"""Host-disjoint out-of-fold competence learning for the eleven frozen experts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import StratifiedGroupKFold

import scripts.experiments.behavioral_supermodel_v2 as behavior_core
import scripts.experiments.behavioral_supermodel_v4 as v4
from scripts.experiments.adaptation_data import INPUTS, MissionBatchPlan, load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.diagnostic_experts import (
    KINDS as DIAGNOSTIC_KINDS,
    DiagnosticExpert,
    extract_features,
    load_models as load_diagnostics,
)
from scripts.experiments.mission_adaptation import (
    ARMS,
    atomic_json,
    validate_config as validate_adaptation_config,
)
from scripts.experiments.physical_experts import FEATURES, KINDS as PHYSICAL_KINDS
from scripts.experiments.transformer_expert import (
    load_models as load_transformers,
    model_from_config,
    validate_transformer_config,
)
from scripts.research.model_comparison import ComparisonScorer
from scripts.research.protocol import ROOT, SCALAR_NAMES, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.cnn.mission_adaptation import MissionAdaptationCNN, reversal_schedule

VERSION = "crossfit_competence_supermodel_v1"
EXPERTS = v4.EXPERTS
REFIT_ARMS = tuple(arm for arm in ARMS if arm != "kepler_only")
DEFAULTS = {
    "schema_version": 1,
    "folds": 5,
    "fold_seed": 8819,
    "training_seed": 9203,
    "ridge_alpha_grid": [.1, 1., 10., 100.],
    "routing_strength_grid": [0., .25, .5, 1., 2., 4.],
    "maximum_target_loss": 10.,
    "cpu_threads": 2,
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown crossfit-competence configuration field")
    config = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("folds", 3, 10),
                           ("fold_seed", 0, 2**31 - 1), ("training_seed", 0, 2**31 - 1),
                           ("cpu_threads", 1, 4)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError("Invalid " + key)
    for key in ("ridge_alpha_grid", "routing_strength_grid"):
        grid = config[key]
        if (not isinstance(grid, list) or not grid or grid != sorted(set(grid))
                or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in grid)):
            raise ValueError("Invalid " + key)
    if config["routing_strength_grid"][0] != 0 or config["ridge_alpha_grid"][0] <= 0:
        raise ValueError("Grids require a static route and positive ridge penalties")
    loss = config["maximum_target_loss"]
    if type(loss) not in (int, float) or not math.isfinite(loss) or not 1 <= loss <= 100:
        raise ValueError("Invalid maximum target loss")
    return config


def subset(part, indices):
    indices = np.asarray(indices, dtype=np.int64)
    result = {key: value[indices] for key, value in part.items() if key != "metadata"}
    result["metadata"] = [part["metadata"][int(i)] for i in indices]
    return result


def make_folds(part, count, seed):
    labels = part["y"].numpy().astype(int)
    groups = np.asarray([str(row["split_group"]) for row in part["metadata"]])
    splitter = StratifiedGroupKFold(n_splits=count, shuffle=True, random_state=seed)
    folds = []
    seen = np.zeros(len(labels), dtype=np.int64)
    for train, heldout in splitter.split(np.zeros(len(labels)), labels, groups):
        if set(groups[train]) & set(groups[heldout]) or set(labels[train]) != {0, 1} or set(labels[heldout]) != {0, 1}:
            raise ValueError("Crossfit fold is not group-disjoint with both classes")
        folds.append((train.astype(np.int64), heldout.astype(np.int64)))
        seen[heldout] += 1
    if not np.all(seen == 1):
        raise ValueError("Every training candidate must be held out exactly once")
    return folds


def train_cnn(arm, fold_data, config, seed):
    if arm not in REFIT_ARMS:
        raise ValueError("Only TESS-dependent CNN arms require fold refitting")
    torch.manual_seed(seed)
    model = MissionAdaptationCNN(adversarial=arm == "dann")
    torch.manual_seed(seed + 100000)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    planner = MissionBatchPlan(fold_data, config["batch_size"], seed)
    class_loss, domain_loss = torch.nn.BCEWithLogitsLoss(), torch.nn.CrossEntropyLoss()
    for step in range(config["steps"]):
        if arm == "fine_tuned" and step == config["pretrain_steps"]:
            optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                          weight_decay=config["weight_decay"])
        model.train()
        inputs, labels, domains = planner.batch(arm, step, config["pretrain_steps"])
        optimizer.zero_grad(set_to_none=True)
        if arm == "dann":
            logits, mission_logits = model(*inputs, grl_strength=reversal_schedule(
                step, config["steps"], config["grl_max"]))
            loss = class_loss(logits, labels) + config["mission_loss_weight"] * domain_loss(
                mission_logits, domains)
        else:
            loss = class_loss(model(*inputs), labels)
        if not torch.isfinite(loss):
            raise ValueError("Crossfit CNN produced nonfinite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["gradient_clip"], error_if_nonfinite=True)
        optimizer.step()
    model.eval()
    return model


def train_transformer(fold_data, config, seed):
    torch.manual_seed(seed)
    model = model_from_config(config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    planner = MissionBatchPlan(fold_data, config["batch_size"], seed)
    train = fold_data["tess"]["train"]
    for step in range(config["steps"]):
        rows = planner.indices("tess", step, config["batch_size"])
        model.train(); optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(
            model(*[train[key][rows] for key in INPUTS]), train["y"][rows])
        if not torch.isfinite(loss):
            raise ValueError("Crossfit Transformer produced nonfinite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["gradient_clip"], error_if_nonfinite=True)
        optimizer.step()
    model.eval()
    return model


def train_diagnostic(kind, train, regularization, max_iterations):
    values = extract_features(train["x_global"], train["x_local"], train["x_scalar"], kind)
    mean, scale = values.mean(axis=0), values.std(axis=0)
    scale[scale < 1e-6] = 1
    fitted = LogisticRegression(C=regularization, max_iter=max_iterations, solver="liblinear",
                                random_state=1701, class_weight="balanced").fit(
                                    (values - mean) / scale, train["y"].numpy())
    model = DiagnosticExpert(kind, mean, scale, fitted.coef_[0], fitted.intercept_[0])
    model.eval()
    return model


def predict_models(models, part):
    by_expert = {expert: [] for expert in EXPERTS[:-len(PHYSICAL_KINDS)]}
    with torch.inference_mode():
        for record, model in models:
            output = model(*[part[key] for key in INPUTS]).numpy()
            if record["arm"] not in by_expert or output.shape != (len(part["y"]),):
                raise ValueError("Malformed crossfit expert prediction")
            by_expert[record["arm"]].append(output)
    if any(not values for values in by_expert.values()):
        raise ValueError("Every nonphysical expert needs a prediction")
    return np.stack([np.stack(by_expert[expert]).mean(axis=0) for expert in by_expert], axis=1).astype(np.float32)


def fit_physical_fold(train_raw, train_available, train_labels, heldout_raw,
                      heldout_available, columns, selected_c, max_iterations):
    logits = np.zeros((len(heldout_raw), len(PHYSICAL_KINDS)), dtype=np.float32)
    for expert_index, kind in enumerate(PHYSICAL_KINDS):
        indices = [columns.index(name) for name in FEATURES[kind]]
        use_train = train_available[:, expert_index]
        mean = train_raw[use_train][:, indices].mean(axis=0)
        scale = train_raw[use_train][:, indices].std(axis=0)
        scale[scale < 1e-6] = 1
        model = LogisticRegression(C=selected_c[kind], max_iter=max_iterations,
                                   solver="liblinear", random_state=1701,
                                   class_weight="balanced").fit(
            (train_raw[use_train][:, indices] - mean) / scale, train_labels[use_train])
        use_heldout = heldout_available[:, expert_index]
        logits[use_heldout, expert_index] = model.decision_function(
            (heldout_raw[use_heldout][:, indices] - mean) / scale).astype(np.float32)
    return logits


def context_matrix(base, physical_raw, physical_available, part, physical_columns):
    period = np.asarray([float(row["period"]) for row in part["metadata"]], dtype=np.float32)
    duration = np.asarray([float(row["duration_hours"]) for row in part["metadata"]], dtype=np.float32)
    disagreement = np.column_stack([base.std(axis=1), base.max(axis=1) - base.min(axis=1)])
    generic = np.column_stack([
        part["x_scalar"].numpy(), np.log(np.maximum(period, 1e-8)),
        np.log(np.maximum(duration, 1e-8)),
        np.log(np.maximum(duration / (24 * period), 1e-8)),
    ])
    context = np.concatenate([
        base, np.abs(base), disagreement, physical_raw,
        physical_available.astype(np.float32), generic,
    ], axis=1).astype(np.float32)
    names = (["logit_" + expert for expert in EXPERTS]
             + ["absolute_logit_" + expert for expert in EXPERTS]
             + ["expert_logit_sd", "expert_logit_range"]
             + ["physical_" + name for name in physical_columns]
             + [kind + "_available" for kind in PHYSICAL_KINDS]
             + ["generic_" + name for name in SCALAR_NAMES]
             + ["generic_log_period", "generic_log_duration", "generic_log_duty_cycle"])
    if context.shape[1] != len(names) or not np.isfinite(context).all():
        raise ValueError("Invalid competence context")
    return context, names


def fit_competence(context, base, availability, labels, alpha, maximum_loss):
    target_loss = np.logaddexp(0, base) - labels[:, None] * base
    target = np.log1p(np.clip(target_loss, 0, maximum_loss))
    coefficient, intercept = [], []
    for expert in range(base.shape[1]):
        use = availability[:, expert]
        model = Ridge(alpha=alpha).fit(context[use], target[use, expert])
        coefficient.append(model.coef_)
        intercept.append(model.intercept_)
    return np.asarray(coefficient, dtype=np.float32), np.asarray(intercept, dtype=np.float32)


def predicted_loss(context, coefficient, intercept, maximum_loss):
    value = context @ coefficient.T + intercept
    return np.expm1(np.clip(value, 0, np.log1p(maximum_loss))).astype(np.float32)


def route(base, availability, prior, expected_loss, strength):
    if (base.shape != availability.shape or base.shape != expected_loss.shape
            or len(prior) != base.shape[1] or not availability.any(axis=1).all()):
        raise ValueError("Invalid competence routing input")
    score = np.log(prior)[None, :] - strength * expected_loss
    score = np.where(availability, score, -np.inf)
    score -= np.max(score, axis=1, keepdims=True)
    weights = np.exp(score)
    weights /= weights.sum(axis=1, keepdims=True)
    return np.sum(weights * base, axis=1).astype(np.float32), weights.astype(np.float32)


def _atomic_npz(path, **arrays):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def build_oof_fold(fold_number, train_indices, heldout_indices, data, full_models,
                   physical_features, physical_predictions, physical_columns,
                   adaptation_config, transformer_config, diagnostic_config,
                   physical_config, selected_diagnostic_c, selected_physical_c,
                   training_seed):
    tess_train = data["tess"]["train"]
    fold_train, heldout = subset(tess_train, train_indices), subset(tess_train, heldout_indices)
    fold_data = {"kepler": data["kepler"], "tess": {**data["tess"], "train": fold_train}}
    models = [(record, model) for record, model in full_models if record["arm"] == "kepler_only"]
    for offset, arm in enumerate(REFIT_ARMS):
        seed = training_seed + fold_number * 100 + offset
        models.append(({"arm": arm, "seed": seed}, train_cnn(arm, fold_data, adaptation_config, seed)))
        print(json.dumps({"stage": "crossfit", "fold": fold_number, "trained": arm}), flush=True)
    transformer_seed = training_seed + fold_number * 100 + 20
    models.append(({"arm": "transformer", "seed": transformer_seed},
                   train_transformer(fold_data, transformer_config, transformer_seed)))
    print(json.dumps({"stage": "crossfit", "fold": fold_number, "trained": "transformer"}), flush=True)
    for kind in DIAGNOSTIC_KINDS:
        models.append(({"arm": kind, "seed": 1701}, train_diagnostic(
            kind, fold_train, selected_diagnostic_c[kind], diagnostic_config["max_iterations"])))
    neural = predict_models(models, heldout)
    _, train_available, train_raw, train_columns = v4.align_physical(
        fold_train, physical_features, physical_predictions)
    _, heldout_available, heldout_raw, heldout_columns = v4.align_physical(
        heldout, physical_features, physical_predictions)
    if train_columns != physical_columns or heldout_columns != physical_columns:
        raise ValueError("Physical feature order changed during crossfit")
    physical_logits = fit_physical_fold(
        train_raw, train_available, fold_train["y"].numpy(), heldout_raw,
        heldout_available, physical_columns, selected_physical_c,
        physical_config["max_iterations"])
    base = np.concatenate([neural, physical_logits], axis=1).astype(np.float32)
    availability = np.concatenate([
        np.ones_like(neural, dtype=bool), heldout_available], axis=1)
    return {"heldout_indices": heldout_indices, "base": base,
            "availability": availability, "physical_raw": heldout_raw}


def load_or_build_oof(output, folds, data, full_models, physical_features,
                      physical_predictions, physical_columns, configs, selected_c):
    folder = output / "folds"; folder.mkdir(parents=True, exist_ok=True)
    pieces = []
    for number, (train_indices, heldout_indices) in enumerate(folds):
        path, receipt_path = folder / f"fold-{number}.npz", folder / f"fold-{number}.json"
        if path.is_file() and receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text())
            if receipt.get("sha256") != file_sha256(path):
                raise ValueError("Crossfit fold cache checksum mismatch")
            with np.load(path, allow_pickle=False) as saved:
                piece = {key: saved[key] for key in saved.files}
            if not np.array_equal(piece["heldout_indices"], heldout_indices):
                raise ValueError("Crossfit fold cache identity mismatch")
            print(json.dumps({"stage": "crossfit", "fold": number, "status": "reused"}), flush=True)
        else:
            piece = build_oof_fold(
                number, train_indices, heldout_indices, data, full_models,
                physical_features, physical_predictions, physical_columns,
                configs["adaptation"], configs["transformer"], configs["diagnostic"],
                configs["physical"], selected_c["diagnostic"], selected_c["physical"],
                configs["competence"]["training_seed"])
            _atomic_npz(path, **piece)
            atomic_json(receipt_path, {"fold": number, "heldout_count": len(heldout_indices),
                                      "sha256": file_sha256(path)})
            print(json.dumps({"stage": "crossfit", "fold": number, "status": "complete"}), flush=True)
        pieces.append(piece)
    size = len(data["tess"]["train"]["y"])
    base = np.empty((size, len(EXPERTS)), dtype=np.float32)
    availability = np.empty((size, len(EXPERTS)), dtype=bool)
    physical_raw = np.empty((size, len(physical_columns)), dtype=np.float32)
    filled = np.zeros(size, dtype=bool)
    for piece in pieces:
        indices = piece["heldout_indices"]
        if filled[indices].any():
            raise ValueError("Duplicate crossfit heldout prediction")
        base[indices], availability[indices], physical_raw[indices] = (
            piece["base"], piece["availability"], piece["physical_raw"])
        filled[indices] = True
    if not filled.all() or not np.isfinite(base).all() or not np.isfinite(physical_raw).all():
        raise ValueError("Incomplete crossfit predictions")
    return base, availability, physical_raw


def full_role(full_models, part, physical_features, physical_predictions):
    neural = predict_models(full_models, part)
    physical_logits, physical_available, physical_raw, columns = v4.align_physical(
        part, physical_features, physical_predictions)
    base = np.concatenate([neural, physical_logits], axis=1).astype(np.float32)
    availability = np.concatenate([np.ones_like(neural, dtype=bool), physical_available], axis=1)
    return base, availability, physical_raw, columns


def choose_competence_model(train, selection, prior, config):
    candidates = []
    for alpha in config["ridge_alpha_grid"]:
        coefficient, intercept = fit_competence(
            train["context"], train["base"], train["availability"], train["labels"],
            alpha, config["maximum_target_loss"])
        loss = predicted_loss(selection["context"], coefficient, intercept,
                              config["maximum_target_loss"])
        for strength in config["routing_strength_grid"]:
            logits, _ = route(selection["base"], selection["availability"], prior, loss, strength)
            score = metrics(selection["labels"], logits)
            candidates.append(({"ridge_alpha": float(alpha), "routing_strength": float(strength),
                                "selection_average_precision": score["average_precision"],
                                "selection_nll": score["nll"], "selection_brier": score["brier"]},
                               coefficient, intercept))
    # Ranking is the primary declared endpoint; simpler routing breaks numerical ties.
    row, coefficient, intercept = max(
        candidates, key=lambda item: (round(item[0]["selection_average_precision"], 10),
                                      -item[0]["selection_nll"],
                                      -item[0]["routing_strength"], item[0]["ridge_alpha"]))
    return row, coefficient, intercept, [item[0] for item in candidates]


def routing_diagnostics(weights, base, availability, labels):
    actual_loss = np.logaddexp(0, base) - labels[:, None] * base
    actual_loss = np.where(availability, actual_loss, np.inf)
    selected, oracle = weights.argmax(axis=1), actual_loss.argmin(axis=1)
    return {"top_route_matches_lowest_loss_expert": float(np.mean(selected == oracle)),
            "mean_weights": dict(zip(EXPERTS, weights.mean(axis=0).astype(float).tolist())),
            "top_routed_count": {expert: int(np.sum(selected == i)) for i, expert in enumerate(EXPERTS)}}


def run(output, configs, full_models, data, physical_features, physical_predictions,
        prior, selected_c):
    folds = make_folds(data["tess"]["train"], configs["competence"]["folds"],
                       configs["competence"]["fold_seed"])
    _, _, _, physical_columns = full_role(
        full_models, data["tess"]["selection"], physical_features, physical_predictions)
    oof_base, oof_available, oof_physical = load_or_build_oof(
        output, folds, data, full_models, physical_features, physical_predictions,
        physical_columns, configs, selected_c)
    roles = {}
    train_part = data["tess"]["train"]
    context, names = context_matrix(oof_base, oof_physical, oof_available[:, -3:],
                                    train_part, physical_columns)
    roles["train"] = {"base": oof_base, "availability": oof_available,
                      "context_raw": context, "labels": train_part["y"].numpy()}
    for role in ("selection", "calibration", "audit"):
        part = data["tess"][role]
        base, available, raw, columns = full_role(full_models, part, physical_features, physical_predictions)
        if columns != physical_columns:
            raise ValueError("Physical feature order differs between roles")
        context, role_names = context_matrix(base, raw, available[:, -3:], part, physical_columns)
        if role_names != names:
            raise ValueError("Competence context names differ between roles")
        roles[role] = {"base": base, "availability": available,
                       "context_raw": context, "labels": part["y"].numpy()}
    moments = behavior_core.fit_transform(roles["train"]["context_raw"])
    for role in roles:
        roles[role]["context"] = behavior_core.transform(roles[role]["context_raw"], moments)
    selected, coefficient, intercept, search = choose_competence_model(
        roles["train"], roles["selection"], prior, configs["competence"])
    expected = {role: predicted_loss(roles[role]["context"], coefficient, intercept,
                                     configs["competence"]["maximum_target_loss"])
                for role in roles}
    routed = {role: route(roles[role]["base"], roles[role]["availability"], prior,
                          expected[role], selected["routing_strength"])
              for role in roles}
    static = {role: route(roles[role]["base"], roles[role]["availability"], prior,
                          np.zeros_like(roles[role]["base"]), 0.)[0]
              for role in roles}
    temperatures = {
        "static": fit_temperature(roles["calibration"]["labels"], static["calibration"]),
        "competence": fit_temperature(roles["calibration"]["labels"], routed["calibration"][0]),
    }
    audit = {
        "v4_static_stack": metrics(roles["audit"]["labels"], static["audit"]),
        "v4_static_stack_calibrated": metrics(
            roles["audit"]["labels"], static["audit"], temperatures["static"]["temperature"]),
        "crossfit_competence": metrics(roles["audit"]["labels"], routed["audit"][0]),
        "crossfit_competence_calibrated": metrics(
            roles["audit"]["labels"], routed["audit"][0], temperatures["competence"]["temperature"]),
    }
    for index, expert in enumerate(EXPERTS):
        use = roles["audit"]["availability"][:, index]
        audit[expert] = {**metrics(roles["audit"]["labels"][use], roles["audit"]["base"][use, index]),
                         "available": int(use.sum())}
    best_single = max(EXPERTS, key=lambda expert: audit[expert]["average_precision"])
    improved = (audit["crossfit_competence"]["average_precision"] > max(
                    audit["v4_static_stack"]["average_precision"], audit[best_single]["average_precision"])
                and audit["crossfit_competence_calibrated"]["brier"]
                < audit["v4_static_stack_calibrated"]["brier"])
    summary = {
        "status": "complete", "version": VERSION, "generated_at": utc_now(),
        "experts": list(EXPERTS), "partitions": {role: len(value["labels"]) for role, value in roles.items()},
        "crossfit": {"folds": len(folds), "group_disjoint": True,
                     "every_training_candidate_held_out_once": True,
                     "kepler_only_reuse_reason": "trained_without_TESS_labels"},
        "selected_configuration": selected, "selection_search": search,
        "calibration": temperatures, "audit": audit,
        "best_single_on_reused_audit": best_single,
        "routing": {role: routing_diagnostics(routed[role][1], roles[role]["base"],
                                               roles[role]["availability"], roles[role]["labels"])
                    for role in ("selection", "calibration", "audit")},
        "claims": {"beats_static_and_best_single_on_declared_metrics": bool(improved),
                   "original_test_evaluated": False, "prospective_confirmation": False,
                   "deployed_to_watcher": False, "planet_probability": False},
        "limitations": [
            "The audit is validation-derived and was consulted by earlier experiments",
            "Fold experts use one seed and a fixed bounded update budget",
            "Selection labels choose ridge penalty and routing strength",
            "Known catalog ephemerides are used by the labelled physical experts",
            "A new frozen host-disjoint evaluation is required for a paper-level claim",
        ],
    }
    artifact = {
        "version": VERSION, "experts": list(EXPERTS), "config": configs["competence"],
        "feature_names": names, "feature_mean": torch.from_numpy(moments[0]),
        "feature_scale": torch.from_numpy(moments[1]), "prior": torch.from_numpy(prior),
        "competence_coefficient": torch.from_numpy(coefficient),
        "competence_intercept": torch.from_numpy(intercept),
        "selected_configuration": selected,
        "calibration_temperature": temperatures["competence"]["temperature"],
    }
    return summary, artifact


def write_report(path, summary):
    audit = summary["audit"]
    display = (summary["best_single_on_reused_audit"], "v4_static_stack",
               "v4_static_stack_calibrated", "crossfit_competence",
               "crossfit_competence_calibrated")
    lines = ["# Cross-fitted competence supermodel", "",
             "Each competence target comes from an expert that did not train on that TESS host.", "",
             "| Method | AP | ROC AUC | Brier | NLL | Accuracy |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in display:
        row = audit[name]; threshold = row["at_0_5"]
        accuracy = (threshold["tp"] + threshold["tn"]) / row["n"]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | "
                     f"{row['roc_auc']:.4f} | {row['brier']:.4f} | {row['nll']:.4f} | {accuracy:.4f} |")
    selected = summary["selected_configuration"]
    lines += ["", "## Frozen selection", "",
              f"Selection chose ridge alpha **{selected['ridge_alpha']}** and routing strength "
              f"**{selected['routing_strength']}** using AP as the primary endpoint.",
              f"Audit top-route/oracle agreement: **{summary['routing']['audit']['top_route_matches_lowest_loss_expert']:.1%}**.",
              f"It beat the static stack and best single expert on the declared metrics: "
              f"**{summary['claims']['beats_static_and_best_single_on_declared_metrics']}**.",
              "", "## Boundaries", "", *["- " + item for item in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/crossfit_competence_v1.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--transformer-config", default="configs/transformer_expert_pilot_v1.json")
    parser.add_argument("--diagnostic-config", default="configs/diagnostic_experts_v1.json")
    parser.add_argument("--physical-config", default="configs/physical_experts_v1.json")
    parser.add_argument("--cnn-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--diagnostic-run", default="outputs/research/diagnostic_experts/pilot-v2")
    parser.add_argument("--physical-run", default="outputs/research/physical_experts/pilot-v1")
    parser.add_argument("--v4-run", default="results/behavioral_supermodel_v4")
    parser.add_argument("--output", default="results/crossfit_competence_v1")
    args = parser.parse_args(argv)
    configs = {
        "competence": validate_config(json.loads((ROOT / args.config).read_text())),
        "adaptation": validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text())),
        "transformer": validate_transformer_config(json.loads((ROOT / args.transformer_config).read_text())),
        "diagnostic": __import__("scripts.experiments.diagnostic_experts", fromlist=["validate_config"]).validate_config(
            json.loads((ROOT / args.diagnostic_config).read_text())),
        "physical": __import__("scripts.experiments.physical_experts", fromlist=["validate_config"]).validate_config(
            json.loads((ROOT / args.physical_config).read_text())),
    }
    torch.set_num_threads(configs["competence"]["cpu_threads"])
    paths = {name: ROOT / value for name, value in (
        ("cnn", args.cnn_run), ("transformer", args.transformer_run),
        ("diagnostic", args.diagnostic_run), ("physical", args.physical_run), ("v4", args.v4_run))}
    receipts = {name: json.loads((path / "complete.json").read_text()) for name, path in paths.items()}
    scorer = ComparisonScorer(paths["cnn"].parent, paths["cnn"].name, receipts["cnn"]["spec_sha256"])
    full_models = scorer.models + load_transformers(paths["transformer"], receipts["transformer"]["spec_sha256"])
    full_models += load_diagnostics(paths["diagnostic"], receipts["diagnostic"]["spec_sha256"])
    data, provenance = load_prepared(ROOT, configs["adaptation"])
    physical_features, physical_predictions = v4._physical_tables(paths["physical"], receipts["physical"])
    v4_path = paths["v4"] / "behavioral_supermodel.pt"
    if receipts["v4"]["files"].get("behavioral_supermodel.pt") != file_sha256(v4_path):
        raise ValueError("v4 prior checksum mismatch")
    prior = __import__("scripts.experiments.behavioral_supermodel_v5", fromlist=["v4_prior"]).v4_prior(
        torch.load(v4_path, map_location="cpu", weights_only=True))
    diagnostic_summary = json.loads((paths["diagnostic"] / "summary.json").read_text())
    physical_summary = json.loads((paths["physical"] / "summary.json").read_text())
    selected_c = {
        "diagnostic": {kind: diagnostic_summary["results"][kind]["selected_c"] for kind in DIAGNOSTIC_KINDS},
        "physical": {kind: physical_summary["experts"][kind]["selected_c"] for kind in PHYSICAL_KINDS},
    }
    output = ROOT / args.output; output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/crossfit_competence.py",
               "scripts/experiments/behavioral_supermodel_v4.py",
               "scripts/experiments/diagnostic_experts.py",
               "scripts/experiments/physical_experts.py",
               "training/cnn/mission_adaptation.py", "training/transformer_expert.py")
    spec = {"version": VERSION, "configs": configs, "selected_regularization": selected_c,
            "source_specs": {name: receipt["spec_sha256"] for name, receipt in receipts.items()},
            "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.is_file() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing crossfit output has a different specification")
    if (output / "complete.json").is_file():
        raise ValueError("Crossfit competence output is already complete")
    atomic_json(spec_path, spec)
    summary, artifact = run(output, configs, full_models, data, physical_features,
                            physical_predictions, prior, selected_c)
    summary["spec_sha256"] = artifact["spec_sha256"] = spec_sha
    torch.save(artifact, output / "competence_model.pt")
    atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "competence_model.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "selected": summary["selected_configuration"],
                      "best_single": summary["best_single_on_reused_audit"],
                      "claim": summary["claims"]["beats_static_and_best_single_on_declared_metrics"],
                      "audit": {name: summary["audit"][name] for name in
                                ("v4_static_stack", "crossfit_competence",
                                 "crossfit_competence_calibrated")}}, indent=2))


if __name__ == "__main__":
    main()
