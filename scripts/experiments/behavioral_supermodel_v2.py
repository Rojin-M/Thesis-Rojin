"""Regularized behavioral fusion with a genuinely distinct Transformer expert."""
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
from scripts.experiments.transformer_expert import load_models
from scripts.research.model_comparison import ARMS, ComparisonScorer
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "behavioral_expert_supermodel_v2"
EXPERTS = (*ARMS, "transformer")
PROBES = ("base", "global_occlusion", "local_occlusion", "scalar_occlusion",
          "small_jitter", "cadence_dropout", "depth_attenuation")
BEHAVIORS = ("seed_sd", "global_delta", "local_delta", "scalar_delta",
             "jitter_abs_delta", "dropout_abs_delta", "attenuation_delta")
DEFAULTS = {"schema_version": 1, "meta_seeds": [401, 409, 419], "steps": 600,
            "learning_rate": .01, "stack_weight_decay": .01, "residual_weight_decay": .2,
            "jitter_std": .02, "jitter_seed": 7301, "cadence_dropout_fraction": .1,
            "attenuation_factor": .9, "alpha_grid": [0., .1, .25, .5, 1.], "max_grad_norm": 5.}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown v2 behavioral configuration field")
    c = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("steps", 20, 10000), ("jitter_seed", 0, 2**31-1)):
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError("Invalid " + key)
    if (not isinstance(c["meta_seeds"], list) or not c["meta_seeds"]
            or len(c["meta_seeds"]) != len(set(c["meta_seeds"])) or any(type(x) is not int for x in c["meta_seeds"])):
        raise ValueError("Invalid meta seeds")
    if (not isinstance(c["alpha_grid"], list) or not c["alpha_grid"] or c["alpha_grid"][0] != 0
            or sorted(set(c["alpha_grid"])) != c["alpha_grid"]):
        raise ValueError("Alpha grid must be sorted, unique, and include zero")
    for key in ("learning_rate", "stack_weight_decay", "residual_weight_decay", "jitter_std",
                "cadence_dropout_fraction", "attenuation_factor", "max_grad_norm"):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]):
            raise ValueError("Invalid " + key)
    if not (0 < c["learning_rate"] <= 1 and 0 <= c["stack_weight_decay"] <= 1
            and 0 < c["residual_weight_decay"] <= 10 and 0 < c["jitter_std"] <= .2
            and 0 < c["cadence_dropout_fraction"] <= .5 and .5 <= c["attenuation_factor"] < 1
            and 0 < c["max_grad_norm"] <= 100 and all(0 <= x <= 1 for x in c["alpha_grid"])):
        raise ValueError("Unsafe v2 behavioral configuration")
    return c


def probe(part, name, c):
    if name not in PROBES:
        raise ValueError("Unknown behavior probe")
    result = {key: part[key].clone() for key in INPUTS}
    if name == "base":
        return result
    if name == "global_occlusion":
        result["x_global"][:] = 0; result["x_flat"][:, :600] = 0
    elif name == "local_occlusion":
        result["x_local"][:] = 0; result["x_flat"][:, 600:900] = 0
    elif name == "scalar_occlusion":
        result["x_scalar"][:] = 0; result["x_flat"][:, -7:] = 0
    elif name == "small_jitter":
        generator = torch.Generator().manual_seed(c["jitter_seed"])
        for key, start, bins in (("x_global", 0, 200), ("x_local", 600, 100)):
            noise = torch.randn((len(part["y"]), bins), generator=generator) * c["jitter_std"]
            coverage = result[key][:, :, 2] > .5
            result[key][:, :, 0] += noise * coverage
            result["x_flat"][:, start:start + bins] += noise
    elif name == "cadence_dropout":
        generator = torch.Generator().manual_seed(c["jitter_seed"] + 1)
        for key, flat_start, bins in (("x_global", 0, 200), ("x_local", 600, 100)):
            drop = torch.rand((len(part["y"]), bins), generator=generator) < c["cadence_dropout_fraction"]
            result[key][drop] = 0
            for offset in (0, bins, 2 * bins):
                block = result["x_flat"][:, flat_start + offset:flat_start + offset + bins]
                block[drop] = 0
    else:
        factor = c["attenuation_factor"]
        result["x_global"][:, :, 0] *= factor; result["x_local"][:, :, 0] *= factor
        result["x_flat"][:, :200] *= factor; result["x_flat"][:, 600:700] *= factor
    return result


