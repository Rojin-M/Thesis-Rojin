"""Feature-conditioned fusion of frozen mission-adaptation experts.

This is a bounded research experiment, not the production planet scorer.  It
learns a soft router on the existing TESS selection partition, calibrates and
chooses an abstention rule on the disjoint calibration partition, and reports
once on the disjoint validation-derived audit partition.  The original TESS
test split remains integrity-checked but unused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch import nn

from scripts.experiments.adaptation_data import INPUTS, load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.mission_adaptation import atomic_json, validate_config
from scripts.research.model_comparison import ARMS, ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "feature_conditioned_expert_fusion_v1"
SCALAR_NAMES = ("depth", "symmetry", "odd_even", "bls_snr", "bls_depth", "bls_duration", "bls_period")
PHYSICAL_NAMES = ("log_period_days", "log_duration_hours", "log_duty_cycle")
DEFAULTS = {
    "schema_version": 1,
    "gate_seeds": [101, 102, 103],
    "steps": 400,
    "learning_rate": 0.01,
    "weight_decay": 0.001,
    "hidden_units": 16,
    "competence_weight": 0.25,
    "competence_temperature": 0.5,
    "max_grad_norm": 5.0,
    "abstention_target_accuracy": 0.9,
    "abstention_min_coverage": 0.1,
}


def validate_fusion_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown expert-fusion configuration fields")
    c = {**DEFAULTS, **value}
    integer_bounds = {"schema_version": (1, 1), "steps": (20, 10000), "hidden_units": (2, 256)}
    for key, (low, high) in integer_bounds.items():
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError("Invalid " + key)
    if (not isinstance(c["gate_seeds"], list) or not 1 <= len(c["gate_seeds"]) <= 10
            or len(c["gate_seeds"]) != len(set(c["gate_seeds"]))
            or any(type(x) is not int or not 0 <= x < 2**31 for x in c["gate_seeds"])):
        raise ValueError("Expected one to ten distinct gate seeds")
    for key in ("learning_rate", "weight_decay", "competence_weight", "competence_temperature",
                "max_grad_norm", "abstention_target_accuracy", "abstention_min_coverage"):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]):
            raise ValueError("Invalid " + key)
    if not (0 < c["learning_rate"] <= 1 and 0 <= c["weight_decay"] <= 1
            and 0 <= c["competence_weight"] <= 10 and 0 < c["competence_temperature"] <= 10
            and 0 < c["max_grad_norm"] <= 100 and .5 < c["abstention_target_accuracy"] <= 1
            and 0 < c["abstention_min_coverage"] <= 1):
        raise ValueError("Expert-fusion hyperparameters exceed supported bounds")
    return c


def _predict_models(models, part, batch_size=128):
    by_arm = {arm: [] for arm in ARMS}
    with torch.inference_mode():
        for record, model in models:
            chunks = []
            for start in range(0, len(part["y"]), batch_size):
                chunks.append(model(*[part[k][start:start + batch_size] for k in INPUTS]))
            values = torch.cat(chunks).detach().cpu().numpy()
            if values.shape != (len(part["y"]),) or not np.isfinite(values).all():
                raise ValueError("Malformed expert prediction")
            by_arm[record["arm"]].append(values)
    if any(not by_arm[arm] for arm in ARMS):
        raise ValueError("Every expert arm must have at least one sealed model")
    stacked = np.stack([np.stack(by_arm[arm], axis=1) for arm in ARMS], axis=1)
    return {"mean": stacked.mean(axis=2), "sd": stacked.std(axis=2), "per_seed": stacked}


def _raw_context(part, predictions):
    scalar = part["x_scalar"].detach().cpu().numpy().astype(np.float64)
    physical = []
    for row in part["metadata"]:
        period, duration = float(row["period"]), float(row["duration_hours"])
        physical.append([math.log(period), math.log(duration), math.log(duration / (24.0 * period))])
    return np.concatenate([scalar, np.asarray(physical), predictions["sd"]], axis=1)


def fit_context_transform(raw):
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    scale[scale < 1e-6] = 1.0
    return {"mean": mean, "scale": scale}


def transform_context(raw, transform):
    value = (raw - transform["mean"]) / transform["scale"]
    if not np.isfinite(value).all():
        raise ValueError("Nonfinite router context")
    return value.astype(np.float32)


class ContextGate(nn.Module):
    """Soft per-candidate routing over frozen expert logits."""

    def __init__(self, context_features, experts, hidden_units):
        super().__init__()
        self.router = nn.Sequential(nn.Linear(context_features, hidden_units), nn.SiLU(),
                                    nn.Linear(hidden_units, experts))

    def forward(self, context, expert_logits, availability=None):
        routing = self.router(context)
        if availability is not None:
            if availability.shape != expert_logits.shape or not availability.any(dim=1).all():
                raise ValueError("Every row needs at least one available expert")
            routing = routing.masked_fill(~availability, -torch.inf)
        weights = torch.softmax(routing, dim=1)
        return torch.sum(weights * expert_logits, dim=1), weights


class StaticGate(nn.Module):
    def __init__(self, experts):
        super().__init__()
        self.routing_logits = nn.Parameter(torch.zeros(experts))

    def forward(self, expert_logits, availability=None):
        routing = self.routing_logits.expand_as(expert_logits)
        if availability is not None:
            if availability.shape != expert_logits.shape or not availability.any(dim=1).all():
                raise ValueError("Every row needs at least one available expert")
            routing = routing.masked_fill(~availability, -torch.inf)
        weights = torch.softmax(routing, dim=1)
        return torch.sum(weights * expert_logits, dim=1), weights


def _competence_targets(expert_logits, labels, temperature):
    loss = torch.nn.functional.binary_cross_entropy_with_logits(
        expert_logits, labels[:, None].expand_as(expert_logits), reduction="none")
    return torch.softmax(-loss / temperature, dim=1)


def train_gate(context, expert_logits, labels, config, seed, contextual=True):
    torch.manual_seed(seed)
    x = torch.as_tensor(context, dtype=torch.float32)
    experts = torch.as_tensor(expert_logits, dtype=torch.float32)
    y = torch.as_tensor(labels, dtype=torch.float32)
    model = (ContextGate(x.shape[1], experts.shape[1], config["hidden_units"])
             if contextual else StaticGate(experts.shape[1]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    target = _competence_targets(experts, y, config["competence_temperature"])
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        fused, weights = model(x, experts) if contextual else model(experts)
        predictive = torch.nn.functional.binary_cross_entropy_with_logits(fused, y)
        competence = -(target * torch.log(weights.clamp_min(1e-8))).sum(dim=1).mean()
        loss = predictive + config["competence_weight"] * competence
        if not torch.isfinite(loss):
            raise ValueError("Expert fusion produced nonfinite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["max_grad_norm"], error_if_nonfinite=True)
        optimizer.step()
    return model


def _apply_gate(models, context, expert_logits, contextual=True, availability=None):
    x = torch.as_tensor(context, dtype=torch.float32)
    experts = torch.as_tensor(expert_logits, dtype=torch.float32)
    available = (torch.as_tensor(availability, dtype=torch.bool) if availability is not None else None)
    logits, weights = [], []
    with torch.inference_mode():
        for model in models:
            fused, routed = (model(x, experts, available) if contextual else model(experts, available))
            logits.append(fused.numpy()); weights.append(routed.numpy())
    return np.mean(logits, axis=0), np.mean(weights, axis=0)


def predict_with_artifact(artifact, raw_context, expert_logits, availability=None):
    """Apply a sealed router to precomputed experts without retraining."""
    if (artifact.get("version") != VERSION or artifact.get("experts") != list(ARMS)
            or len(artifact.get("contextual_gate_states", [])) != len(artifact.get("config", {}).get("gate_seeds", []))):
        raise ValueError("Invalid expert-fusion artifact")
    raw_context = np.asarray(raw_context, dtype=np.float64)
    expert_logits = np.asarray(expert_logits, dtype=np.float32)
    if (raw_context.ndim != 2 or expert_logits.shape != (len(raw_context), len(ARMS))):
        raise ValueError("Invalid expert-fusion input shape")
    transform = {"mean": np.asarray(artifact["context_mean"], dtype=np.float64),
                 "scale": np.asarray(artifact["context_scale"], dtype=np.float64)}
    context = transform_context(raw_context, transform)
    models = []
    for state in artifact["contextual_gate_states"]:
        model = ContextGate(context.shape[1], len(ARMS), artifact["config"]["hidden_units"])
        model.load_state_dict(state, strict=True); model.eval(); models.append(model)
    logits, weights = _apply_gate(models, context, expert_logits, availability=availability)
    temperature = float(artifact["calibration_temperature"])
    probability = _sigmoid(logits / temperature)
    disagreement = np.std(_sigmoid(expert_logits), axis=1)
    confidence = np.abs(probability - .5) * 2 * np.clip(1 - 2 * disagreement, 0, 1)
    rule = artifact["abstention_rule"]
    abstain = (confidence < rule["threshold"] if rule.get("available")
               else np.ones(len(probability), dtype=bool))
    return {"logit": logits, "calibrated_score": probability, "weights": weights,
            "expert_disagreement": disagreement, "confidence": confidence, "abstain": abstain}


def _sigmoid(value):
    value = np.asarray(value, dtype=np.float64)
    return np.where(value >= 0, 1 / (1 + np.exp(-value)), np.exp(value) / (1 + np.exp(value)))


def _select_abstention(logits, expert_logits, labels, target_accuracy, min_coverage):
    probabilities = _sigmoid(logits)
    disagreement = np.std(_sigmoid(expert_logits), axis=1)
    confidence = np.abs(probabilities - .5) * 2 * np.clip(1 - 2 * disagreement, 0, 1)
    correct = (probabilities >= .5) == np.asarray(labels, dtype=bool)
    minimum = max(1, math.ceil(len(labels) * min_coverage))
    candidates = []
    for threshold in np.unique(confidence):
        keep = confidence >= threshold
        if keep.sum() >= minimum and correct[keep].mean() >= target_accuracy:
            candidates.append((int(keep.sum()), float(threshold), float(correct[keep].mean())))
    if not candidates:
        return {"available": False, "reason": "calibration_partition_cannot_meet_target",
                "target_accuracy": target_accuracy, "minimum_coverage": min_coverage}
    retained, threshold, accuracy = max(candidates)
    return {"available": True, "threshold": threshold, "calibration_retained": retained,
            "calibration_coverage": retained / len(labels), "calibration_accuracy": accuracy,
            "target_accuracy": target_accuracy, "minimum_coverage": min_coverage}


def _evaluate_abstention(rule, logits, expert_logits, labels):
    if not rule["available"]:
        return {"available": False, "reason": rule["reason"]}
    probabilities = _sigmoid(logits)
    disagreement = np.std(_sigmoid(expert_logits), axis=1)
    confidence = np.abs(probabilities - .5) * 2 * np.clip(1 - 2 * disagreement, 0, 1)
    keep = confidence >= rule["threshold"]
    correct = (probabilities >= .5) == np.asarray(labels, dtype=bool)
    return {"available": True, "n": len(labels), "retained": int(keep.sum()),
            "coverage": float(keep.mean()), "accuracy_when_retained": float(correct[keep].mean()) if keep.any() else None,
            "abstained": int((~keep).sum())}


def _regime_masks(part, selection_part):
    period = np.asarray([x["period"] for x in part["metadata"]])
    duration = np.asarray([x["duration_hours"] for x in part["metadata"]])
    selection_bls = selection_part["x_scalar"][:, 3].numpy()
    low, high = np.quantile(selection_bls, [.33, .67])
    bls = part["x_scalar"][:, 3].numpy()
    return {
        "period_under_2d": period < 2,
        "period_2_to_10d": (period >= 2) & (period < 10),
        "period_at_least_10d": period >= 10,
        "duration_under_2h": duration < 2,
        "duration_2_to_5h": (duration >= 2) & (duration < 5),
        "duration_at_least_5h": duration >= 5,
        "bls_snr_low_third": bls <= low,
        "bls_snr_middle_third": (bls > low) & (bls < high),
        "bls_snr_high_third": bls >= high,
    }


def competence_report(part, selection_part, predictions, router_weights):
    labels = part["y"].numpy()
    report = {}
    for name, mask in _regime_masks(part, selection_part).items():
        row = {"n": int(mask.sum()), "positive": int(labels[mask].sum()), "experts": {},
               "mean_router_weight": {arm: float(router_weights[mask, i].mean()) if mask.any() else None
                                      for i, arm in enumerate(ARMS)}}
        for i, arm in enumerate(ARMS):
            if not mask.any():
                values = {"n": 0}
            else:
                values = metrics(labels[mask], predictions["mean"][mask, i])
            row["experts"][arm] = {key: values.get(key) for key in ("n", "average_precision", "roc_auc", "brier")}
        eligible = [(arm, values["brier"]) for arm, values in row["experts"].items()
                    if values["brier"] is not None]
        row["best_expert_by_brier"] = min(eligible, key=lambda x: x[1])[0] if eligible else None
        report[name] = row
    return report


def run_fusion(config, adaptation_config, scorer, data, *, return_models=False):
    c = validate_fusion_config(config)
    parts, predictions = {}, {}
    for role in ("selection", "calibration", "audit"):
        parts[role] = data["tess"][role]
        predictions[role] = _predict_models(scorer.models, parts[role])
    raw = {role: _raw_context(parts[role], predictions[role]) for role in parts}
    transform = fit_context_transform(raw["selection"])
    context = {role: transform_context(raw[role], transform) for role in parts}
    y_selection = parts["selection"]["y"].numpy()
    contextual = [train_gate(context["selection"], predictions["selection"]["mean"], y_selection, c, seed)
                  for seed in c["gate_seeds"]]
    static = [train_gate(context["selection"], predictions["selection"]["mean"], y_selection, c, seed, False)
              for seed in c["gate_seeds"]]
    outputs = {}
    for role in parts:
        contextual_logits, weights = _apply_gate(contextual, context[role], predictions[role]["mean"])
        static_logits, static_weights = _apply_gate(static, context[role], predictions[role]["mean"], False)
        outputs[role] = {"contextual": contextual_logits, "weights": weights,
                         "static": static_logits, "static_weights": static_weights,
                         "uniform": predictions[role]["mean"].mean(axis=1)}
    selection_ap = [metrics(y_selection, predictions["selection"]["mean"][:, i])["average_precision"]
                    for i in range(len(ARMS))]
    best_index = int(np.argmax(selection_ap))
    calibration_y = parts["calibration"]["y"].numpy()
    calibration = fit_temperature(calibration_y, outputs["calibration"]["contextual"])
    abstention = _select_abstention(outputs["calibration"]["contextual"] / calibration["temperature"],
        predictions["calibration"]["mean"], calibration_y, c["abstention_target_accuracy"],
        c["abstention_min_coverage"])
    audit_y = parts["audit"]["y"].numpy()
    audit_methods = {
        "best_single_selection": predictions["audit"]["mean"][:, best_index],
        "uniform_mean": outputs["audit"]["uniform"],
        "learned_static": outputs["audit"]["static"],
        "feature_conditioned_gate": outputs["audit"]["contextual"],
    }
    audit = {name: metrics(audit_y, logits) for name, logits in audit_methods.items()}
    audit["feature_conditioned_gate_calibrated"] = metrics(
        audit_y, outputs["audit"]["contextual"], calibration["temperature"])
    summary = {
        "schema_version": 1, "version": VERSION, "status": "complete", "generated_at": utc_now(),
        "config": c, "source_adaptation_config": adaptation_config,
        "experts": list(ARMS), "expert_count": len(ARMS),
        "models_per_expert": int(predictions["selection"]["per_seed"].shape[2]),
        "best_single_selected_on_selection": ARMS[best_index], "selection_expert_ap": dict(zip(ARMS, selection_ap)),
        "context_features": list(SCALAR_NAMES + PHYSICAL_NAMES + tuple("seed_sd_" + arm for arm in ARMS)),
        "context_transform": {key: value.tolist() for key, value in transform.items()},
        "calibration": calibration, "abstention_rule": abstention,
        "audit_abstention": _evaluate_abstention(abstention,
            outputs["audit"]["contextual"] / calibration["temperature"], predictions["audit"]["mean"], audit_y),
        "audit": audit,
        "audit_competence": competence_report(parts["audit"], parts["selection"], predictions["audit"],
                                                outputs["audit"]["weights"]),
        "mean_audit_router_weight": {arm: float(outputs["audit"]["weights"][:, i].mean())
                                     for i, arm in enumerate(ARMS)},
        "claims": {"improvement_established": False, "novelty_established": False,
                   "search_ready": False, "planet_probability": False, "original_test_evaluated": False},
        "limitations": [
            "Pilot experts differ by training regime but share one CNN architecture and input contract",
            "The 82-row audit is validation-derived and too small for a final paper claim",
            "Known catalog ephemerides are used; this is classification, not blind transit recovery",
            "The abstention rule is empirical and does not provide conformal coverage",
            "Competence by regime is descriptive and requires replication on a prospective sector split",
            "Pixel, centroid, contamination and catalog experts are future modalities, not present in this pilot",
        ],
    }
    if return_models:
        artifact = {
            "version": VERSION, "experts": list(ARMS), "config": c,
            "context_features": summary["context_features"],
            "context_mean": torch.from_numpy(transform["mean"].astype(np.float32)),
            "context_scale": torch.from_numpy(transform["scale"].astype(np.float32)),
            "contextual_gate_states": [model.state_dict() for model in contextual],
            "static_gate_states": [model.state_dict() for model in static],
            "calibration_temperature": float(calibration["temperature"]),
            "abstention_rule": abstention,
        }
        return summary, artifact
    return summary


def write_report(path, summary):
    rows = summary["audit"]
    lines = ["# Feature-conditioned expert-fusion pilot", "",
        "A soft router learned on the TESS selection partition combines five frozen training-regime experts.",
        "Calibration and abstention use a separate partition; the validation-derived audit is reported once.", "",
        "| Method | AP | ROC AUC | Brier | NLL |", "| --- | ---: | ---: | ---: | ---: |"]
    for name in ("best_single_selection", "uniform_mean", "learned_static", "feature_conditioned_gate",
                 "feature_conditioned_gate_calibrated"):
        row = rows[name]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | "
                     f"{row['roc_auc']:.4f} | {row['brier']:.4f} | {row['nll']:.4f} |")
    lines += ["", "## Mean audit routing", ""]
    lines += [f"- {arm}: {weight:.3f}" for arm, weight in summary["mean_audit_router_weight"].items()]
    lines += ["", "## Boundaries", ""] + ["- " + item for item in summary["limitations"]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/expert_fusion_pilot_v1.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--source-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--output", default="results/expert_fusion_pilot_v3")
    args = parser.parse_args(argv)
    config = validate_fusion_config(json.loads((ROOT / args.config).read_text()))
    adaptation_config = validate_config(json.loads((ROOT / args.adaptation_config).read_text()))
    source = ROOT / args.source_run
    receipt = json.loads((source / "complete.json").read_text())
    spec_sha = receipt["spec_sha256"]
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Expert-fusion output already exists; choose a new versioned output")
    output.mkdir(parents=True, exist_ok=True)
    scorer = ComparisonScorer(source.parent, source.name, spec_sha)
    data, provenance = load_prepared(ROOT, adaptation_config)
    spec = {"version": VERSION, "config": config, "source_run": str(source.relative_to(ROOT)),
            "source_spec_sha256": spec_sha, "source_complete_sha256": file_sha256(source / "complete.json"),
            "prepared_data": provenance, "source_files": {
                name: file_sha256(ROOT / name) for name in (
                    "scripts/experiments/expert_fusion.py", "scripts/experiments/adaptation_data.py",
                    "scripts/experiments/adaptation_metrics.py", "scripts/research/model_comparison.py")}}
    spec_sha256 = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, model_artifact = run_fusion(config, adaptation_config, scorer, data, return_models=True)
    summary["spec_sha256"] = spec_sha256
    model_artifact["spec_sha256"] = spec_sha256
    model_path = output / "fusion_model.pt"
    temporary_model = output / "fusion_model.pt.tmp"
    torch.save(model_artifact, temporary_model)
    temporary_model.replace(model_path)
    atomic_json(output / "spec.json", spec)
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "fusion_model.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                             "spec_sha256": spec_sha256, "files": files})
    print(json.dumps({"status": "complete", "output": str(output), "audit": summary["audit"]}, indent=2))


if __name__ == "__main__":
    main()
