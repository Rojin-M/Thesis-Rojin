#!/usr/bin/env python3
"""Apply the existing validation-selected Kepler v0 transformer to the fixed TESS test."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import torch

from scripts.data.check_tess_prepared import check_prepared
from scripts.experiments.run_tess_baseline import (
    INPUT_KEYS, RUN_FILES, _checked_predictions, _json_bytes, _now, _npz,
    _sha, _training_record, _verify_files, _write, _write_json, source_inputs,
)
from training.transformer import train_kepler_transformer as trainer

ARM = "kepler_transformer"


def predict(model, arrays, indices, stats, batch_size, device):
    """Normalize only with supplied source moments; preserve the requested row order."""
    normalized = source_inputs({key: arrays[key][indices] for key in INPUT_KEYS}, stats)
    probabilities = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(indices), batch_size):
            batch = [torch.from_numpy(normalized[key][start:start + batch_size]).to(device)
                     for key in ("x_global", "x_local", "x_scalar", "x_flat")]
            probabilities.append(torch.sigmoid(model(*batch)).cpu().numpy())
    return np.concatenate(probabilities).astype(np.float32)


def verify(output: Path) -> dict:
    output = output.resolve()
    completion = json.loads((output / "completion.json").read_text())
    protocol = json.loads((output / "protocol.json").read_text())
    signature = hashlib.sha256(_json_bytes({k: v for k, v in protocol.items() if k != "signature"})).hexdigest()
    if (completion.get("status") != "complete" or protocol["signature"] != signature
            or completion["protocol_signature"] != signature):
        raise ValueError("Evaluation completion or protocol signature mismatch")
    _verify_files(output, completion["artifacts"])
    for name, expected in protocol["input_sha256"].items():
        if _sha(Path(name)) != expected:
            raise ValueError(f"Frozen evaluation input changed: {name}")
    prepared = Path(protocol["prepared"]["directory"])
    manifest = pd.read_csv(prepared / "manifest_tess_v0.csv", dtype={"candidate_id": str})
    indices = _npz(prepared / "splits_tess_v0_seed42.npz")["test_idx"]
    record = completion["arms"][ARM]
    frame = pd.read_csv(output / f"{ARM}_predictions.csv", dtype={"candidate_id": str})
    metrics = _checked_predictions(frame, manifest, indices, record["threshold"])
    for key, value in metrics.items():
        np.testing.assert_allclose(value, record["metrics"][key], rtol=0, atol=1e-12)
    return {"status": "passed", "metrics_reconstructed": True, "test_candidates": len(indices),
            "artifact_hashes": len(completion["artifacts"]), "metrics": metrics}


def evaluate(base: Path, output: Path, device_name: str = "auto") -> dict:
    base, output = base.resolve(), output.resolve()
    prepared = base / "data/processed/tess/v0"
    study = base / "outputs/reproduce/transformer"
    selection_path = study / "selection.json"
    selection = json.loads(selection_path.read_text())
    variant = selection["selected_variant"]
    if variant not in ("bypass_input_norm", "legacy_input_norm"):
        raise ValueError("Unknown Kepler validation-selected transformer variant")
    runs = list((study / variant / "seed_42").glob("*/best_model.pt"))
    if len(runs) != 1:
        raise ValueError("Expected exactly one existing selected seed-42 v0 transformer checkpoint")
    source = runs[0].parent
    for protected in (base / "data", base / "outputs/reproduce", prepared, source):
        if output == protected or output in protected.parents or protected in output.parents:
            raise ValueError("Output must be separate from prepared data and original runs")
    if output.exists():
        raise ValueError("Use a new output directory, or --verify_only for the saved evaluation")
    verification = check_prepared(prepared)
    if verification["mode"] != "full":
        raise ValueError("A verified full TESS dataset is required")
    preparation = json.loads((prepared / "provenance.json").read_text())
    prepared_summary = json.loads((prepared / "preparation_summary.json").read_text())
    cfg = trainer.TrainConfig(**json.loads((source / "config.json").read_text()))
    model_cfg = json.loads((source / "model_config.json").read_text())
    if (cfg.seed != 42 or cfg.use_aux_branch or cfg.use_input_norm != (variant == "legacy_input_norm")
            or model_cfg.get("use_aux_branch") or model_cfg.get("aux_features", 0) != 0):
        raise ValueError("Source must be the selected seed-42 v0 transformer without auxiliary inputs")
    for key in ("d_model", "num_heads", "global_depth", "local_depth", "mlp_ratio", "dropout",
                "attention_dropout", "token_dropout", "scalar_dropout", "use_input_norm"):
        if model_cfg[key] != getattr(cfg, key):
            raise ValueError(f"Model/config disagreement: {key}")
    if tuple(model_cfg[k] for k in ("global_seq_len", "local_seq_len", "scalar_features")) != (200, 100, 7):
        raise ValueError("Source input geometry differs from common v0 inputs")
    # CNN and transformer trainers share the same saved checkpoint/validation contract.
    checkpoint, summary = _training_record(source, cfg, model_cfg)
    source_paths = {}
    for key in ("dataset_path", "splits_path", "manifest_path"):
        original = Path(getattr(cfg, key))
        candidates = [Path(p) for p in preparation["inputs"] if Path(p).name == original.name]
        if len(candidates) != 1 or _sha(candidates[0]) != preparation["inputs"][str(candidates[0])]:
            raise ValueError(f"Prepared source input mismatch: {key}")
        source_paths[key] = candidates[0]
    audit_path = study / "results/verification.json"
    audit = json.loads(audit_path.read_text())["source_files_sha256"]
    # Match historical paths by their repository-relative suffix after relocation.
    for path in [source / n for n in RUN_FILES] + list(source_paths.values()) + [
            ROOT / "training/transformer/train_kepler_transformer.py", ROOT / "training/cnn/train_kepler_cnn.py"]:
        relative = path.relative_to(base).as_posix()
        expected = [digest for name, digest in audit.items() if name.endswith("/" + relative)]
        if len(expected) != 1 or _sha(path) != expected[0]:
            raise ValueError(f"Source differs from the completed Kepler study: {relative}")
    stats = _npz(prepared / "kepler_train_normalization.npz")
    source_splits = _npz(source_paths["splits_path"])
    # Only hash-verified legacy Kepler files contain pickled feature-name arrays.
    with np.load(source_paths["dataset_path"], allow_pickle=True) as data:
        source_arrays = {key: data[key] for key in INPUT_KEYS}
    source_manifest = pd.read_csv(source_paths["manifest_path"], dtype={"candidate_id": str})
    saved_validation = pd.read_csv(source / "val_predictions.csv", dtype={"candidate_id": str})
    val_indices = source_splits["val_idx"]
    for key in ("candidate_id", "y"):
        np.testing.assert_array_equal(saved_validation[key], source_manifest.iloc[val_indices][key])
    device = trainer.detect_device(device_name)
    trainer.set_seed(42)
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("high")
    model = trainer.ExoFormer(**model_cfg).to(device)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    replay = predict(model, source_arrays, val_indices, stats, cfg.batch_size, device)
    np.testing.assert_allclose(replay, saved_validation.probability.to_numpy(dtype=np.float32), rtol=1e-5, atol=1e-6)
    replay_error = float(np.max(np.abs(replay - saved_validation.probability.to_numpy(dtype=np.float32))))
    print(f"Kepler validation replay passed; maximum probability difference {replay_error:.3g}", flush=True)
    arrays = _npz(prepared / "dataset_tess_v0.npz")
    splits = _npz(prepared / "splits_tess_v0_seed42.npz")
    manifest = pd.read_csv(prepared / "manifest_tess_v0.csv", dtype={"candidate_id": str})
    indices = splits["test_idx"]
    input_paths = [source / name for name in RUN_FILES] + list(source_paths.values()) + [
        selection_path, audit_path, prepared / "preparation_summary.json", prepared / "provenance.json"]
    input_paths += [prepared / name for name in prepared_summary["outputs"]]
    code_paths = [Path(__file__).resolve(), ROOT / "training/transformer/train_kepler_transformer.py",
                  ROOT / "training/cnn/train_kepler_cnn.py", ROOT / "scripts/data/tess_dataset.py",
                  ROOT / "scripts/data/check_tess_prepared.py", ROOT / "scripts/experiments/run_tess_baseline.py"]
    protocol = {
        "schema_version": 1, "created_utc": _now(), "seed": 42,
        "scope": "Frozen Kepler transformer on the previously consulted fixed TESS benchmark; single seed",
        "selection": {"source_variant": variant, "source_seed": "42, matched to the first CNN comparison",
                      "source_checkpoint": "maximum Kepler validation AP",
                      "source_threshold": "unchanged Kepler validation F1 threshold",
                      "tess_finetuning": False, "tess_recalibration": False, "tess_test_tuning": False},
        "source": {"run_dir": str(source), "epoch": checkpoint["epoch"],
                   "threshold": checkpoint["val_threshold"], "checkpoint_sha256": _sha(source / "best_model.pt"),
                   "model_config": model_cfg, "config": checkpoint["config"]},
        "source_validation_replay": {"passed": True, "rows": len(val_indices), "max_absolute_error": replay_error,
                                     "rtol": 1e-5, "atol": 1e-6},
        "normalization": "Unchanged Kepler training moments from verified kepler_train_normalization.npz",
        "prepared": {"directory": str(prepared), "outputs": prepared_summary["outputs"]},
        "test_rows": {"count": len(indices),
                      "candidate_ids_sha256": hashlib.sha256(_json_bytes(manifest.iloc[indices].candidate_id.tolist())).hexdigest()},
        "execution": {"device": str(device), "batch_size": cfg.batch_size, "precision": "float32",
                      "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None},
        "environment": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "torch", "scikit-learn")},
        "input_sha256": {str(path): _sha(path) for path in input_paths},
        "code_sha256": {str(path.relative_to(ROOT)): _sha(path) for path in code_paths},
    }
    protocol["signature"] = hashlib.sha256(_json_bytes(protocol)).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "protocol.json", protocol)
    _write_json(output / "run.json", {"status": "running", "started_utc": _now()})
    try:
        probabilities = predict(model, arrays, indices, stats, cfg.batch_size, device)
        threshold = float(checkpoint["val_threshold"])
        frame = manifest.iloc[indices].copy()
        frame["probability"] = probabilities
        frame["prediction"] = (probabilities >= threshold).astype(np.int64)
        metrics = _checked_predictions(frame, manifest, indices, threshold)
        _write(output / f"{ARM}_predictions.csv", frame.to_csv(index=False).encode())
        record = {"arm": ARM, "name": "frozen Kepler transformer v0 on TESS", "test_size": len(indices),
                  "threshold": threshold, "threshold_fit_split": "Kepler validation",
                  "best_epoch": int(checkpoint["epoch"]), "metrics": metrics,
                  "checkpoint_sha256": protocol["source"]["checkpoint_sha256"]}
        _write_json(output / f"{ARM}_metrics.json", record)
        for name, digest in protocol["input_sha256"].items():
            if _sha(Path(name)) != digest:
                raise ValueError(f"Input changed during evaluation: {name}")
        for name, digest in protocol["code_sha256"].items():
            if _sha(ROOT / name) != digest:
                raise ValueError(f"Code changed during evaluation: {name}")
        completion = {"status": "complete", "finished_utc": _now(), "protocol_signature": protocol["signature"],
                      "arms": {ARM: record}, "artifacts": {name: _sha(output / name) for name in (
                          "protocol.json", f"{ARM}_metrics.json", f"{ARM}_predictions.csv")}}
        _write_json(output / "completion.json", completion)
        report = verify(output)
        _write_json(output / "verification.json", report)
        _write_json(output / "run.json", {"status": "complete", "finished_utc": completion["finished_utc"]})
        return report
    except BaseException as exc:
        _write_json(output / "run.json", {"status": "incomplete", "error": str(exc)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--verify_only", action="store_true", help="Check saved hashes and metrics without inference")
    args = parser.parse_args()
    output = args.output_dir or args.base_dir / "outputs/tess_transformer/seed42"
    result = verify(output) if args.verify_only else evaluate(args.base_dir, output, args.device)
    print(json.dumps(result, indent=2))