def collect(models, part, c, batch_size=128):
    predictions = {}
    with torch.inference_mode():
        for name in PROBES:
            inputs, by_expert = probe(part, name, c), {expert: [] for expert in EXPERTS}
            for record, model in models:
                chunks = [model(*[inputs[key][start:start + batch_size] for key in INPUTS])
                          for start in range(0, len(part["y"]), batch_size)]
                value = torch.cat(chunks).numpy()
                if record["arm"] not in by_expert or value.shape != (len(part["y"]),):
                    raise ValueError("Malformed expert behavior output")
                by_expert[record["arm"]].append(value)
            if any(not by_expert[x] for x in EXPERTS):
                raise ValueError("Every declared expert needs at least one model")
            predictions[name] = np.stack([np.stack(by_expert[x], axis=1) for x in EXPERTS], axis=1)
    base = predictions["base"]
    means = {name: value.mean(axis=2) for name, value in predictions.items()}
    base_mean = means["base"]
    blocks = []
    for i in range(len(EXPERTS)):
        blocks.append(np.stack([base[:, i].std(axis=1),
            means["global_occlusion"][:, i] - base_mean[:, i],
            means["local_occlusion"][:, i] - base_mean[:, i],
            means["scalar_occlusion"][:, i] - base_mean[:, i],
            np.abs(means["small_jitter"][:, i] - base_mean[:, i]),
            np.abs(means["cadence_dropout"][:, i] - base_mean[:, i]),
            means["depth_attenuation"][:, i] - base_mean[:, i]], axis=1))
    behavior = np.concatenate(blocks + [base_mean.std(axis=1, keepdims=True),
                                         (base_mean.max(axis=1)-base_mean.min(axis=1))[:, None]], axis=1)
    names = [f"{expert}_{behavior_name}" for expert in EXPERTS for behavior_name in BEHAVIORS]
    names += ["expert_disagreement", "expert_range"]
    return {"base": base_mean.astype(np.float32), "behavior": behavior.astype(np.float32), "names": names}


def fit_transform(value):
    mean, scale = value.mean(axis=0), value.std(axis=0); scale[scale < 1e-6] = 1
    return mean, scale


def transform(value, moments):
    output = (value - moments[0]) / moments[1]
    if not np.isfinite(output).all(): raise ValueError("Nonfinite behavioral transform")
    return output.astype(np.float32)


class ConvexStack(nn.Module):
    def __init__(self, experts):
        super().__init__(); self.routing = nn.Parameter(torch.zeros(experts))

    def forward(self, logits, availability=None):
        route = self.routing.expand_as(logits)
        if availability is not None:
            if availability.shape != logits.shape or not availability.any(dim=1).all():
                raise ValueError("Every candidate requires an available expert")
            route = route.masked_fill(~availability, -torch.inf)
        weights = torch.softmax(route, dim=1)
        return torch.sum(weights * logits, dim=1), weights


class ResidualBehavior(nn.Module):
    def __init__(self, features):
        super().__init__(); self.linear = nn.Linear(features, 1)

    def forward(self, value):
        return torch.tanh(self.linear(value).squeeze(1))


def train_stack(base, labels, c, seed):
    torch.manual_seed(seed); model = ConvexStack(base.shape[1])
    x, y = torch.as_tensor(base), torch.as_tensor(labels)
    optimizer = torch.optim.AdamW(model.parameters(), lr=c["learning_rate"], weight_decay=c["stack_weight_decay"])
    for _ in range(c["steps"]):
        optimizer.zero_grad(set_to_none=True); out, _ = model(x)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(out, y); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), c["max_grad_norm"]); optimizer.step()
    model.eval(); return model


