"""Interpretable transit-morphology and stellar-variability experts."""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression

from scripts.experiments.adaptation_data import load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "handcrafted_diagnostic_experts_v1"
KINDS = ("transit_morphology", "stellar_variability")
DEFAULTS = {"schema_version": 1, "c_grid": [.01, .1, 1., 10.], "max_iterations": 2000}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown diagnostic-expert configuration field")
    c = {**DEFAULTS, **value}
    if c["schema_version"] != 1 or type(c["max_iterations"]) is not int or not 100 <= c["max_iterations"] <= 10000:
        raise ValueError("Invalid diagnostic-expert configuration")
    if (not isinstance(c["c_grid"], list) or not c["c_grid"] or sorted(set(c["c_grid"])) != c["c_grid"]
            or any(type(x) not in (int, float) or not 1e-4 <= x <= 100 for x in c["c_grid"])):
        raise ValueError("Invalid regularization grid")
    return c


def _summaries(value, mask):
    valid = mask > .5
    rows = []
    for row, use in zip(value, valid):
        selected = row[use]
        # A fully occluded view is a deliberate behavior probe. Encode its
        # absent summaries as zero while retaining zero coverage.
        rows.append(([0.] * 5 if not len(selected) else [float(selected.mean()), float(selected.std()),
                     *np.percentile(selected, (10, 50, 90)).tolist()]) + [float(use.mean())])
    return np.asarray(rows, dtype=np.float32)


def extract_features(x_global, x_local, x_scalar, kind):
    """Extract fixed label-free diagnostics from normalized shared_v1 tensors."""
    if kind not in KINDS:
        raise ValueError("Unknown diagnostic expert")
    arrays = [x.detach().cpu().numpy() if torch.is_tensor(x) else np.asarray(x) for x in
              (x_global, x_local, x_scalar)]
    g, local, scalar = arrays
    if g.ndim != 3 or g.shape[1:] != (200, 3) or local.shape != (len(g), 100, 3) or scalar.shape != (len(g), 7):
        raise ValueError("Invalid shared_v1 diagnostic inputs")
    gm, lm = g[:, :, 2], local[:, :, 2]
    if kind == "transit_morphology":
        center = local[:, 45:55, 0]
        inner = np.concatenate([local[:, 35:45, 0], local[:, 55:65, 0]], axis=1)
        wings = np.concatenate([local[:, 20:35, 0], local[:, 65:80, 0]], axis=1)
        left, right = local[:, :50, 0], local[:, 50:, 0][:, ::-1]
        features = np.column_stack([
            np.median(wings, axis=1) - np.median(center, axis=1),
            np.median(inner, axis=1) - np.median(center, axis=1),
            np.mean(np.abs(left - right), axis=1),
            np.std(center, axis=1), np.std(wings, axis=1),
            np.mean(lm[:, 45:55], axis=1), np.mean(lm, axis=1),
            np.median(local[:, :, 1], axis=1),
            *_summaries(local[:, :, 0], lm).T,
            *scalar.T,
        ])
    else:
        value = g[:, :, 0]
        diff = np.diff(value, axis=1)
        centered = value - value.mean(axis=1, keepdims=True)
        denom = np.sum(centered * centered, axis=1).clip(1e-8)
        autocorrelation = [np.sum(centered[:, :-lag] * centered[:, lag:], axis=1) / denom
                           for lag in (1, 5, 10, 20)]
        features = np.column_stack([
            *_summaries(value, gm).T,
            np.std(diff, axis=1), np.median(np.abs(diff), axis=1),
            np.percentile(value, 95, axis=1) - np.percentile(value, 5, axis=1),
            *autocorrelation,
            np.median(g[:, :, 1], axis=1), np.percentile(g[:, :, 1], 90, axis=1),
            *_summaries(local[:, :, 0], lm).T,
            *scalar.T,
        ])
    if not np.isfinite(features).all():
        raise ValueError("Nonfinite handcrafted diagnostic feature")
    return features.astype(np.float32)


class DiagnosticExpert(torch.nn.Module):
    def __init__(self, kind, mean, scale, coefficient, intercept):
        super().__init__(); self.kind = kind
        self.register_buffer("mean", torch.as_tensor(mean, dtype=torch.float32))
        self.register_buffer("scale", torch.as_tensor(scale, dtype=torch.float32))
        self.register_buffer("coefficient", torch.as_tensor(coefficient, dtype=torch.float32))
        self.register_buffer("intercept", torch.as_tensor(float(intercept), dtype=torch.float32))

    def forward(self, x_global, x_local, x_scalar, x_flat):
        features = torch.from_numpy(extract_features(x_global, x_local, x_scalar, self.kind)).to(x_global.device)
        return ((features - self.mean) / self.scale) @ self.coefficient + self.intercept


