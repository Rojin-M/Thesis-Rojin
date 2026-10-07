"""Behavioral supermodel with TLS, aperture and difference-image experts."""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd
import torch

import scripts.experiments.behavioral_supermodel_v2 as core
import scripts.experiments.behavioral_supermodel_v3 as v3
from scripts.experiments.adaptation_data import load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.diagnostic_experts import load_models as load_diagnostics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.experiments.physical_experts import FEATURES, KINDS
from scripts.experiments.transformer_expert import load_models as load_transformers
from scripts.research.model_comparison import ARMS, ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "behavioral_expert_supermodel_v4"
EXPERTS = (*v3.EXPERTS, *KINDS)


def _physical_tables(folder, receipt):
    for name in ("features.csv", "predictions.csv"):
        if receipt["files"].get(name) != file_sha256(folder / name):
            raise ValueError("Physical-expert artifact checksum mismatch: " + name)
    features = pd.read_csv(folder / "features.csv", dtype={"candidate_id": str, "target_id": str})
    predictions = pd.read_csv(folder / "predictions.csv", dtype={"candidate_id": str, "target_id": str})
    if predictions.candidate_id.duplicated().any() or features.candidate_id.duplicated().any():
        raise ValueError("Physical-expert candidate identities are not unique")
    return features.set_index("candidate_id"), predictions.set_index("candidate_id")


def align_physical(part, features, predictions):
    ids = [str(row["candidate_id"]) for row in part["metadata"]]
    if any(candidate not in predictions.index or candidate not in features.index for candidate in ids):
        raise ValueError("Physical-expert output does not cover an experiment candidate")
    p = predictions.loc[ids]
    if not np.array_equal(p.label.to_numpy(dtype=np.float32), part["y"].numpy()):
        raise ValueError("Physical-expert labels differ from prepared-role labels")
    logits = p[[kind + "_logit" for kind in KINDS]].to_numpy(dtype=np.float32)
    available = p[[kind + "_available" for kind in KINDS]].to_numpy(dtype=bool)
    columns = [name for kind in KINDS for name in FEATURES[kind]]
    raw = features.loc[ids, columns].to_numpy(dtype=np.float32)
    if not np.isfinite(logits).all() or not np.isfinite(raw).all():
        raise ValueError("Physical-expert behavior contains nonfinite values")
    return logits, available, raw, columns


def train_stack(base, availability, labels, config, seed):
    torch.manual_seed(seed)
    model = core.ConvexStack(base.shape[1])
    x, mask, y = torch.as_tensor(base), torch.as_tensor(availability), torch.as_tensor(labels)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["stack_weight_decay"])
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        output, _ = model(x, mask)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(output, y)
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), config["max_grad_norm"]); optimizer.step()
    model.eval()
    return model


def mean_stack(models, base, availability):
    x, mask = torch.as_tensor(base), torch.as_tensor(availability)
    with torch.inference_mode():
        return np.stack([model(x, mask)[0].numpy() for model in models]).mean(axis=0)


def available_mean(base, availability):
    return np.sum(base * availability, axis=1) / availability.sum(axis=1)