def train_residual(features, baseline, labels, c, seed):
    torch.manual_seed(seed); model = ResidualBehavior(features.shape[1])
    x, base, y = torch.as_tensor(features), torch.as_tensor(baseline), torch.as_tensor(labels)
    optimizer = torch.optim.AdamW(model.parameters(), lr=c["learning_rate"], weight_decay=c["residual_weight_decay"])
    for _ in range(c["steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(base + model(x), y); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), c["max_grad_norm"]); optimizer.step()
    model.eval(); return model


def mean_stack(models, base):
    x = torch.as_tensor(base)
    with torch.inference_mode(): return np.stack([m(x)[0].numpy() for m in models]).mean(axis=0)


def mean_residual(models, behavior):
    x = torch.as_tensor(behavior)
    with torch.inference_mode(): return np.stack([m(x).numpy() for m in models]).mean(axis=0)


def calibration_alpha(y, baseline, residual, grid):
    losses = {str(alpha): float(np.mean(np.logaddexp(0, baseline + alpha * residual)
                                       - y * (baseline + alpha * residual))) for alpha in grid}
    selected = min(grid, key=lambda alpha: (losses[str(alpha)], alpha))
    return {"selected": float(selected), "nll_by_alpha": losses, "scope": "calibration_groups_only"}


def run(c, scorer, transformer_models, data):
    models = scorer.models + transformer_models
    roles = ("selection", "calibration", "audit")
    collected = {role: collect(models, data["tess"][role], c) for role in roles}
    moments = fit_transform(collected["selection"]["behavior"])
    behavior = {role: transform(collected[role]["behavior"], moments) for role in roles}
    y_sel = data["tess"]["selection"]["y"].numpy()
    stacks = [train_stack(collected["selection"]["base"], y_sel, c, seed) for seed in c["meta_seeds"]]
    baseline = {role: mean_stack(stacks, collected[role]["base"]) for role in roles}
    residuals = [train_residual(behavior["selection"], baseline["selection"], y_sel, c, seed)
                 for seed in c["meta_seeds"]]
    correction = {role: mean_residual(residuals, behavior[role]) for role in roles}
    y_cal = data["tess"]["calibration"]["y"].numpy()
    alpha = calibration_alpha(y_cal, baseline["calibration"], correction["calibration"], c["alpha_grid"])
    final = {role: baseline[role] + alpha["selected"] * correction[role] for role in roles}
    temperatures = {"convex_stack": fit_temperature(y_cal, baseline["calibration"]),
                    "behavioral_supermodel": fit_temperature(y_cal, final["calibration"])}
    y_audit = data["tess"]["audit"]["y"].numpy()
    transformer = collected["audit"]["base"][:, EXPERTS.index("transformer")]
    audit = {"transformer_ensemble": metrics(y_audit, transformer),
             "uniform_mean": metrics(y_audit, collected["audit"]["base"].mean(axis=1)),
             "convex_stack": metrics(y_audit, baseline["audit"]),
             "convex_stack_calibrated": metrics(y_audit, baseline["audit"], temperatures["convex_stack"]["temperature"]),
             "behavioral_supermodel": metrics(y_audit, final["audit"]),
             "behavioral_supermodel_calibrated": metrics(y_audit, final["audit"], temperatures["behavioral_supermodel"]["temperature"])}
    weights = np.mean([torch.softmax(model.routing.detach(), dim=0).numpy() for model in stacks], axis=0)
    importance = np.mean([np.abs(model.linear.weight.detach().numpy()[0]) for model in residuals], axis=0)
    top = sorted(zip(collected["selection"]["names"], importance.tolist()), key=lambda x: -x[1])[:12]
    improved = (audit["behavioral_supermodel"]["average_precision"] > audit["convex_stack"]["average_precision"]
                and audit["behavioral_supermodel_calibrated"]["brier"] < audit["convex_stack_calibrated"]["brier"])
    summary = {"status": "complete", "schema_version": 1, "version": VERSION, "generated_at": utc_now(),
               "experts": list(EXPERTS), "expert_architectures": ["CNN", "DANN-CNN", "Transformer"],
               "probes": list(PROBES), "behavior_features": collected["selection"]["names"],
               "partitions": {r: len(data["tess"][r]["y"]) for r in roles}, "calibration_alpha": alpha,
               "calibration": temperatures, "audit": audit,
               "mean_stack_weights": dict(zip(EXPERTS, weights.tolist())),
               "top_behavior_coefficients": [{"feature": n, "mean_abs_coefficient": v} for n, v in top],
               "claims": {"behavior_improvement_over_convex_stack": bool(improved), "original_test_evaluated": False,
                          "search_ready": False, "planet_probability": False, "novelty_established": False},
               "limitations": ["Validation-derived audit was used by earlier experiments and is not a pristine final test",
                   "Transformer training is a bounded 120-update pilot without a convergence claim",
                   "Occlusion and perturbation probes measure sensitivity but are not physical planet simulations",
                   "TLS, centroid, contamination and pixel-level experts are not yet included",
                   "Prospective host-disjoint confirmation remains required"]}
    artifact = {"version": VERSION, "experts": list(EXPERTS), "config": c, "behavior_features": collected["selection"]["names"],
                "behavior_mean": torch.from_numpy(moments[0]), "behavior_scale": torch.from_numpy(moments[1]),
                "stack_states": [m.state_dict() for m in stacks], "residual_states": [m.state_dict() for m in residuals],
                "selected_alpha": alpha["selected"], "calibration_temperature": temperatures["behavioral_supermodel"]["temperature"]}
    return summary, artifact


def report(path, summary):
    lines = ["# Behavioral supermodel v2", "", "Six experts, including a distinct dual-view Transformer, are combined by a convex stack and a calibration-gated behavioral residual.", "",
             "| Method | AP | ROC AUC | Brier | NLL |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, row in summary["audit"].items():
        lines.append(f"| {name.replace('_',' ')} | {row['average_precision']:.4f} | {row['roc_auc']:.4f} | {row['brier']:.4f} | {row['nll']:.4f} |")
    lines += ["", f"Calibration-selected behavioral strength: **{summary['calibration_alpha']['selected']}**.",
              f"Behavior improved both AP and calibrated Brier over the convex stack: **{summary['claims']['behavior_improvement_over_convex_stack']}**.",
              "", "## Boundaries", ""] + ["- " + x for x in summary["limitations"]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/behavioral_supermodel_v2.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--source-run", default="outputs/research/model_experiments/pilot-v1")
    parser.add_argument("--transformer-run", default="outputs/research/transformer_expert/pilot-v1")
    parser.add_argument("--output", default="results/behavioral_supermodel_v2")
    args = parser.parse_args(argv)
    c = validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    source, transformer_path, output = ROOT / args.source_run, ROOT / args.transformer_run, ROOT / args.output
    if output.exists() and any(output.iterdir()): raise ValueError("v2 output already exists")
    output.mkdir(parents=True, exist_ok=True)
    source_receipt = json.loads((source / "complete.json").read_text())
    transformer_receipt = json.loads((transformer_path / "complete.json").read_text())
    scorer = ComparisonScorer(source.parent, source.name, source_receipt["spec_sha256"])
    transformers = load_models(transformer_path, transformer_receipt["spec_sha256"])
    data, provenance = load_prepared(ROOT, adaptation)
    spec = {"version": VERSION, "config": c, "cnn_source_spec": source_receipt["spec_sha256"],
            "transformer_source_spec": transformer_receipt["spec_sha256"], "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in
                ("scripts/experiments/behavioral_supermodel_v2.py", "scripts/experiments/transformer_expert.py",
                 "training/transformer_expert.py", "scripts/experiments/adaptation_data.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    summary, artifact = run(c, scorer, transformers, data)
    summary["spec_sha256"], artifact["spec_sha256"] = spec_sha, spec_sha
    torch.save(artifact, output / "behavioral_supermodel.pt")
    atomic_json(output / "spec.json", spec); atomic_json(output / "summary.json", summary); report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "report.md", "behavioral_supermodel.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(), "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output), "alpha": summary["calibration_alpha"],
                      "audit": summary["audit"], "improved": summary["claims"]["behavior_improvement_over_convex_stack"]}, indent=2))


if __name__ == "__main__": main()