def fit_kind(kind, data, c):
    train, selection = data["tess"]["train"], data["tess"]["selection"]
    train_x = extract_features(train["x_global"], train["x_local"], train["x_scalar"], kind)
    selection_x = extract_features(selection["x_global"], selection["x_local"], selection["x_scalar"], kind)
    mean, scale = train_x.mean(axis=0), train_x.std(axis=0); scale[scale < 1e-6] = 1
    train_z, selection_z = (train_x - mean) / scale, (selection_x - mean) / scale
    rows = []
    for regularization in c["c_grid"]:
        fitted = LogisticRegression(C=regularization, max_iter=c["max_iterations"], solver="liblinear",
                                    random_state=1701, class_weight="balanced").fit(train_z, train["y"].numpy())
        logits = fitted.decision_function(selection_z)
        rows.append((metrics(selection["y"].numpy(), logits)["average_precision"], regularization, fitted))
    _, selected_c, fitted = max(rows, key=lambda row: (row[0], -row[1]))
    model = DiagnosticExpert(kind, mean, scale, fitted.coef_[0], fitted.intercept_[0]); model.eval()
    output = {"kind": kind, "selected_c": selected_c,
              "selection_ap_by_c": {str(C): score for score, C, _ in rows}, "partitions": {}}
    for role in ("selection", "calibration", "audit"):
        part = data["tess"][role]
        with torch.inference_mode(): logits = model(part["x_global"], part["x_local"], part["x_scalar"], part["x_flat"]).numpy()
        output["partitions"][role] = {"logits": logits, "labels": part["y"].numpy()}
    calibration = fit_temperature(output["partitions"]["calibration"]["labels"],
                                  output["partitions"]["calibration"]["logits"])
    output["calibration"] = calibration
    output["audit"] = {"raw": metrics(output["partitions"]["audit"]["labels"], output["partitions"]["audit"]["logits"]),
                       "calibrated": metrics(output["partitions"]["audit"]["labels"], output["partitions"]["audit"]["logits"], calibration["temperature"])}
    del output["partitions"]
    return model, output


def load_models(folder, expected_spec_sha):
    folder = ROOT / folder if not str(folder).startswith("/") else folder
    folder = __import__("pathlib").Path(folder)
    receipt = json.loads((folder / "complete.json").read_text())
    if receipt["spec_sha256"] != expected_spec_sha:
        raise ValueError("Diagnostic-expert identity mismatch")
    artifact = torch.load(folder / "diagnostic_experts.pt", map_location="cpu", weights_only=True)
    models = []
    for kind in KINDS:
        item = artifact["experts"][kind]
        model = DiagnosticExpert(kind, item["mean"], item["scale"], item["coefficient"], item["intercept"])
        model.load_state_dict(item["state"], strict=True); model.eval()
        models.append(({"arm": kind, "seed": 1701, "model_sha256": receipt["files"]["diagnostic_experts.pt"]}, model))
    return models


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/diagnostic_experts_v1.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--output", default="outputs/research/diagnostic_experts/pilot-v1")
    args = parser.parse_args(argv)
    c = validate_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()): raise ValueError("Diagnostic-expert output already exists")
    output.mkdir(parents=True, exist_ok=True)
    data, provenance = load_prepared(ROOT, adaptation)
    spec = {"version": VERSION, "config": c, "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in
                ("scripts/experiments/diagnostic_experts.py", "scripts/experiments/adaptation_data.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    results, experts = {}, {}
    for kind in KINDS:
        model, results[kind] = fit_kind(kind, data, c)
        experts[kind] = {"mean": model.mean, "scale": model.scale, "coefficient": model.coefficient,
                         "intercept": model.intercept, "state": model.state_dict()}
    torch.save({"version": VERSION, "spec_sha256": spec_sha, "experts": experts}, output / "diagnostic_experts.pt")
    summary = {"status": "complete", "version": VERSION, "generated_at": utc_now(), "spec_sha256": spec_sha,
               "results": results, "claims": {"original_test_evaluated": False, "search_ready": False,
               "physical_validation": False}, "limitations": ["Handcrafted experts use prepared known-ephemeris views",
               "No target-pixel, nearby-source or difference-image inputs are available", "Validation-derived audit is not a pristine final test"]}
    atomic_json(output / "spec.json", spec); atomic_json(output / "summary.json", summary)
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "diagnostic_experts.pt")}
    atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output),
        "audit": {k: v["audit"] for k, v in results.items()}}, indent=2))


if __name__ == "__main__": main()
