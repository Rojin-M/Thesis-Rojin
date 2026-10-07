"""Behavioral meta-learning over frozen exoplanet experts.

Each expert is observed on the original candidate and on fixed, label-free
diagnostic probes.  A small meta-model learns from scores, seed variability,
cross-expert disagreement, and response deltas.  Labels never enter a probe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math

import numpy as np
import torch
from torch import nn

from scripts.experiments.adaptation_data import INPUTS, load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.research.model_comparison import ARMS, ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "behavioral_expert_supermodel_v1"
PROBES = ("base", "global_occlusion", "local_occlusion", "scalar_occlusion", "small_jitter")
BEHAVIORS = ("base_logit", "seed_sd", "global_delta", "local_delta", "scalar_delta", "jitter_abs_delta")
DEFAULTS = {
    "schema_version": 1,
    "meta_seeds": [211, 223, 227],
    "steps": 600,
    "learning_rate": 0.01,
    "weight_decay": 0.01,
    "hidden_units": 12,
    "jitter_std": 0.02,
    "jitter_seed": 7301,
    "max_grad_norm": 5.0,
}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown behavioral-supermodel configuration field")
    c = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("steps", 20, 10000),
                           ("hidden_units", 2, 128), ("jitter_seed", 0, 2**31 - 1)):
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError("Invalid " + key)
    if (not isinstance(c["meta_seeds"], list) or not 1 <= len(c["meta_seeds"]) <= 10
            or len(c["meta_seeds"]) != len(set(c["meta_seeds"]))
            or any(type(x) is not int or not 0 <= x < 2**31 for x in c["meta_seeds"])):
        raise ValueError("Expected distinct bounded meta seeds")
    for key in ("learning_rate", "weight_decay", "jitter_std", "max_grad_norm"):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]):
            raise ValueError("Invalid " + key)
    if not (0 < c["learning_rate"] <= 1 and 0 <= c["weight_decay"] <= 1
            and 0 < c["jitter_std"] <= .2 and 0 < c["max_grad_norm"] <= 100):
        raise ValueError("Behavioral-supermodel settings exceed supported bounds")
    return c


def diagnostic_probe(part, name, jitter_std=.02, jitter_seed=7301):
    """Create a label-free diagnostic counterfactual for frozen inference."""
    if name not in PROBES:
        raise ValueError("Unknown diagnostic probe")
    result = {key: part[key].clone() for key in INPUTS}
    if name == "base":
        return result
    if name == "global_occlusion":
        result["x_global"][:, :, :2] = 0
        result["x_global"][:, :, 2] = 0
        result["x_flat"][:, :600] = 0
    elif name == "local_occlusion":
        result["x_local"][:, :, :2] = 0
        result["x_local"][:, :, 2] = 0
        result["x_flat"][:, 600:900] = 0
    elif name == "scalar_occlusion":
        result["x_scalar"][:] = 0
        result["x_flat"][:, -7:] = 0
    else:
        generator = torch.Generator().manual_seed(jitter_seed)
        for key, mean_slice in (("x_global", slice(0, 200)), ("x_local", slice(600, 700))):
            mask = result[key][:, :, 2] > .5
            noise = torch.randn(result[key][:, :, 0].shape, generator=generator) * jitter_std
            result[key][:, :, 0] += noise * mask
            result["x_flat"][:, mean_slice] += noise
    return result


def collect_behavior(models, part, config, batch_size=128):
    """Return per-arm behavior features with no access to labels."""
    by_probe = {}
    with torch.inference_mode():
        for probe in PROBES:
            inputs = diagnostic_probe(part, probe, config["jitter_std"], config["jitter_seed"])
            by_arm = {arm: [] for arm in ARMS}
            for record, model in models:
                chunks = []
                for start in range(0, len(part["y"]), batch_size):
                    chunks.append(model(*[inputs[key][start:start + batch_size] for key in INPUTS]))
                values = torch.cat(chunks).cpu().numpy()
                if values.shape != (len(part["y"]),) or not np.isfinite(values).all():
                    raise ValueError("Malformed behavioral probe prediction")
                by_arm[record["arm"]].append(values)
            by_probe[probe] = np.stack([np.stack(by_arm[arm], axis=1) for arm in ARMS], axis=1)
    base = by_probe["base"]
    base_mean, base_sd = base.mean(axis=2), base.std(axis=2)
    probe_mean = {name: values.mean(axis=2) for name, values in by_probe.items()}
    blocks = []
    for index in range(len(ARMS)):
        blocks.append(np.stack([
            base_mean[:, index], base_sd[:, index],
            probe_mean["global_occlusion"][:, index] - base_mean[:, index],
            probe_mean["local_occlusion"][:, index] - base_mean[:, index],
            probe_mean["scalar_occlusion"][:, index] - base_mean[:, index],
            np.abs(probe_mean["small_jitter"][:, index] - base_mean[:, index]),
        ], axis=1))
    expert_features = np.concatenate(blocks, axis=1)
    ensemble = np.stack([base_mean.mean(axis=1), base_mean.std(axis=1),
                         base_mean.max(axis=1) - base_mean.min(axis=1)], axis=1)
    features = np.concatenate([expert_features, ensemble], axis=1).astype(np.float32)
    if not np.isfinite(features).all():
        raise ValueError("Nonfinite behavioral features")
    names = [f"{arm}_{behavior}" for arm in ARMS for behavior in BEHAVIORS]
    names += ["expert_mean", "expert_disagreement", "expert_range"]
    return {"features": features, "feature_names": names, "base_logits": base_mean.astype(np.float32),
            "per_seed_base": base.astype(np.float32)}


def fit_transform(features):
    mean, scale = features.mean(axis=0), features.std(axis=0)
    scale[scale < 1e-6] = 1
    return {"mean": mean, "scale": scale}


def apply_transform(features, transform):
    result = (features - transform["mean"]) / transform["scale"]
    if not np.isfinite(result).all():
        raise ValueError("Invalid transformed behavioral features")
    return result.astype(np.float32)


class BehavioralSupermodel(nn.Module):
    def __init__(self, features, hidden_units):
        super().__init__()
        self.network = nn.Sequential(nn.Linear(features, hidden_units), nn.SiLU(),
                                     nn.Linear(hidden_units, 1))

    def forward(self, value):
        return self.network(value).squeeze(1)


class OrdinaryStack(nn.Module):
    def __init__(self, experts):
        super().__init__()
        self.linear = nn.Linear(experts, 1)

    def forward(self, value):
        return self.linear(value).squeeze(1)


def train_model(features, labels, config, seed, behavioral=True):
    torch.manual_seed(seed)
    x = torch.as_tensor(features, dtype=torch.float32)
    y = torch.as_tensor(labels, dtype=torch.float32)
    model = (BehavioralSupermodel(x.shape[1], config["hidden_units"])
             if behavioral else OrdinaryStack(x.shape[1]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x), y)
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite supermodel loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config["max_grad_norm"], error_if_nonfinite=True)
        optimizer.step()
    model.eval()
    return model


def predict_ensemble(models, features):
    x = torch.as_tensor(features, dtype=torch.float32)
    with torch.inference_mode():
        values = np.stack([model(x).numpy() for model in models], axis=1)
    return values.mean(axis=1), values.std(axis=1)


def run_experiment(config, adaptation_config, scorer, data, return_models=False):
    c = validate_config(config)
    roles = ("selection", "calibration", "audit")
    behavior = {role: collect_behavior(scorer.models, data["tess"][role], c) for role in roles}
    transform = fit_transform(behavior["selection"]["features"])
    x = {role: apply_transform(behavior[role]["features"], transform) for role in roles}
    base_transform = fit_transform(behavior["selection"]["base_logits"])
    base_x = {role: apply_transform(behavior[role]["base_logits"], base_transform) for role in roles}
    y_selection = data["tess"]["selection"]["y"].numpy()
    supermodels = [train_model(x["selection"], y_selection, c, seed, True) for seed in c["meta_seeds"]]
    stacks = [train_model(base_x["selection"], y_selection, c, seed, False) for seed in c["meta_seeds"]]
    outputs = {}
    for role in roles:
        super_logit, super_sd = predict_ensemble(supermodels, x[role])
        stack_logit, stack_sd = predict_ensemble(stacks, base_x[role])
        outputs[role] = {"supermodel": super_logit, "supermodel_seed_sd": super_sd,
                         "ordinary_stack": stack_logit, "ordinary_stack_seed_sd": stack_sd,
                         "uniform": behavior[role]["base_logits"].mean(axis=1)}
    calibration_y = data["tess"]["calibration"]["y"].numpy()
    calibration = {name: fit_temperature(calibration_y, outputs["calibration"][name])
                   for name in ("supermodel", "ordinary_stack")}
    audit_y = data["tess"]["audit"]["y"].numpy()
    selection_ap = [metrics(y_selection, behavior["selection"]["base_logits"][:, i])["average_precision"]
                    for i in range(len(ARMS))]
    best = int(np.argmax(selection_ap))
    audit = {
        "best_single_selection": metrics(audit_y, behavior["audit"]["base_logits"][:, best]),
        "uniform_mean": metrics(audit_y, outputs["audit"]["uniform"]),
        "ordinary_stack": metrics(audit_y, outputs["audit"]["ordinary_stack"]),
        "ordinary_stack_calibrated": metrics(audit_y, outputs["audit"]["ordinary_stack"],
                                              calibration["ordinary_stack"]["temperature"]),
        "behavioral_supermodel": metrics(audit_y, outputs["audit"]["supermodel"]),
        "behavioral_supermodel_calibrated": metrics(audit_y, outputs["audit"]["supermodel"],
                                                    calibration["supermodel"]["temperature"]),
    }
    improved = (audit["behavioral_supermodel"]["average_precision"] > audit["ordinary_stack"]["average_precision"]
                and audit["behavioral_supermodel_calibrated"]["brier"] < audit["ordinary_stack_calibrated"]["brier"])
    summary = {"schema_version": 1, "version": VERSION, "status": "complete", "generated_at": utc_now(),
               "config": c, "experts": list(ARMS), "expert_architectures": ["CNN", "DANN-CNN"],
               "probes": list(PROBES), "behavior_features": behavior["selection"]["feature_names"],
               "partitions": {role: len(data["tess"][role]["y"]) for role in roles},
               "best_single_selected_on_selection": ARMS[best], "calibration": calibration, "audit": audit,
               "mean_audit_meta_seed_sd": {"behavioral_supermodel": float(outputs["audit"]["supermodel_seed_sd"].mean()),
                                            "ordinary_stack": float(outputs["audit"]["ordinary_stack_seed_sd"].mean())},
               "claims": {"behavior_improvement_over_ordinary_stacking": bool(improved),
                          "novelty_established": False, "original_test_evaluated": False,
                          "planet_probability": False, "search_ready": False},
               "limitations": ["Current sealed experts are CNN and DANN-CNN variants; no Transformer expert is yet available",
                   "The 82-row validation-derived audit was used by earlier experiments and is not a pristine final test",
                   "Diagnostic occlusions are counterfactual sensitivity probes, not physical light-curve augmentations",
                   "Known catalog ephemerides are present; this is candidate classification rather than blind detection",
                   "A larger prospective host-disjoint evaluation is required before scientific promotion"]}
    if return_models:
        artifact = {"version": VERSION, "experts": list(ARMS), "probes": list(PROBES), "config": c,
                    "feature_names": behavior["selection"]["feature_names"],
                    "feature_mean": torch.from_numpy(transform["mean"]),
                    "feature_scale": torch.from_numpy(transform["scale"]),
                    "model_states": [model.state_dict() for model in supermodels],
                    "calibration_temperature": float(calibration["supermodel"]["temperature"])}
        return summary, artifact
    return summary


def write_report(path, summary):
    lines = ["# Behavioral expert supermodel pilot", "",
             "A meta-model observes frozen experts on the original candidate and four label-free diagnostic probes.",
             "It is trained on selection, calibrated separately, and reported on the validation-derived audit.", "",
             "| Method | AP | ROC AUC | Brier | NLL |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, row in summary["audit"].items():
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | {row['roc_auc']:.4f} | {row['brier']:.4f} | {row['nll']:.4f} |")
    lines += ["", f"Behavior features beat ordinary stacking under both predeclared criteria: **{summary['claims']['behavior_improvement_over_ordinary_stacking']}**.",
              "", "## Boundaries", ""] + ["- " + item for item in summary["limitations"]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/behavioral_supermodel_pilot_v1.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--source-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--output", default="results/behavioral_supermodel_pilot_v1")
    args = parser.parse_args(argv)
    config = validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation_config = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    source = ROOT / args.source_run
    receipt = json.loads((source / "complete.json").read_text())
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Behavioral-supermodel output already exists; choose a new versioned directory")
    output.mkdir(parents=True, exist_ok=True)
    scorer = ComparisonScorer(source.parent, source.name, receipt["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation_config)
    spec = {"version": VERSION, "config": config, "source_run": str(source.relative_to(ROOT)),
            "source_spec_sha256": receipt["spec_sha256"], "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in (
                "scripts/experiments/behavioral_supermodel.py", "scripts/experiments/adaptation_data.py",
                "scripts/experiments/adaptation_metrics.py", "scripts/research/model_comparison.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact = run_experiment(config, adaptation_config, scorer, data, True)
    summary["spec_sha256"], artifact["spec_sha256"] = spec_sha, spec_sha
    torch.save(artifact, output / "behavioral_supermodel.pt")
    atomic_json(output / "spec.json", spec)
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "behavioral_supermodel.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output), "audit": summary["audit"],
                      "behavior_improvement": summary["claims"]["behavior_improvement_over_ordinary_stacking"]}, indent=2))


if __name__ == "__main__":
    main()
