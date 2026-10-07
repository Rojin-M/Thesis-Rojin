"""Nonlinear supermodel trained on host-disjoint out-of-fold expert behavior."""
from __future__ import annotations

import argparse
import hashlib
import json
import math

import joblib
import numpy as np
import torch
from scipy.special import expit, logit
from sklearn.ensemble import HistGradientBoostingClassifier

import scripts.experiments.behavioral_supermodel_v4 as v4
from scripts.experiments.adaptation_data import load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.crossfit_competence import (
    EXPERTS,
    VERSION as CROSSFIT_VERSION,
    context_matrix,
    full_role,
    validate_config as validate_crossfit_config,
)
from scripts.experiments.diagnostic_experts import load_models as load_diagnostics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.experiments.transformer_expert import load_models as load_transformers
from scripts.research.model_comparison import ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "crossfit_nonlinear_supermodel_v2"
DEFAULTS = {
    "schema_version": 1,
    "max_leaf_nodes_grid": [7, 15, 31],
    "l2_regularization_grid": [1., 10., 100.],
    "blend_grid": [0., .05, .1, .2, .35, .5, .75, 1.],
    "max_iterations": 150,
    "learning_rate": .05,
    "minimum_leaf_samples": 20,
    "random_seed": 331,
    "cpu_threads": 2,
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown nonlinear-supermodel configuration field")
    config = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("max_iterations", 20, 2000),
                           ("minimum_leaf_samples", 2, 200), ("random_seed", 0, 2**31 - 1),
                           ("cpu_threads", 1, 4)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError("Invalid " + key)
    for key, positive in (("max_leaf_nodes_grid", True), ("l2_regularization_grid", True),
                          ("blend_grid", False)):
        grid = config[key]
        if (not isinstance(grid, list) or not grid or grid != sorted(set(grid))
                or any(type(x) not in (int, float) or not math.isfinite(x)
                       or (x <= 0 if positive else x < 0) for x in grid)):
            raise ValueError("Invalid " + key)
    if (config["blend_grid"][0] != 0 or config["blend_grid"][-1] > 1
            or max(config["max_leaf_nodes_grid"]) > 255
            or max(config["l2_regularization_grid"]) > 1000):
        raise ValueError("Unsafe nonlinear-supermodel grid")
    for key in ("learning_rate",):
        if type(config[key]) not in (int, float) or not 0 < config[key] <= 1:
            raise ValueError("Invalid " + key)
    return config


def load_oof(folder, size, experts, physical_features):
    base = np.empty((size, experts), dtype=np.float32)
    availability = np.empty((size, experts), dtype=bool)
    physical = np.empty((size, physical_features), dtype=np.float32)
    filled = np.zeros(size, dtype=bool)
    receipts = {}
    for receipt_path in sorted(folder.glob("fold-*.json")):
        receipt = json.loads(receipt_path.read_text())
        path = receipt_path.with_suffix(".npz")
        digest = file_sha256(path)
        if receipt.get("sha256") != digest:
            raise ValueError("Crossfit fold checksum mismatch")
        with np.load(path, allow_pickle=False) as saved:
            indices = saved["heldout_indices"]
            if filled[indices].any():
                raise ValueError("Duplicate crossfit candidate")
            base[indices] = saved["base"]
            availability[indices] = saved["availability"]
            physical[indices] = saved["physical_raw"]
            filled[indices] = True
        receipts[str(path.relative_to(ROOT))] = digest
        receipts[str(receipt_path.relative_to(ROOT))] = file_sha256(receipt_path)
    if not filled.all() or len(receipts) != 10:
        raise ValueError("Five complete crossfit folds are required")
    return base, availability, physical, receipts


def static_logits(base, availability, prior):
    weights = prior[None, :] * availability
    weights = weights / weights.sum(axis=1, keepdims=True)
    return np.sum(weights * base, axis=1).astype(np.float32)


def meta_logits(model, context):
    probability = np.clip(model.predict_proba(context)[:, 1], 1e-5, 1 - 1e-5)
    return logit(probability).astype(np.float32)


def blend_logits(static, meta, strength):
    if static.shape != meta.shape or not 0 <= strength <= 1:
        raise ValueError("Invalid supermodel blend")
    return (static + strength * (meta - static)).astype(np.float32)


def fit_model(context, labels, config, leaves, regularization):
    model = HistGradientBoostingClassifier(
        max_iter=config["max_iterations"], learning_rate=config["learning_rate"],
        max_leaf_nodes=leaves, min_samples_leaf=config["minimum_leaf_samples"],
        l2_regularization=regularization, random_state=config["random_seed"])
    model.fit(context, labels)
    return model


def select_model(train, selection, config):
    candidates = []
    for leaves in config["max_leaf_nodes_grid"]:
        for regularization in config["l2_regularization_grid"]:
            model = fit_model(train["context"], train["labels"], config, leaves, regularization)
            meta = meta_logits(model, selection["context"])
            for blend in config["blend_grid"]:
                logits = blend_logits(selection["static"], meta, blend)
                score = metrics(selection["labels"], logits)
                candidates.append(({
                    "max_leaf_nodes": int(leaves), "l2_regularization": float(regularization),
                    "blend": float(blend), "selection_average_precision": score["average_precision"],
                    "selection_nll": score["nll"], "selection_brier": score["brier"],
                }, model))
    # Ranking is primary. NLL, smaller blend, stronger regularization, then fewer leaves break ties.
    selected, model = max(candidates, key=lambda item: (
        round(item[0]["selection_average_precision"], 10), -item[0]["selection_nll"],
        -item[0]["blend"], item[0]["l2_regularization"], -item[0]["max_leaf_nodes"]))
    return selected, model, [row for row, _ in candidates]


def accuracy(row):
    threshold = row["at_0_5"]
    return (threshold["tp"] + threshold["tn"]) / row["n"]


def run(config, full_models, data, physical_features, physical_predictions, prior, oof_folder):
    train_part = data["tess"]["train"]
    # Establish the physical feature contract from the frozen full experts.
    selection_values = full_role(full_models, data["tess"]["selection"],
                                 physical_features, physical_predictions)
    physical_columns = selection_values[3]
    oof_base, oof_available, oof_physical, fold_receipts = load_oof(
        oof_folder, len(train_part["y"]), len(EXPERTS), len(physical_columns))
    context, names = context_matrix(oof_base, oof_physical, oof_available[:, -3:],
                                    train_part, physical_columns)
    roles = {"train": {"base": oof_base, "availability": oof_available, "context": context,
                       "labels": train_part["y"].numpy()}}
    for role in ("selection", "calibration", "audit"):
        if role == "selection":
            base, available, raw, columns = selection_values
        else:
            base, available, raw, columns = full_role(
                full_models, data["tess"][role], physical_features, physical_predictions)
        role_context, role_names = context_matrix(
            base, raw, available[:, -3:], data["tess"][role], columns)
        if columns != physical_columns or role_names != names:
            raise ValueError("Nonlinear supermodel feature contract differs between roles")
        roles[role] = {"base": base, "availability": available, "context": role_context,
                       "labels": data["tess"][role]["y"].numpy(),
                       "static": static_logits(base, available, prior)}
    selected, model, search = select_model(roles["train"], roles["selection"], config)
    final = {}
    for role in ("selection", "calibration"):
        final[role] = blend_logits(roles[role]["static"], meta_logits(model, roles[role]["context"]),
                                   selected["blend"])
    temperature = fit_temperature(roles["calibration"]["labels"], final["calibration"])
    static_temperature = fit_temperature(roles["calibration"]["labels"], roles["calibration"]["static"])
    # Audit is touched only after architecture, hyperparameters, blend and temperature are frozen.
    final["audit"] = blend_logits(roles["audit"]["static"], meta_logits(model, roles["audit"]["context"]),
                                  selected["blend"])
    audit = {
        "v4_static_stack": metrics(roles["audit"]["labels"], roles["audit"]["static"]),
        "v4_static_stack_calibrated": metrics(
            roles["audit"]["labels"], roles["audit"]["static"], static_temperature["temperature"]),
        "crossfit_nonlinear": metrics(roles["audit"]["labels"], final["audit"]),
        "crossfit_nonlinear_calibrated": metrics(
            roles["audit"]["labels"], final["audit"], temperature["temperature"]),
    }
    for index, expert in enumerate(EXPERTS):
        use = roles["audit"]["availability"][:, index]
        audit[expert] = {**metrics(roles["audit"]["labels"][use], roles["audit"]["base"][use, index]),
                         "available": int(use.sum())}
    best_single = max(EXPERTS, key=lambda expert: audit[expert]["average_precision"])
    improved = (audit["crossfit_nonlinear"]["average_precision"] > max(
                    audit["v4_static_stack"]["average_precision"], audit[best_single]["average_precision"])
                and audit["crossfit_nonlinear_calibrated"]["brier"]
                < min(audit["v4_static_stack_calibrated"]["brier"], audit[best_single]["brier"]))
    summary = {
        "status": "complete", "version": VERSION, "generated_at": utc_now(),
        "experts": list(EXPERTS), "partitions": {role: len(value["labels"]) for role, value in roles.items()},
        "training_contract": "538_host_disjoint_out_of_fold_predictions_from_crossfit_competence_v1",
        "selected_configuration": selected, "selection_search": search,
        "calibration": {"crossfit_nonlinear": temperature, "v4_static": static_temperature},
        "audit": audit, "best_single_on_reused_audit": best_single,
        "selection_gain": {
            "average_precision": selected["selection_average_precision"]
                                 - metrics(roles["selection"]["labels"], roles["selection"]["static"])["average_precision"],
            "nll": selected["selection_nll"]
                   - metrics(roles["selection"]["labels"], roles["selection"]["static"])["nll"],
        },
        "claims": {"beats_static_and_best_single_on_declared_metrics": bool(improved),
                   "original_test_evaluated": False, "prospective_confirmation": False,
                   "deployed_to_watcher": False, "planet_probability": False},
        "limitations": [
            "The audit is validation-derived and was consulted by earlier experiments",
            "Selection labels choose tree complexity, regularization and blend strength",
            "Physical experts use known catalog ephemerides on these labelled examples",
            "A new frozen host-disjoint evaluation is required for a paper-level claim",
        ],
    }
    artifact = {"version": VERSION, "experts": list(EXPERTS), "config": config,
                "feature_names": names, "prior": prior, "selected_configuration": selected,
                "calibration_temperature": temperature["temperature"], "model": model}
    return summary, artifact, fold_receipts


def write_report(path, summary):
    audit = summary["audit"]
    display = (summary["best_single_on_reused_audit"], "v4_static_stack",
               "v4_static_stack_calibrated", "crossfit_nonlinear",
               "crossfit_nonlinear_calibrated")
    lines = ["# Cross-fitted nonlinear supermodel v2", "",
             "A regularized nonlinear classifier learns joint failure patterns from 538 host-disjoint "
             "out-of-fold expert predictions, then blends with the v4 prior.", "",
             "| Method | AP | ROC AUC | Brier | NLL | Accuracy |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in display:
        row = audit[name]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | "
                     f"{row['roc_auc']:.4f} | {row['brier']:.4f} | {row['nll']:.4f} | {accuracy(row):.4f} |")
    chosen = summary["selected_configuration"]
    lines += ["", "## Frozen selection", "",
              f"Selection chose **{chosen['max_leaf_nodes']} leaves**, L2 **{chosen['l2_regularization']}** "
              f"and blend **{chosen['blend']}**.",
              f"Selection AP gain over v4: **{summary['selection_gain']['average_precision']:+.4f}**.",
              f"It beat the static stack and strongest single expert on both declared audit metrics: "
              f"**{summary['claims']['beats_static_and_best_single_on_declared_metrics']}**.",
              "", "## Boundaries", "", *["- " + item for item in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/crossfit_supermodel_v2.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--cnn-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--diagnostic-run", default="outputs/research/diagnostic_experts/pilot-v2")
    parser.add_argument("--physical-run", default="outputs/research/physical_experts/pilot-v1")
    parser.add_argument("--v4-run", default="results/behavioral_supermodel_v4")
    parser.add_argument("--crossfit-run", default="results/crossfit_competence_v1")
    parser.add_argument("--output", default="results/crossfit_supermodel_v2")
    args = parser.parse_args(argv)
    config = validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    paths = {name: ROOT / value for name, value in (
        ("cnn", args.cnn_run), ("transformer", args.transformer_run),
        ("diagnostic", args.diagnostic_run), ("physical", args.physical_run),
        ("v4", args.v4_run), ("crossfit", args.crossfit_run))}
    receipts = {name: json.loads((path / "complete.json").read_text()) for name, path in paths.items()}
    crossfit_artifact = torch.load(paths["crossfit"] / "competence_model.pt",
                                   map_location="cpu", weights_only=True)
    if crossfit_artifact.get("version") != CROSSFIT_VERSION:
        raise ValueError("Crossfit source version mismatch")
    validate_crossfit_config(crossfit_artifact["config"])
    scorer = ComparisonScorer(paths["cnn"].parent, paths["cnn"].name, receipts["cnn"]["spec_sha256"])
    full_models = scorer.models + load_transformers(paths["transformer"], receipts["transformer"]["spec_sha256"])
    full_models += load_diagnostics(paths["diagnostic"], receipts["diagnostic"]["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation)
    physical_features, physical_predictions = v4._physical_tables(paths["physical"], receipts["physical"])
    prior = crossfit_artifact["prior"].numpy()
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Nonlinear crossfit output already exists")
    output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/crossfit_supermodel_v2.py",
               "scripts/experiments/crossfit_competence.py")
    spec = {"version": VERSION, "config": config,
            "source_specs": {name: receipt["spec_sha256"] for name, receipt in receipts.items()},
            "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact, fold_receipts = run(
        config, full_models, data, physical_features, physical_predictions, prior,
        paths["crossfit"] / "folds")
    summary["spec_sha256"] = spec_sha; artifact["spec_sha256"] = spec_sha
    model_path = output / "supermodel.joblib"
    temporary = model_path.with_suffix(".joblib.tmp")
    joblib.dump(artifact, temporary); temporary.replace(model_path)
    atomic_json(output / "spec.json", {**spec, "crossfit_fold_files": fold_receipts})
    atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "supermodel.joblib")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "selected": summary["selected_configuration"],
                      "claim": summary["claims"]["beats_static_and_best_single_on_declared_metrics"],
                      "best_single": summary["best_single_on_reused_audit"],
                      "audit": {name: summary["audit"][name] for name in
                                ("v4_static_stack", "crossfit_nonlinear",
                                 "crossfit_nonlinear_calibrated")}}, indent=2))


if __name__ == "__main__":
    main()