def run(config, models, data, features, predictions):
    roles = ("selection", "calibration", "audit")
    collected, physical = {}, {}
    for role in roles:
        collected[role] = v3.collect(models, data["tess"][role], config)
        physical[role] = align_physical(data["tess"][role], features, predictions)
    physical_moments = core.fit_transform(physical["selection"][2])
    assembled = {}
    for role in roles:
        logits, availability, raw, columns = physical[role]
        base = np.concatenate([collected[role]["base"], logits], axis=1).astype(np.float32)
        mask = np.concatenate([np.ones_like(collected[role]["base"], dtype=bool), availability], axis=1)
        raw_z = core.transform(raw, physical_moments)
        available_count = availability.sum(axis=1, keepdims=True).astype(np.float32)
        physical_mask = availability.astype(np.float32)
        behavior = np.concatenate([collected[role]["behavior"], raw_z, physical_mask, available_count], axis=1)
        assembled[role] = {"base": base, "availability": mask, "behavior": behavior.astype(np.float32)}
    behavior_moments = core.fit_transform(assembled["selection"]["behavior"])
    behavior = {role: core.transform(assembled[role]["behavior"], behavior_moments) for role in roles}
    y_selection = data["tess"]["selection"]["y"].numpy()
    stacks = [train_stack(assembled["selection"]["base"], assembled["selection"]["availability"],
                          y_selection, config, seed) for seed in config["meta_seeds"]]
    baseline = {role: mean_stack(stacks, assembled[role]["base"], assembled[role]["availability"])
                for role in roles}
    residuals = [core.train_residual(behavior["selection"], baseline["selection"], y_selection, config, seed)
                 for seed in config["meta_seeds"]]
    correction = {role: core.mean_residual(residuals, behavior[role]) for role in roles}
    y_calibration = data["tess"]["calibration"]["y"].numpy()
    alpha = core.calibration_alpha(y_calibration, baseline["calibration"], correction["calibration"],
                                   config["alpha_grid"])
    final = {role: baseline[role] + alpha["selected"] * correction[role] for role in roles}
    temperatures = {"convex_stack": fit_temperature(y_calibration, baseline["calibration"]),
                    "behavioral_supermodel": fit_temperature(y_calibration, final["calibration"])}
    y_audit = data["tess"]["audit"]["y"].numpy()
    audit = {}
    audit_base, audit_available = assembled["audit"]["base"], assembled["audit"]["availability"]
    for index, expert in enumerate(EXPERTS):
        use = audit_available[:, index]
        audit[expert] = {**metrics(y_audit[use], audit_base[use, index]), "available": int(use.sum())}
    audit.update({"available_uniform_mean": metrics(y_audit, available_mean(audit_base, audit_available)),
        "convex_stack": metrics(y_audit, baseline["audit"]),
        "convex_stack_calibrated": metrics(y_audit, baseline["audit"], temperatures["convex_stack"]["temperature"]),
        "behavioral_supermodel": metrics(y_audit, final["audit"]),
        "behavioral_supermodel_calibrated": metrics(y_audit, final["audit"], temperatures["behavioral_supermodel"]["temperature"])})
    stack_weights = np.mean([torch.softmax(model.routing.detach(), dim=0).numpy() for model in stacks], axis=0)
    feature_names = collected["selection"]["names"] + ["physical_" + name for name in columns]
    feature_names += [kind + "_available" for kind in KINDS] + ["physical_available_count"]
    importance = np.mean([np.abs(model.linear.weight.detach().numpy()[0]) for model in residuals], axis=0)
    top = sorted(zip(feature_names, importance.tolist()), key=lambda item: -item[1])[:20]
    best_single = max(EXPERTS, key=lambda name: audit[name]["average_precision"])
    improved = (audit["behavioral_supermodel"]["average_precision"] > audit[best_single]["average_precision"]
                and audit["behavioral_supermodel_calibrated"]["brier"] < audit[best_single]["brier"])
    summary = {"status": "complete", "version": VERSION, "generated_at": utc_now(), "experts": list(EXPERTS),
        "partitions": {role: len(data["tess"][role]["y"]) for role in roles}, "calibration_alpha": alpha,
        "calibration": temperatures, "audit": audit, "best_single_on_reused_audit": best_single,
        "mean_stack_weights": dict(zip(EXPERTS, stack_weights.tolist())),
        "top_behavior_coefficients": [{"feature": name, "mean_abs_coefficient": value} for name, value in top],
        "claims": {"behavior_improvement_over_best_single": bool(improved), "original_test_evaluated": False,
                   "search_ready": False, "planet_probability": False, "prospective_confirmation": False},
        "limitations": ["The audit is validation-derived and was consulted by earlier experiments",
            "Physical experts use known catalog ephemerides for labelled training examples",
            "Pixel-feature availability is explicit and unavailable experts are masked",
            "The frozen prospective cohort remains necessary for an unbiased final comparison"]}
    artifact = {"version": VERSION, "experts": list(EXPERTS), "config": config,
        "behavior_features": feature_names, "behavior_mean": torch.from_numpy(behavior_moments[0]),
        "behavior_scale": torch.from_numpy(behavior_moments[1]), "physical_feature_mean": torch.from_numpy(physical_moments[0]),
        "physical_feature_scale": torch.from_numpy(physical_moments[1]),
        "stack_states": [model.state_dict() for model in stacks], "residual_states": [model.state_dict() for model in residuals],
        "selected_alpha": alpha["selected"], "calibration_temperature": temperatures["behavioral_supermodel"]["temperature"]}
    return summary, artifact


