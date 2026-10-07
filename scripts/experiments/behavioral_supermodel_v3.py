"""Eight-expert behavioral fusion with Transformer and diagnostic specialists."""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import torch

import scripts.experiments.behavioral_supermodel_v2 as core
from scripts.experiments.adaptation_data import load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.diagnostic_experts import load_models as load_diagnostics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.experiments.transformer_expert import load_models as load_transformers
from scripts.research.model_comparison import ARMS, ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "behavioral_expert_supermodel_v3"
EXPERTS = (*ARMS, "transformer", "transit_morphology", "stellar_variability")


def collect(models, part, config, batch_size=128):
    """Collect behavior while allowing different seed counts per expert."""
    means, base_sd = {}, None
    with torch.inference_mode():
        for probe_name in core.PROBES:
            inputs = core.probe(part, probe_name, config)
            by_expert = {expert: [] for expert in EXPERTS}
            for record, model in models:
                chunks = [model(*[inputs[key][start:start + batch_size] for key in core.INPUTS])
                          for start in range(0, len(part["y"]), batch_size)]
                value = torch.cat(chunks).numpy()
                if value.shape != (len(part["y"]),) or record["arm"] not in by_expert:
                    raise ValueError("Malformed dynamic expert output")
                by_expert[record["arm"]].append(value)
            if any(not values for values in by_expert.values()):
                raise ValueError("Every declared expert needs a model")
            stacked = {expert: np.stack(values, axis=1) for expert, values in by_expert.items()}
            means[probe_name] = np.stack([stacked[expert].mean(axis=1) for expert in EXPERTS], axis=1)
            if probe_name == "base":
                base_sd = np.stack([stacked[expert].std(axis=1) for expert in EXPERTS], axis=1)
    base = means["base"]
    blocks = []
    for i in range(len(EXPERTS)):
        blocks.append(np.stack([base_sd[:, i], means["global_occlusion"][:, i] - base[:, i],
            means["local_occlusion"][:, i] - base[:, i], means["scalar_occlusion"][:, i] - base[:, i],
            np.abs(means["small_jitter"][:, i] - base[:, i]),
            np.abs(means["cadence_dropout"][:, i] - base[:, i]),
            means["depth_attenuation"][:, i] - base[:, i]], axis=1))
    behavior = np.concatenate(blocks + [base.std(axis=1, keepdims=True),
                                         (base.max(axis=1) - base.min(axis=1))[:, None]], axis=1)
    names = [f"{expert}_{behavior_name}" for expert in EXPERTS for behavior_name in core.BEHAVIORS]
    names += ["expert_disagreement", "expert_range"]
    return {"base": base.astype(np.float32), "behavior": behavior.astype(np.float32), "names": names}


def run(config, models, data):
    roles = ("selection", "calibration", "audit")
    collected = {role: collect(models, data["tess"][role], config) for role in roles}
    moments = core.fit_transform(collected["selection"]["behavior"])
    behavior = {role: core.transform(collected[role]["behavior"], moments) for role in roles}
    y_selection = data["tess"]["selection"]["y"].numpy()
    stacks = [core.train_stack(collected["selection"]["base"], y_selection, config, seed)
              for seed in config["meta_seeds"]]
    baseline = {role: core.mean_stack(stacks, collected[role]["base"]) for role in roles}
    residuals = [core.train_residual(behavior["selection"], baseline["selection"], y_selection, config, seed)
                 for seed in config["meta_seeds"]]
    correction = {role: core.mean_residual(residuals, behavior[role]) for role in roles}
    y_calibration = data["tess"]["calibration"]["y"].numpy()
    alpha = core.calibration_alpha(y_calibration, baseline["calibration"], correction["calibration"], config["alpha_grid"])
    final = {role: baseline[role] + alpha["selected"] * correction[role] for role in roles}
    temperatures = {"convex_stack": fit_temperature(y_calibration, baseline["calibration"]),
                    "behavioral_supermodel": fit_temperature(y_calibration, final["calibration"])}
    audit_y = data["tess"]["audit"]["y"].numpy()
    audit = {expert: metrics(audit_y, collected["audit"]["base"][:, i]) for i, expert in enumerate(EXPERTS)}
    audit.update({"uniform_mean": metrics(audit_y, collected["audit"]["base"].mean(axis=1)),
                  "convex_stack": metrics(audit_y, baseline["audit"]),
                  "convex_stack_calibrated": metrics(audit_y, baseline["audit"], temperatures["convex_stack"]["temperature"]),
                  "behavioral_supermodel": metrics(audit_y, final["audit"]),
                  "behavioral_supermodel_calibrated": metrics(audit_y, final["audit"], temperatures["behavioral_supermodel"]["temperature"])})
    stack_weights = np.mean([torch.softmax(model.routing.detach(), dim=0).numpy() for model in stacks], axis=0)
    importance = np.mean([np.abs(model.linear.weight.detach().numpy()[0]) for model in residuals], axis=0)
    top = sorted(zip(collected["selection"]["names"], importance.tolist()), key=lambda x: -x[1])[:15]
    best_single = max(EXPERTS, key=lambda expert: audit[expert]["average_precision"])
    improved = (audit["behavioral_supermodel"]["average_precision"] > audit[best_single]["average_precision"]
                and audit["behavioral_supermodel_calibrated"]["brier"] < audit[best_single]["brier"])
    summary = {"status": "complete", "schema_version": 1, "version": VERSION, "generated_at": utc_now(),
               "experts": list(EXPERTS), "probes": list(core.PROBES), "behavior_features": collected["selection"]["names"],
               "partitions": {role: len(data["tess"][role]["y"]) for role in roles},
               "best_single_on_reused_audit": best_single, "calibration_alpha": alpha, "calibration": temperatures,
               "audit": audit, "mean_stack_weights": dict(zip(EXPERTS, stack_weights.tolist())),
               "top_behavior_coefficients": [{"feature": name, "mean_abs_coefficient": value} for name, value in top],
               "claims": {"behavior_improvement_over_best_single": bool(improved), "original_test_evaluated": False,
                          "search_ready": False, "planet_probability": False, "novelty_established": False},
               "limitations": ["The audit was previously consulted and best-single identification is descriptive only",
                   "Diagnostic experts use known-ephemeris prepared views and do not validate blind recovery",
                   "No target-pixel files are cached, so difference-image and source-localization experts remain unavailable",
                   "Prospective host-disjoint confirmation is required before promotion"]}
    artifact = {"version": VERSION, "experts": list(EXPERTS), "config": config,
                "behavior_features": collected["selection"]["names"], "behavior_mean": torch.from_numpy(moments[0]),
                "behavior_scale": torch.from_numpy(moments[1]), "stack_states": [m.state_dict() for m in stacks],
                "residual_states": [m.state_dict() for m in residuals], "selected_alpha": alpha["selected"],
                "calibration_temperature": temperatures["behavioral_supermodel"]["temperature"]}
    return summary, artifact


