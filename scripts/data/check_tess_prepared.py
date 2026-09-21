#!/usr/bin/env python3
"""Read-only verification of prepared TESS artifacts and model input interfaces."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.data.tess_dataset import (
    apply_normalization, feature_names, fit_normalization, validate_dataset,
)

INPUT_KEYS = ("X_global", "X_local", "X_scalar", "X")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as saved:
        return {key: saved[key] for key in saved.files}


def _source_path(inputs: dict[str, str], prefix: str) -> Path:
    matches = [Path(name) for name in inputs
               if Path(name).name.startswith(prefix) and Path(name).suffix == ".npz"]
    if len(matches) != 1 or not matches[0].is_absolute():
        raise ValueError(f"Provenance must identify one absolute {prefix} source path")
    path = matches[0]
    if _digest(path) != inputs[str(path)]:
        raise ValueError(f"Kepler source checksum mismatch: {path}")
    return path


def _check_model_interfaces(arrays: dict[str, np.ndarray], stats: dict[str, np.ndarray],
                            indices: np.ndarray, row_source: str) -> dict[str, Any]:
    """Run a random CNN forward call only; no checkpoints or metrics."""
    import torch
    from training.cnn.train_kepler_cnn import ExoMinerStyleCNN

    normalized = apply_normalization({key: arrays[key][indices] for key in INPUT_KEYS}, stats)
    tensors = [torch.from_numpy(normalized[key]) for key in
               ("x_global", "x_local", "x_scalar", "x_flat")]
    report = {"performed": True, "purpose": "random_initialization_interface_only",
              "device": "cpu", "row_source": row_source, "batch_size": int(len(indices)),
              "models": {}}
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(min(2, previous_threads))
        with torch.random.fork_rng(devices=[]), torch.inference_mode():
            torch.manual_seed(42)
            models = {"ExoMinerStyleCNN": ExoMinerStyleCNN(
                scalar_features=7, flat_features=907, dropout=.20, scalar_dropout=.10,
                wide_dropout=.15, use_wide_branch=False, use_aux_branch=False)}
            for name, model in models.items():
                model.eval()
                output = model(*tensors)
                finite = bool(torch.isfinite(output).all().item())
                if tuple(output.shape) != (len(indices),) or not finite:
                    raise ValueError(f"{name} failed its finite-output/shape interface check")
                report["models"][name] = {"output_shape": list(output.shape), "finite_output": finite}
    finally:
        torch.set_num_threads(previous_threads)
    return report


def check_prepared(prepared_dir: Path, check_models: bool = False) -> dict[str, Any]:
    """Verify a completed preparation without modifying it or fitting on TESS."""
    root = Path(prepared_dir).resolve()
    summary = json.loads((root / "preparation_summary.json").read_text())
    provenance = json.loads((root / "provenance.json").read_text())
    if summary.get("status") != "complete":
        raise ValueError("Preparation must be complete before verification")
    payload = {key: value for key, value in provenance.items() if key != "signature"}
    if hashlib.sha256(_canonical_json(payload)).hexdigest() != provenance.get("signature"):
        raise ValueError("Preparation provenance signature mismatch")
    science = provenance["science"]
    pilot = bool(science["pilot_candidates"])
    outputs = summary.get("outputs", {})
    required = {"dataset_tess_v0.npz", "manifest_tess_v0.csv", "kepler_overlap.csv",
                "kepler_train_normalization.npz"}
    split_name = f"splits_tess_v0_seed{int(science['seed'])}.npz"
    if not pilot:
        required.update({split_name, "tess_train_normalization.npz"})
    if required - set(outputs):
        raise ValueError(f"Required outputs are absent from recorded checksums: {sorted(required - set(outputs))}")
    for name, expected in outputs.items():
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root) or path == root:
            raise ValueError(f"Recorded output is outside the prepared directory: {name}")
        if _digest(path) != expected:
            raise ValueError(f"Prepared output checksum mismatch: {name}")

    arrays = _load_npz(root / "dataset_tess_v0.npz")
    if str(arrays.get("preprocessing_version", "")) != science["version"]:
        raise ValueError("Dataset preprocessing version differs from provenance")
    manifest = pd.read_csv(root / "manifest_tess_v0.csv", dtype={"candidate_id": str, "split_group": str})
    overlap = pd.read_csv(root / "kepler_overlap.csv")
    if "tic_id" not in overlap:
        raise ValueError("Kepler overlap audit lacks TIC IDs")
    splits = None if pilot else _load_npz(root / split_name)
    retained = sorted({str(group) for group in science.get("train_only_groups", [])}
                      & set(manifest.split_group))
    validation = validate_dataset(arrays, manifest, splits,
                                  forbidden_tic_ids=overlap.tic_id.unique(), train_only_groups=retained)
    if summary.get("accepted_candidates") != len(manifest):
        raise ValueError("Accepted candidate count differs from the preparation summary")
    if "validation" in summary and validation != summary["validation"]:
        raise ValueError("Dataset validation differs from the preparation summary")
    recorded_groups = sorted(str(group) for group in summary.get("pilot_groups_reserved_for_training", []))
    if retained != recorded_groups:
        raise ValueError("Reserved pilot groups differ from the preparation summary")

    inputs = provenance["inputs"]
    dataset_path = _source_path(inputs, "dataset_kepler_")
    splits_path = _source_path(inputs, "splits_kepler_")
    # Legacy Kepler files contain object-dtype feature names. Only those already
    # hash-verified local source artifacts are opened with pickle enabled.
    with np.load(dataset_path, allow_pickle=True) as source, np.load(splits_path, allow_pickle=False) as source_splits:
        flat_names, scalar_names = feature_names()
        if (not np.array_equal(source["feature_names"].astype(str), flat_names)
                or not np.array_equal(source["scalar_feature_names"].astype(str), scalar_names)):
            raise ValueError("Kepler source feature order differs from the TESS contract")
        source_training_count = len(source_splits["train_idx"])
        expected_stats = fit_normalization({key: source[key] for key in INPUT_KEYS}, source_splits["train_idx"])
    saved_stats = _load_npz(root / "kepler_train_normalization.npz")
    if set(saved_stats) != set(expected_stats):
        raise ValueError("Saved Kepler normalization statistic keys differ")
    for name, expected in expected_stats.items():
        if saved_stats[name].dtype != np.float32 or not np.array_equal(saved_stats[name], expected):
            raise ValueError(f"Saved Kepler normalization differs from source training rows: {name}")
    model_report = {"performed": False}
    if check_models:
        indices = np.arange(min(4, len(manifest))) if pilot else splits["train_idx"][:4]
        model_report = _check_model_interfaces(arrays, saved_stats, indices, "pilot" if pilot else "train")
    return {"status": "passed", "prepared_dir": str(root), "mode": "pilot" if pilot else "full",
            "hash_checks": {"passed": True, "prepared_output_files": len(outputs),
                            "provenance_signature": True, "kepler_source_files": 2},
            "dataset_validation": validation,
            "source_normalization": {"matches_kepler_training_rows": True,
                                     "source_training_rows": int(source_training_count),
                                     "dataset_path": str(dataset_path), "splits_path": str(splits_path)},
            "model_interfaces": model_report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared_dir", type=Path, required=True)
    parser.add_argument("--check_models", action="store_true",
                        help="Forward at most four training/pilot rows through a random CNN")
    parser.add_argument("--report_path", type=Path, help="Optional new JSON report; otherwise stdout only")
    args = parser.parse_args()
    report = check_prepared(args.prepared_dir, args.check_models)
    text = _canonical_json(report).decode()
    if args.report_path is not None:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite any artifact or prior report during verification.
        with args.report_path.open("x") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