def write_report(path, summary):
    lines = ["# Behavioral supermodel v4", "", "Eleven experts include CNN/DANN regimes, a Transformer, two light-curve diagnostics, TLS, aperture photometry and difference-image localization.", "",
             "| Method | AP | ROC AUC | Brier | Available |", "| --- | ---: | ---: | ---: | ---: |"]
    display = (*EXPERTS, "available_uniform_mean", "convex_stack", "convex_stack_calibrated",
               "behavioral_supermodel", "behavioral_supermodel_calibrated")
    for name in display:
        row = summary["audit"][name]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | {row['roc_auc']:.4f} | {row['brier']:.4f} | {row.get('available', 82)} |")
    lines += ["", f"Calibration-selected behavioral strength: **{summary['calibration_alpha']['selected']}**.",
              f"Behavior beat the strongest single expert on both declared metrics: **{summary['claims']['behavior_improvement_over_best_single']}**.",
              "", "## Boundaries", ""] + ["- " + item for item in summary["limitations"]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/behavioral_supermodel_v2.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--cnn-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--diagnostic-run", default="outputs/research/diagnostic_experts/pilot-v2")
    parser.add_argument("--physical-run", default="outputs/research/physical_experts/pilot-v1")
    parser.add_argument("--output", default="results/behavioral_supermodel_v4")
    args = parser.parse_args(argv)
    config = core.validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    paths = {name: ROOT / value for name, value in (("cnn", args.cnn_run), ("transformer", args.transformer_run),
             ("diagnostic", args.diagnostic_run), ("physical", args.physical_run))}
    receipts = {name: json.loads((path / "complete.json").read_text()) for name, path in paths.items()}
    scorer = ComparisonScorer(paths["cnn"].parent, paths["cnn"].name, receipts["cnn"]["spec_sha256"])
    models = scorer.models + load_transformers(paths["transformer"], receipts["transformer"]["spec_sha256"])
    models += load_diagnostics(paths["diagnostic"], receipts["diagnostic"]["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation)
    features, predictions = _physical_tables(paths["physical"], receipts["physical"])
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()): raise ValueError("v4 output already exists")
    output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/behavioral_supermodel_v4.py", "scripts/experiments/behavioral_supermodel_v3.py",
               "scripts/experiments/behavioral_supermodel_v2.py", "scripts/experiments/physical_experts.py")
    spec = {"version": VERSION, "config": config, "source_specs": {key: value["spec_sha256"] for key, value in receipts.items()},
            "prepared_data": provenance, "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact = run(config, models, data, features, predictions)
    summary["spec_sha256"] = artifact["spec_sha256"] = spec_sha
    torch.save(artifact, output / "behavioral_supermodel.pt")
    atomic_json(output / "spec.json", spec); atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "report.md", "behavioral_supermodel.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(), "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "best_single": summary["best_single_on_reused_audit"],
                      "alpha": summary["calibration_alpha"], "key_audit": {name: summary["audit"][name] for name in
                      ("tls", "aperture_photometry", "difference_image", "convex_stack", "behavioral_supermodel")}}, indent=2))


if __name__ == "__main__":
    main()
