"""Diagnostic-conditioned routing over the eleven frozen v4 experts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math

import numpy as np
import torch
from torch import nn

import scripts.experiments.behavioral_supermodel_v2 as core
import scripts.experiments.behavioral_supermodel_v3 as v3
import scripts.experiments.behavioral_supermodel_v4 as v4
from scripts.experiments.adaptation_data import load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.diagnostic_experts import load_models as load_diagnostics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.experiments.physical_experts import FEATURES, KINDS
from scripts.experiments.transformer_expert import load_models as load_transformers
from scripts.research.model_comparison import ComparisonScorer
from scripts.research.protocol import ROOT, SCALAR_NAMES, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "diagnostic_conditioned_supermodel_v5"
EXPERTS = v4.EXPERTS
DEFAULTS = {
    "schema_version": 1,
    "router_seeds": [701, 709, 719],
    "steps": 600,
    "learning_rate": .01,
    "weight_decay": .1,
    "competence_weight": .1,
    "competence_temperature": .5,
    "shrinkage_grid": [0., .15, .35, .7],
    "prior_kl_grid": [.25, 1., 4.],
    "max_grad_norm": 5.,
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown diagnostic-router configuration field")
    config = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("steps", 20, 10000)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError("Invalid " + key)
    seeds = config["router_seeds"]
    if (not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds))
            or any(type(seed) is not int or seed < 0 for seed in seeds)):
        raise ValueError("Invalid router seeds")
    for key in ("shrinkage_grid", "prior_kl_grid"):
        grid = config[key]
        if (not isinstance(grid, list) or not grid or grid != sorted(set(grid))
                or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in grid)):
            raise ValueError("Invalid " + key)
    if config["shrinkage_grid"][0] != 0:
        raise ValueError("Shrinkage grid must include the static prior")
    for key in ("learning_rate", "weight_decay", "competence_weight",
                "competence_temperature", "max_grad_norm"):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid " + key)
    if (config["learning_rate"] > 1 or config["weight_decay"] > 10
            or config["competence_weight"] > 10 or config["competence_temperature"] > 10
            or config["max_grad_norm"] > 100 or max(config["shrinkage_grid"]) > 5
            or max(config["prior_kl_grid"]) > 100):
        raise ValueError("Unsafe diagnostic-router configuration")
    return config


class DiagnosticRouter(nn.Module):
    """A masked linear adjustment around a fixed global expert prior."""

    def __init__(self, prior, feature_mask, shrinkage, seed=0):
        super().__init__()
        prior = torch.as_tensor(prior, dtype=torch.float32)
        feature_mask = torch.as_tensor(feature_mask, dtype=torch.float32)
        if (prior.ndim != 1 or feature_mask.ndim != 2 or feature_mask.shape[0] != len(prior)
                or not torch.isfinite(prior).all() or (prior <= 0).any()
                or not torch.allclose(prior.sum(), torch.tensor(1.), atol=1e-5)
                or not (feature_mask.sum(dim=1) > 0).all() or shrinkage < 0):
            raise ValueError("Invalid diagnostic router prior or feature mask")
        self.register_buffer("prior", prior)
        self.register_buffer("feature_mask", feature_mask)
        self.shrinkage = float(shrinkage)
        generator = torch.Generator().manual_seed(seed)
        initial = torch.randn(feature_mask.shape, generator=generator) * .01
        self.coefficient = nn.Parameter(initial * feature_mask)

    def forward(self, context, logits, availability):
        if (context.ndim != 2 or logits.ndim != 2 or availability.shape != logits.shape
                or context.shape[0] != logits.shape[0] or logits.shape[1] != len(self.prior)
                or context.shape[1] != self.feature_mask.shape[1]
                or not availability.any(dim=1).all()):
            raise ValueError("Malformed diagnostic router input")
        adjustment = context @ (self.coefficient * self.feature_mask).T
        route = torch.log(self.prior).unsqueeze(0) + self.shrinkage * adjustment
        route = route.masked_fill(~availability, -torch.inf)
        weights = torch.softmax(route, dim=1)
        return torch.sum(weights * logits, dim=1), weights


def competence_targets(logits, labels, availability, temperature):
    losses = torch.nn.functional.binary_cross_entropy_with_logits(
        logits, labels[:, None].expand_as(logits), reduction="none")
    scores = (-losses / temperature).masked_fill(~availability, -torch.inf)
    return torch.softmax(scores, dim=1)


def train_router(context, logits, availability, labels, prior, feature_mask,
                 config, shrinkage, prior_kl, seed):
    model = DiagnosticRouter(prior, feature_mask, shrinkage, seed)
    x = torch.as_tensor(context)
    base = torch.as_tensor(logits)
    available = torch.as_tensor(availability)
    y = torch.as_tensor(labels)
    target = competence_targets(base, y, available, config["competence_temperature"])
    prior_tensor = torch.as_tensor(prior).unsqueeze(0) * available
    prior_tensor = prior_tensor / prior_tensor.sum(dim=1, keepdim=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        fused, weights = model(x, base, available)
        predictive = torch.nn.functional.binary_cross_entropy_with_logits(fused, y)
        competence = -(target * torch.log(weights.clamp_min(1e-8))).sum(dim=1).mean()
        divergence = (weights * (torch.log(weights.clamp_min(1e-8))
                                 - torch.log(prior_tensor.clamp_min(1e-8)))).sum(dim=1).mean()
        loss = predictive + config["competence_weight"] * competence + prior_kl * divergence
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["max_grad_norm"])
        optimizer.step()
    model.eval()
    return model


def apply_routers(models, context, logits, availability):
    x, base, available = map(torch.as_tensor, (context, logits, availability))
    with torch.inference_mode():
        outputs = [model(x, base, available) for model in models]
    fused = np.stack([item[0].numpy() for item in outputs]).mean(axis=0)
    weights = np.stack([item[1].numpy() for item in outputs]).mean(axis=0)
    return fused.astype(np.float32), weights.astype(np.float32)


def v4_prior(artifact):
    if artifact.get("version") != v4.VERSION or artifact.get("experts") != list(EXPERTS):
        raise ValueError("The routing prior is not the expected v4 artifact")
    routes = []
    for state in artifact["stack_states"]:
        route = state["routing"].detach().float()
        routes.append(torch.softmax(route, dim=0).numpy())
    prior = np.mean(routes, axis=0).astype(np.float32)
    prior /= prior.sum()
    return prior


def build_feature_mask(names):
    shared = {
        "expert_disagreement", "expert_range", "physical_tls_sde",
        "physical_tls_period_match", "physical_tls_sampling_gate",
        "physical_ap_background_depth_snr", "physical_ap_depth_cv",
        "physical_diff_offset_sigma", "physical_diff_peak_snr",
        *(kind + "_available" for kind in KINDS),
    }
    feature_mask = np.zeros((len(EXPERTS), len(names)), dtype=np.float32)
    for expert_index, expert in enumerate(EXPERTS):
        own = {"physical_" + name for name in FEATURES.get(expert, ())}
        for feature_index, name in enumerate(names):
            if (name in shared or name.startswith("generic_") or name.startswith(expert + "_")
                    or name in own):
                feature_mask[expert_index, feature_index] = 1.
    if not np.all(feature_mask.sum(axis=1) > 0):
        raise ValueError("Every expert needs at least one routing diagnostic")
    return feature_mask


def assemble_roles(models, data, physical_features, physical_predictions, behavior_config):
    roles = ("selection", "calibration", "audit")
    collected, physical, assembled = {}, {}, {}
    columns = None
    for role in roles:
        part = data["tess"][role]
        collected[role] = v3.collect(models, part, behavior_config)
        physical[role] = v4.align_physical(part, physical_features, physical_predictions)
        physical_logits, physical_available, raw, role_columns = physical[role]
        if columns is None:
            columns = role_columns
        elif columns != role_columns:
            raise ValueError("Physical feature order changed between roles")
        base = np.concatenate([collected[role]["base"], physical_logits], axis=1).astype(np.float32)
        availability = np.concatenate(
            [np.ones_like(collected[role]["base"], dtype=bool), physical_available], axis=1)
        metadata = part["metadata"]
        period = np.asarray([float(row["period"]) for row in metadata], dtype=np.float32)
        duration = np.asarray([float(row["duration_hours"]) for row in metadata], dtype=np.float32)
        generic = np.column_stack([
            part["x_scalar"].numpy(),
            np.log(np.maximum(period, 1e-8)),
            np.log(np.maximum(duration, 1e-8)),
            np.log(np.maximum(duration / (24 * period), 1e-8)),
        ]).astype(np.float32)
        context = np.concatenate([
            collected[role]["behavior"], raw, physical_available.astype(np.float32), generic,
        ], axis=1).astype(np.float32)
        assembled[role] = {"base": base, "availability": availability, "context_raw": context}
    names = list(collected["selection"]["names"])
    names += ["physical_" + name for name in columns]
    names += [kind + "_available" for kind in KINDS]
    names += ["generic_" + name for name in SCALAR_NAMES]
    names += ["generic_log_period", "generic_log_duration", "generic_log_duty_cycle"]
    if any(value["context_raw"].shape[1] != len(names) for value in assembled.values()):
        raise ValueError("Router feature-name contract differs from the assembled matrix")
    moments = core.fit_transform(assembled["selection"]["context_raw"])
    for role in roles:
        assembled[role]["context"] = core.transform(assembled[role]["context_raw"], moments)
    return assembled, names, moments


def _nll(labels, logits):
    return float(np.mean(np.logaddexp(0, logits) - labels * logits))


def select_configuration(assembled, labels, prior, feature_mask, config):
    rows, candidates = [], []
    for shrinkage in config["shrinkage_grid"]:
        kl_values = [0.] if shrinkage == 0 else config["prior_kl_grid"]
        for prior_kl in kl_values:
            if shrinkage == 0:
                models = [DiagnosticRouter(prior, feature_mask, 0.)]
            else:
                models = [train_router(
                    assembled["selection"]["context"], assembled["selection"]["base"],
                    assembled["selection"]["availability"], labels["selection"], prior,
                    feature_mask, config, shrinkage, prior_kl, seed)
                    for seed in config["router_seeds"]]
            cal_logits, _ = apply_routers(
                models, assembled["calibration"]["context"], assembled["calibration"]["base"],
                assembled["calibration"]["availability"])
            temperature = fit_temperature(labels["calibration"], cal_logits)
            row = {"shrinkage": float(shrinkage), "prior_kl": float(prior_kl),
                   "calibration_nll_raw": _nll(labels["calibration"], cal_logits),
                   "calibration_nll": float(temperature["nll_after"]),
                   "temperature": float(temperature["temperature"])}
            rows.append(row)
            candidates.append((row, models))
    # Complexity is the explicit tie-breaker; audit data is not touched here.
    chosen_row, chosen_models = min(
        candidates, key=lambda item: (round(item[0]["calibration_nll"], 10),
                                      item[0]["shrinkage"], -item[0]["prior_kl"]))
    return chosen_row, chosen_models, rows


def routing_summary(weights, base, labels, availability, names, models):
    losses = np.logaddexp(0, base) - labels[:, None] * base
    losses = np.where(availability, losses, np.inf)
    selected = weights.argmax(axis=1)
    oracle = losses.argmin(axis=1)
    top_coefficients = {}
    coefficient = np.mean([np.abs(model.coefficient.detach().numpy()) for model in models], axis=0)
    mask = models[0].feature_mask.numpy().astype(bool)
    for index, expert in enumerate(EXPERTS):
        order = np.argsort(-coefficient[index] * mask[index])[:8]
        top_coefficients[expert] = [
            {"feature": names[j], "mean_abs_coefficient": float(coefficient[index, j])}
            for j in order if mask[index, j] and coefficient[index, j] > 0
        ]
    return {
        "mean_weight": dict(zip(EXPERTS, weights.mean(axis=0).astype(float).tolist())),
        "weight_std": dict(zip(EXPERTS, weights.std(axis=0).astype(float).tolist())),
        "top_routed_count": {expert: int(np.sum(selected == i)) for i, expert in enumerate(EXPERTS)},
        "top_route_matches_lowest_loss_expert": float(np.mean(selected == oracle)),
        "top_coefficients_by_expert": top_coefficients,
    }


def run(config, behavior_config, models, data, physical_features, physical_predictions, prior):
    assembled, feature_names, moments = assemble_roles(
        models, data, physical_features, physical_predictions, behavior_config)
    labels = {role: data["tess"][role]["y"].numpy() for role in assembled}
    feature_mask = build_feature_mask(feature_names)
    selected, routers, search = select_configuration(assembled, labels, prior, feature_mask, config)
    # The audit is evaluated only after the configuration and temperature are frozen.
    audit_logits, audit_weights = apply_routers(
        routers, assembled["audit"]["context"], assembled["audit"]["base"],
        assembled["audit"]["availability"])
    static = DiagnosticRouter(prior, feature_mask, 0.)
    static_cal, _ = apply_routers([static], assembled["calibration"]["context"],
                                  assembled["calibration"]["base"],
                                  assembled["calibration"]["availability"])
    static_audit, _ = apply_routers([static], assembled["audit"]["context"],
                                    assembled["audit"]["base"],
                                    assembled["audit"]["availability"])
    static_temperature = fit_temperature(labels["calibration"], static_cal)
    audit = {
        "v4_static_stack": metrics(labels["audit"], static_audit),
        "v4_static_stack_calibrated": metrics(
            labels["audit"], static_audit, static_temperature["temperature"]),
        "diagnostic_router": metrics(labels["audit"], audit_logits),
        "diagnostic_router_calibrated": metrics(
            labels["audit"], audit_logits, selected["temperature"]),
    }
    for index, expert in enumerate(EXPERTS):
        use_cal = assembled["calibration"]["availability"][:, index]
        use_audit = assembled["audit"]["availability"][:, index]
        expert_temperature = fit_temperature(
            labels["calibration"][use_cal], assembled["calibration"]["base"][use_cal, index])
        audit[expert] = {**metrics(labels["audit"][use_audit],
                                  assembled["audit"]["base"][use_audit, index]),
                         "available": int(use_audit.sum())}
        audit[expert + "_calibrated"] = metrics(
            labels["audit"][use_audit], assembled["audit"]["base"][use_audit, index],
            expert_temperature["temperature"])
    best_single = max(EXPERTS, key=lambda expert: audit[expert]["average_precision"])
    router_metrics = audit["diagnostic_router"]
    router_calibrated = audit["diagnostic_router_calibrated"]
    static_metrics = audit["v4_static_stack"]
    static_calibrated = audit["v4_static_stack_calibrated"]
    beats_both = (router_metrics["average_precision"] > max(
                      static_metrics["average_precision"], audit[best_single]["average_precision"])
                  and router_calibrated["brier"] < min(
                      static_calibrated["brier"], audit[best_single + "_calibrated"]["brier"]))
    summary = {
        "status": "complete", "schema_version": 1, "version": VERSION,
        "generated_at": utc_now(), "experts": list(EXPERTS),
        "partitions": {role: len(labels[role]) for role in assembled},
        "selection_protocol": "train_on_selection_choose_once_by_calibration_nll_then_evaluate_audit",
        "selected_configuration": selected, "calibration_search": search,
        "static_calibration": static_temperature, "audit": audit,
        "best_single_on_reused_audit": best_single,
        "routing": routing_summary(audit_weights, assembled["audit"]["base"], labels["audit"],
                                   assembled["audit"]["availability"], feature_names, routers),
        "claims": {
            "router_beats_static_and_best_single_on_declared_metrics": bool(beats_both),
            "dynamic_router_selected_by_calibration": bool(selected["shrinkage"] > 0),
            "original_test_evaluated": False, "prospective_confirmation": False,
            "planet_probability": False,
        },
        "limitations": [
            "The audit is validation-derived and was consulted by earlier experiments",
            "The small calibration split can select a noisy routing configuration",
            "Physical experts use known catalog ephemerides for these labelled examples",
            "A frozen prospective host-disjoint cohort is required for a paper-level claim",
        ],
    }
    artifact = {
        "version": VERSION, "experts": list(EXPERTS), "config": config,
        "behavior_config": behavior_config, "feature_names": feature_names,
        "feature_mean": torch.from_numpy(moments[0]), "feature_scale": torch.from_numpy(moments[1]),
        "feature_mask": torch.from_numpy(feature_mask), "prior": torch.from_numpy(prior),
        "router_states": [model.state_dict() for model in routers],
        "selected_configuration": selected,
    }
    return summary, artifact


def write_report(path, summary):
    audit = summary["audit"]
    best = summary["best_single_on_reused_audit"]
    display = (best, "v4_static_stack", "v4_static_stack_calibrated",
               "diagnostic_router", "diagnostic_router_calibrated")
    lines = [
        "# Diagnostic-conditioned supermodel v5", "",
        "A low-capacity gate adjusts v4's global expert prior per candidate using expert behavior, "
        "cross-expert disagreement, TLS, aperture, difference-image and ephemeris diagnostics.", "",
        "| Method | AP | ROC AUC | Brier | Accuracy |", "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in display:
        row = audit[name]
        accuracy = (row["at_0_5"]["tp"] + row["at_0_5"]["tn"]) / row["n"]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | "
                     f"{row['roc_auc']:.4f} | {row['brier']:.4f} | {accuracy:.4f} |")
    chosen = summary["selected_configuration"]
    lines += [
        "", "## Frozen selection", "",
        f"Calibration selected shrinkage **{chosen['shrinkage']}**, prior KL **{chosen['prior_kl']}**, "
        f"and temperature **{chosen['temperature']:.4f}**.",
        f"A dynamic gate was selected: **{summary['claims']['dynamic_router_selected_by_calibration']}**.",
        f"It beat the static stack and strongest single expert on both declared metrics: "
        f"**{summary['claims']['router_beats_static_and_best_single_on_declared_metrics']}**.",
        "", "## Boundaries", "",
        *["- " + item for item in summary["limitations"]],
    ]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/diagnostic_router_v5.json")
    parser.add_argument("--behavior-config", default="configs/behavioral_supermodel_v2.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--cnn-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--diagnostic-run", default="outputs/research/diagnostic_experts/pilot-v2")
    parser.add_argument("--physical-run", default="outputs/research/physical_experts/pilot-v1")
    parser.add_argument("--v4-run", default="results/behavioral_supermodel_v4")
    parser.add_argument("--output", default="results/behavioral_supermodel_v5")
    args = parser.parse_args(argv)
    config = validate_config(json.loads((ROOT / args.config).read_text()))
    behavior_config = core.validate_config(json.loads((ROOT / args.behavior_config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    paths = {name: ROOT / value for name, value in (
        ("cnn", args.cnn_run), ("transformer", args.transformer_run),
        ("diagnostic", args.diagnostic_run), ("physical", args.physical_run), ("v4", args.v4_run))}
    receipts = {name: json.loads((path / "complete.json").read_text()) for name, path in paths.items()}
    scorer = ComparisonScorer(paths["cnn"].parent, paths["cnn"].name, receipts["cnn"]["spec_sha256"])
    models = scorer.models + load_transformers(paths["transformer"], receipts["transformer"]["spec_sha256"])
    models += load_diagnostics(paths["diagnostic"], receipts["diagnostic"]["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation)
    physical_features, physical_predictions = v4._physical_tables(paths["physical"], receipts["physical"])
    v4_path = paths["v4"] / "behavioral_supermodel.pt"
    if receipts["v4"]["files"].get("behavioral_supermodel.pt") != file_sha256(v4_path):
        raise ValueError("v4 routing-prior checksum mismatch")
    prior_artifact = torch.load(v4_path, map_location="cpu", weights_only=True)
    prior = v4_prior(prior_artifact)
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("v5 output already exists")
    output.mkdir(parents=True, exist_ok=True)
    sources = (
        "scripts/experiments/behavioral_supermodel_v5.py",
        "scripts/experiments/behavioral_supermodel_v4.py",
        "scripts/experiments/behavioral_supermodel_v3.py",
        "scripts/experiments/behavioral_supermodel_v2.py",
    )
    spec = {
        "version": VERSION, "config": config, "behavior_config": behavior_config,
        "source_specs": {name: receipt["spec_sha256"] for name, receipt in receipts.items()},
        "prepared_data": provenance,
        "source_files": {name: file_sha256(ROOT / name) for name in sources},
    }
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact = run(config, behavior_config, models, data, physical_features,
                            physical_predictions, prior)
    summary["spec_sha256"] = artifact["spec_sha256"] = spec_sha
    torch.save(artifact, output / "behavioral_supermodel.pt")
    atomic_json(output / "spec.json", spec)
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "behavioral_supermodel.pt")}
    atomic_json(output / "complete.json", {
        "status": "complete", "completed_at": utc_now(), "spec_sha256": spec_sha, "files": files})
    print(json.dumps({
        "status": "complete", "selected": summary["selected_configuration"],
        "best_single": summary["best_single_on_reused_audit"],
        "claim": summary["claims"]["router_beats_static_and_best_single_on_declared_metrics"],
        "key_audit": {name: summary["audit"][name] for name in
                      ("v4_static_stack", "diagnostic_router", "diagnostic_router_calibrated")},
    }, indent=2))


if __name__ == "__main__":
    main()