def write_report(path, summary):
    display = (*EXPERTS, "uniform_mean", "convex_stack", "convex_stack_calibrated",
               "behavioral_supermodel", "behavioral_supermodel_calibrated")
    lines = ["# Behavioral supermodel v3", "", "Eight experts include CNN/DANN regimes, a Transformer, transit morphology and stellar variability.", "",
             "| Method | AP | ROC AUC | Brier |", "| --- | ---: | ---: | ---: |"]
    for name in display:
        row = summary["audit"][name]
        lines.append(f"| {name.replace('_',' ')} | {row['average_precision']:.4f} | {row['roc_auc']:.4f} | {row['brier']:.4f} |")
    lines += ["", f"Calibration-selected behavioral strength: **{summary['calibration_alpha']['selected']}**.",
              f"Behavior beat the strongest individual expert on both declared metrics: **{summary['claims']['behavior_improvement_over_best_single']}**.",
              "", "## Boundaries", ""] + ["- " + item for item in summary["limitations"]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/behavioral_supermodel_v2.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--cnn-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--diagnostic-run", default="outputs/research/diagnostic_experts/pilot-v2")
    parser.add_argument("--output", default="results/behavioral_supermodel_v3")
    args = parser.parse_args(argv)
    config = core.validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    paths = {name: ROOT / value for name, value in (("cnn", args.cnn_run), ("transformer", args.transformer_run),
                                                     ("diagnostic", args.diagnostic_run))}
    receipts = {name: json.loads((path / "complete.json").read_text()) for name, path in paths.items()}
    scorer = ComparisonScorer(paths["cnn"].parent, paths["cnn"].name, receipts["cnn"]["spec_sha256"])
    models = scorer.models + load_transformers(paths["transformer"], receipts["transformer"]["spec_sha256"])
    models += load_diagnostics(paths["diagnostic"], receipts["diagnostic"]["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation)
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()): raise ValueError("v3 output already exists")
    output.mkdir(parents=True, exist_ok=True)
    spec = {"version": VERSION, "config": config, "source_specs": {k: v["spec_sha256"] for k, v in receipts.items()},
            "prepared_data": provenance, "source_files": {name: file_sha256(ROOT / name) for name in
                ("scripts/experiments/behavioral_supermodel_v3.py", "scripts/experiments/behavioral_supermodel_v2.py",
                 "scripts/experiments/diagnostic_experts.py", "scripts/experiments/transformer_expert.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact = run(config, models, data); summary["spec_sha256"] = artifact["spec_sha256"] = spec_sha
    torch.save(artifact, output / "behavioral_supermodel.pt")
    atomic_json(output / "spec.json", spec); atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "report.md", "behavioral_supermodel.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(), "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output), "best_single": summary["best_single_on_reused_audit"],
                      "alpha": summary["calibration_alpha"], "key_audit": {name: summary["audit"][name] for name in
                      ("stellar_variability", "convex_stack", "behavioral_supermodel")}}, indent=2))


if __name__ == "__main__": main()
