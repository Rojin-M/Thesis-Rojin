#!/usr/bin/env python3
"""Compare the v0 and shared_v1 Kepler CNNs on fixed shared_v1 TESS test rows."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data.tess_dataset import fit_normalization
from scripts.experiments import run_tess_baseline as baseline


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _run_directory(pointer_path: Path) -> Path:
    pointer = json.loads(pointer_path.read_text())
    if pointer.get("status") != "complete":
        raise ValueError(f"CNN run is not complete: {pointer_path}")
    saved = Path(pointer["run_dir"])
    relocated = pointer_path.parent / saved.name
    run = relocated if relocated.is_dir() else saved
    if not run.is_dir():
        raise FileNotFoundError(run)
    return run.resolve()


def _prepared(base: Path, mission: str, version: str) -> tuple[dict, dict, pd.DataFrame, dict]:
    directory = base / "data/processed" / mission / version
    prefix = f"{mission}_{version}"
    paths = {
        "dataset": directory / f"dataset_{prefix}.npz",
        "splits": directory / f"splits_{prefix}_seed42.npz",
        "manifest": directory / f"manifest_{prefix}.csv",
        "normalization": directory / "kepler_train_normalization.npz",
        "summary": directory / "preparation_summary.json",
        "provenance": directory / "provenance.json",
    }
    if version == "v0" and mission == "kepler":
        paths["dataset"] = next(directory.glob("dataset_kepler_v0_*.npz"))
        paths["normalization"] = base / "data/processed/tess/v0/kepler_train_normalization.npz"
        paths.pop("summary")
        paths.pop("provenance")
    if version == "v0" and mission == "tess":
        paths["dataset"] = directory / "dataset_tess_v0.npz"
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    if "summary" in paths:
        summary = json.loads(paths["summary"].read_text())
        if summary.get("status") != "complete":
            raise ValueError(f"Incomplete prepared dataset: {directory}")
        for name, expected in summary["outputs"].items():
            if baseline._sha(directory / name) != expected:
                raise ValueError(f"Prepared artifact changed: {directory / name}")
    with np.load(paths["dataset"], allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in ("X_global", "X_local", "X_scalar", "X", "y")}
    splits = baseline._npz(paths["splits"])
    manifest = pd.read_csv(paths["manifest"], dtype={"candidate_id": str, "split_group": str})
    if not np.array_equal(arrays["y"], manifest.y.to_numpy()):
        raise ValueError(f"Dataset labels differ from manifest: {directory}")
    return arrays, splits, manifest, paths


def _checked_source(run: Path, paths: dict, arrays: dict, splits: dict,
                    stats: dict) -> tuple[dict, dict]:
    cfg = baseline.trainer.train_config_from_dict(json.loads((run / "config.json").read_text()))
    if cfg.seed != 42 or cfg.use_wide_branch or cfg.use_aux_branch:
        raise ValueError("Comparison requires the seed-42 common-input CNN")
    for key in ("dataset", "splits", "manifest"):
        configured = Path(getattr(cfg, key + "_path"))
        if configured.name != paths[key].name:
            raise ValueError(f"Source {key} does not match prepared version")
        if configured.is_file() and baseline._sha(configured) != baseline._sha(paths[key]):
            raise ValueError(f"Source {key} differs from the prepared artifact")
    fitted = fit_normalization(arrays, splits["train_idx"])
    if set(fitted) != set(stats) or any(not np.array_equal(fitted[key], stats[key]) for key in fitted):
        raise ValueError("Saved Kepler normalization differs from the source training rows")
    checkpoint, summary = baseline._training_record(run, cfg, baseline._model_config(cfg))
    return {"config": cfg, "checkpoint": checkpoint, "summary": summary}, fitted


def _replay_validation(source: dict, arrays: dict, splits: dict, manifest: pd.DataFrame,
                       stats: dict, run: Path, device: str) -> dict:
    validation, _ = baseline.evaluate_frozen_source(
        run, source["checkpoint"], arrays, manifest, {"test_idx": splits["val_idx"]}, stats, device)
    saved = pd.read_csv(run / "val_predictions.csv", dtype={"candidate_id": str})
    if (not np.array_equal(validation.candidate_id.to_numpy(), saved.candidate_id.to_numpy())
            or not np.array_equal(validation.y.to_numpy(), saved.y.to_numpy())):
        raise ValueError("Source validation replay changed candidate order or labels")
    difference = np.max(np.abs(validation.probability.to_numpy(dtype=np.float32)
                               - saved.probability.to_numpy(dtype=np.float32)))
    if difference > 1e-5:
        raise ValueError(f"Source validation replay differs from saved predictions: {difference}")
    return {"rows": int(len(saved)), "maximum_probability_difference": float(difference)}


def _score(frame: pd.DataFrame, manifest: pd.DataFrame, indices: np.ndarray,
           threshold: float) -> dict:
    metrics = baseline._checked_predictions(frame, manifest, indices, threshold)
    tn, fp, fn, tp = confusion_matrix(frame.y, frame.prediction, labels=[0, 1]).ravel()
    return {**metrics, "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def _verify_complete(output: Path) -> dict:
    completion = json.loads((output / "completion.json").read_text())
    if completion.get("status") != "complete":
        raise ValueError("Shared CNN transfer is incomplete")
    for name, expected in completion["artifacts"].items():
        if baseline._sha(output / name) != expected:
            raise ValueError(f"Saved transfer artifact changed: {name}")
    for name, expected in completion["inputs"].items():
        if baseline._sha(Path(name)) != expected:
            raise ValueError(f"Transfer input changed: {name}")
    comparison = pd.read_csv(output / "comparison.csv")
    for arm in ("v0", "shared_v1"):
        predictions = pd.read_csv(output / f"{arm}_predictions.csv", dtype={"candidate_id": str})
        row = comparison.loc[comparison.arm == arm].iloc[0]
        metrics = baseline.trainer.compute_metrics(
            predictions.y.to_numpy(), predictions.probability.to_numpy(dtype=np.float32), float(row.threshold))
        if any(not np.isclose(metrics[key], row[key], atol=1e-12, rtol=0) for key in metrics):
            raise ValueError(f"Saved {arm} metrics disagree with predictions")
    return completion


def evaluate(base: Path, output: Path, device: str, verify_only: bool = False,
             shared_run_pointer: Path | None = None, baseline_run_pointer: Path | None = None) -> dict:
    base = base.resolve()
    output = output.resolve()
    if verify_only or (output / "completion.json").is_file():
        return _verify_complete(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Transfer output directory must be new or empty")
    status = json.loads((base / "outputs/shared_preparation/shared_v1/full_status.json").read_text())
    verification = json.loads((base / "outputs/shared_preparation/shared_v1/full_verification.json").read_text())
    if status.get("status") != "complete" or verification.get("status") != "verified":
        raise ValueError("Both full shared_v1 datasets must be verified before model evaluation")

    target_arrays, target_splits, target_manifest, target_paths = _prepared(base, "tess", "shared_v1")
    if len(target_splits["test_idx"]) != 335:
        raise ValueError("TESS test membership differs from the fixed benchmark")
    source_runs = {
        "v0": _run_directory(baseline_run_pointer or base / "outputs/reproduce/cnn_baseline/run.json"),
        "shared_v1": _run_directory(shared_run_pointer or base / "outputs/shared_cnn/kepler/run.json"),
    }
    source_paths = {}
    sources = {}
    statistics = {}
    replays = {}
    for arm in source_runs:
        arrays, splits, manifest, paths = _prepared(base, "kepler", arm)
        stats = baseline._npz(paths["normalization"])
        source, _ = _checked_source(source_runs[arm], paths, arrays, splits, stats)
        if source["config"].prepare_version != arm:
            raise ValueError(f"Source preparation version differs from requested arm: {arm}")
        source_paths[arm] = paths
        sources[arm] = source
        statistics[arm] = stats
        replays[arm] = _replay_validation(source, arrays, splits, manifest, stats, source_runs[arm], device)
    excluded = {"base_dir", "dataset_path", "splits_path", "manifest_path", "output_root",
                "prepare_version", "device"}
    recipes = [{key: value for key, value in asdict(sources[arm]["config"]).items() if key not in excluded}
               for arm in source_runs]
    if recipes[0] != recipes[1]:
        raise ValueError("CNN recipes differ between v0 and shared_v1")

    input_paths = [target_paths[key] for key in ("dataset", "splits", "manifest", "normalization", "summary", "provenance")]
    input_paths += [source_paths[arm][key] for arm in source_runs
                    for key in ("dataset", "splits", "manifest", "normalization")]
    input_paths += [source_runs[arm] / name for arm in source_runs
                    for name in (*baseline.RUN_FILES, "test_predictions.csv")]
    inputs = {str(path.resolve()): baseline._sha(path) for path in input_paths}
    output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "seed": 42,
        "test_size": int(len(target_splits["test_idx"])),
        "test_candidate_ids_sha256": hashlib.sha256(
            json.dumps(target_manifest.iloc[target_splits["test_idx"]].candidate_id.tolist()).encode()).hexdigest(),
        "comparison": "Frozen Kepler CNN v0 and shared_v1 on identical shared_v1 TESS test inputs",
        "selection": "Kepler validation AP selects checkpoint; Kepler validation F1 selects threshold",
        "normalization": "Each source uses only its own Kepler training moments; no TESS fitting",
        "replay": replays,
        "recipe": recipes[0],
        "inputs": inputs,
        "code": {str(path.relative_to(base)): baseline._sha(path) for path in (
            Path(__file__).resolve(), base / "scripts/experiments/run_tess_baseline.py",
            base / "training/cnn/train_kepler_cnn.py", base / "scripts/data/tess_dataset.py")},
        "test_status": "Previously consulted benchmark; single seed; source training cohorts differ",
    }
    _write_json(output / "protocol.json", protocol)

    records = []
    for arm in source_runs:
        checkpoint = sources[arm]["checkpoint"]
        predictions, _ = baseline.evaluate_frozen_source(
            source_runs[arm], checkpoint, target_arrays, target_manifest, target_splits,
            statistics[arm], device)
        threshold = float(checkpoint["val_threshold"])
        metrics = _score(predictions, target_manifest, target_splits["test_idx"], threshold)
        predictions.to_csv(output / f"{arm}_predictions.csv", index=False)
        records.append({"arm": arm, "threshold": threshold, "best_epoch": int(checkpoint["epoch"]),
                        "test_size": len(predictions), **metrics})
    pd.DataFrame(records).to_csv(output / "comparison.csv", index=False)
    for name, expected in inputs.items():
        if baseline._sha(Path(name)) != expected:
            raise ValueError(f"Transfer input changed during inference: {name}")
    completion = {
        "status": "complete",
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "artifacts": {name: baseline._sha(output / name) for name in (
            "protocol.json", "v0_predictions.csv", "shared_v1_predictions.csv", "comparison.csv")},
    }
    _write_json(output / "completion.json", completion)
    return _verify_complete(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, default=ROOT)
    parser.add_argument("--output_dir", type=Path, default=ROOT / "outputs/shared_cnn/tess_transfer")
    parser.add_argument("--shared_run_pointer", type=Path)
    parser.add_argument("--baseline_run_pointer", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--verify_only", action="store_true")
    args = parser.parse_args()
    completion = evaluate(args.base_dir, args.output_dir, args.device, args.verify_only,
                          args.shared_run_pointer, args.baseline_run_pointer)
    print(json.dumps({"status": completion["status"], "comparison": str(args.output_dir / "comparison.csv")}, indent=2))


if __name__ == "__main__":
    main()
