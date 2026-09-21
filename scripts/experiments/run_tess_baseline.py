#!/usr/bin/env python3
"""Compare one TESS-trained CNN with a frozen Kepler CNN on the same TESS test."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.data.check_tess_prepared import check_prepared
from scripts.data.tess_dataset import apply_normalization, fit_normalization
from training.cnn import train_kepler_cnn as trainer

INPUT_KEYS = ("X_global", "X_local", "X_scalar", "X")
RUN_FILES = ("config.json", "model_config.json", "summary.json", "best_model.pt",
             "history.csv", "val_predictions.csv")
ARM_NAMES = {"tess_trained": "TESS-trained CNN v0",
             "kepler_frozen": "frozen Kepler CNN v0 on TESS"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _write(path, _json_bytes(value))


def _npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as saved:
        return {name: saved[name] for name in saved.files}


def _source_directory(base: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).resolve()
    pointer_path = base / "outputs/reproduce/cnn_baseline/run.json"
    pointer = json.loads(pointer_path.read_text())
    if pointer.get("status") != "complete":
        raise ValueError("The source CNN run pointer must be complete")
    old = Path(pointer["run_dir"])
    relocated = pointer_path.parent / old.name
    return (relocated if relocated.is_dir() else old).resolve()


def _model_config(cfg: trainer.TrainConfig) -> dict[str, Any]:
    return {"scalar_features": 7, "flat_features": 907, "dropout": cfg.dropout,
            "scalar_dropout": cfg.scalar_dropout, "wide_dropout": cfg.wide_dropout,
            "use_wide_branch": False, "use_aux_branch": False, "aux_features": 0,
            "aux_dropout": cfg.aux_dropout}


def _probabilities(frame: pd.DataFrame) -> np.ndarray:
    if not {"y", "probability", "prediction"}.issubset(frame.columns):
        raise ValueError("Prediction records require labels, probabilities, and predictions")
    # Original trainer probabilities are float32; round-trip CSV values back to
    # that dtype before checking threshold ties and ranking metrics.
    probabilities = frame.probability.to_numpy(dtype=np.float32)
    if (not len(frame) or not np.isfinite(probabilities).all()
            or not np.isin(frame.y, [0, 1]).all()
            or ((probabilities < 0) | (probabilities > 1)).any()):
        raise ValueError("Invalid saved prediction probabilities or labels")
    return probabilities


def _training_record(run: Path, expected_cfg: trainer.TrainConfig,
                     expected_model: dict[str, Any]) -> tuple[dict, dict]:
    for name in RUN_FILES:
        if not (run / name).is_file():
            raise ValueError(f"Incomplete CNN training record: {run / name}")
    cfg = json.loads((run / "config.json").read_text())
    model_cfg = json.loads((run / "model_config.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    checkpoint = torch.load(run / "best_model.pt", map_location="cpu")
    saved_cfg = asdict(trainer.train_config_from_dict(cfg))
    checkpoint_cfg = asdict(trainer.train_config_from_dict(checkpoint.get("config", {})))
    if saved_cfg != asdict(expected_cfg) or checkpoint_cfg != saved_cfg:
        raise ValueError("Saved CNN configuration differs from the frozen protocol")
    if model_cfg != expected_model or checkpoint.get("model_config") != expected_model:
        raise ValueError("Saved CNN architecture differs from the common-input baseline")
    if "model_state" not in checkpoint or checkpoint.get("aux_preprocessing") is not None:
        raise ValueError("Checkpoint must contain baseline weights without auxiliary preprocessing")
    threshold = float(checkpoint["val_threshold"])
    epoch = int(checkpoint["epoch"])
    if (not np.isfinite(threshold) or not 0 <= threshold <= 1 or epoch < 1
            or summary.get("best_epoch") != epoch or summary.get("best_threshold") != threshold):
        raise ValueError("Checkpoint and summary disagree on validation selection")
    history = pd.read_csv(run / "history.csv")
    if (history.empty or not {"epoch", "val_pr_auc", "val_threshold"}.issubset(history.columns)
            or not np.isfinite(history[["epoch", "val_pr_auc", "val_threshold"]].to_numpy()).all()):
        raise ValueError("Invalid CNN validation history")
    chosen = history.loc[history.val_pr_auc.idxmax()]
    if (int(chosen.epoch) != epoch or not np.isclose(chosen.val_threshold, threshold, rtol=0, atol=1e-12)
            or not np.isclose(chosen.val_pr_auc, checkpoint["val_pr_auc"], rtol=0, atol=1e-12)):
        raise ValueError("Checkpoint was not selected by the recorded maximum validation AP")
    validation = pd.read_csv(run / "val_predictions.csv")
    probabilities = _probabilities(validation)
    selected_threshold = trainer.build_threshold(validation.y.to_numpy(), probabilities, expected_cfg.threshold_grid_size)
    if selected_threshold != threshold:
        raise ValueError("Checkpoint threshold differs from validation-only F1 selection")
    if not np.array_equal(validation.prediction.to_numpy(), (probabilities >= threshold).astype(np.int64)):
        raise ValueError("Validation predictions do not use the selected threshold")
    validation_ap = trainer.compute_metrics(validation.y.to_numpy(), probabilities, threshold)["pr_auc"]
    if not np.isclose(validation_ap, checkpoint["val_pr_auc"], rtol=0, atol=1e-12):
        raise ValueError("Saved validation predictions disagree with checkpoint AP")
    return checkpoint, summary


def source_inputs(arrays: dict[str, np.ndarray], stats: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Use supplied Kepler training moments; no TESS fitting or recalibration."""
    return apply_normalization({key: arrays[key] for key in INPUT_KEYS}, stats)


def evaluate_frozen_source(source_run: Path, checkpoint: dict, arrays: dict[str, np.ndarray],
                           manifest: pd.DataFrame, splits: dict[str, np.ndarray],
                           stats: dict[str, np.ndarray], device: str) -> tuple[pd.DataFrame, dict]:
    """Evaluate only fixed test rows with source weights and source threshold."""
    del source_run
    indices = splits["test_idx"]
    normalized = source_inputs({key: arrays[key][indices] for key in INPUT_KEYS}, stats)
    selected_device = trainer.detect_device(device)
    model = trainer.ExoMinerStyleCNN(**checkpoint["model_config"]).to(selected_device)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    torch.set_float32_matmul_precision("high")
    probabilities = []
    batch_size = int(checkpoint["config"]["batch_size"])
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            batch = [torch.from_numpy(normalized[key][start:start + batch_size]).to(selected_device)
                     for key in ("x_global", "x_local", "x_scalar", "x_flat")]
            probabilities.append(torch.sigmoid(model(*batch)).cpu().numpy())
    probability = np.concatenate(probabilities).astype(np.float32)
    threshold = float(checkpoint["val_threshold"])
    frame = manifest.iloc[indices].copy()
    frame["probability"] = probability
    frame["prediction"] = (probability >= threshold).astype(np.int64)
    metrics = trainer.compute_metrics(arrays["y"][indices], probability, threshold)
    return frame, metrics


def _checked_predictions(frame: pd.DataFrame, manifest: pd.DataFrame, indices: np.ndarray,
                         threshold: float) -> dict[str, float]:
    expected = manifest.iloc[indices]
    for key in ("candidate_id", "tic_id", "y"):
        if key not in frame or not np.array_equal(frame[key].to_numpy(), expected[key].to_numpy()):
            raise ValueError(f"Prediction {key} order differs from the fixed split")
    probabilities = _probabilities(frame)
    if not np.array_equal(frame.prediction.to_numpy(), (probabilities >= threshold).astype(np.int64)):
        raise ValueError("Predictions do not use the frozen threshold")
    return trainer.compute_metrics(expected.y.to_numpy(), probabilities, threshold)


def _verify_files(root: Path, files: dict[str, str]) -> None:
    for relative, expected in files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or _sha(path) != expected:
            raise ValueError(f"Recorded comparison artifact checksum mismatch: {relative}")


def _target_run(output: Path, cfg: trainer.TrainConfig, model_config: dict,
                signature: str, manifest: pd.DataFrame, splits: dict) -> tuple[Path, dict, dict]:
    pointer_path = output / "target_run.json"
    target_root = Path(cfg.output_root)
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text())
        if pointer.get("protocol_signature") != signature or pointer.get("status") != "complete":
            raise ValueError("Target pointer differs from the frozen protocol")
        _verify_files(output, pointer["artifacts"])
        run = Path(pointer["run_dir"]).resolve()
        if not run.is_relative_to(target_root):
            raise ValueError("Target run pointer is outside this comparison")
    else:
        existing = sorted(target_root.iterdir()) if target_root.exists() else []
        if existing:
            if len(existing) != 1 or not existing[0].is_dir() or not (existing[0] / "summary.json").is_file():
                raise ValueError("Incomplete target training exists; preserve it and use a new output directory")
            run = existing[0]
        else:
            target_root.mkdir(parents=True, exist_ok=True)
            run = Path(trainer.train_model(cfg)).resolve()
            if not run.is_relative_to(target_root):
                raise ValueError("Trainer returned a run outside the isolated target directory")
    checkpoint, summary = _training_record(run, cfg, model_config)
    validation = pd.read_csv(run / "val_predictions.csv", dtype={"candidate_id": str})
    _checked_predictions(validation, manifest, splits["val_idx"], float(checkpoint["val_threshold"]))
    if not (run / "test_predictions.csv").is_file():
        raise ValueError("Target run is missing its final test predictions; refusing automatic retraining")
    predictions = pd.read_csv(run / "test_predictions.csv", dtype={"candidate_id": str})
    metrics = _checked_predictions(predictions, manifest, splits["test_idx"], float(checkpoint["val_threshold"]))
    for key, value in metrics.items():
        if not np.isclose(value, summary["test_metrics"][key], rtol=0, atol=1e-12):
            raise ValueError(f"Saved target test metric disagrees with its predictions: {key}")
    files = {str((run / name).relative_to(output)): _sha(run / name)
             for name in (*RUN_FILES, "test_predictions.csv")}
    _write_json(pointer_path, {"status": "complete", "protocol_signature": signature,
                              "run_dir": str(run), "artifacts": files})
    record = {"arm": "tess_trained", "name": ARM_NAMES["tess_trained"],
              "protocol_signature": signature,
              "threshold": float(checkpoint["val_threshold"]),
              "threshold_fit_split": "TESS validation", "best_epoch": int(checkpoint["epoch"]),
              "checkpoint_sha256": _sha(run / "best_model.pt"), "test_size": len(predictions),
              "metrics": metrics}
    _write_json(output / "tess_trained_metrics.json", record)
    _write(output / "tess_trained_predictions.csv", predictions.to_csv(index=False).encode())
    return run, record, files


def _run_locked(base: Path, prepared: Path, output: Path, source_run: Path, device: str) -> dict:
    verified = check_prepared(prepared)
    if verified.get("status") != "passed" or verified.get("mode") != "full":
        raise ValueError("Comparison requires a verified full TESS preparation, not a pilot")
    preparation = json.loads((prepared / "provenance.json").read_text())
    prepared_summary = json.loads((prepared / "preparation_summary.json").read_text())
    if preparation["science"]["seed"] != 42:
        raise ValueError("This first comparison uses the prespecified seed 42 split")
    arrays = _npz(prepared / "dataset_tess_v0.npz")
    splits_path = prepared / "splits_tess_v0_seed42.npz"
    splits = _npz(splits_path)
    manifest_path = prepared / "manifest_tess_v0.csv"
    manifest = pd.read_csv(manifest_path, dtype={"candidate_id": str, "split_group": str})
    source_stats = _npz(prepared / "kepler_train_normalization.npz")
    target_stats = _npz(prepared / "tess_train_normalization.npz")
    fitted = fit_normalization(arrays, splits["train_idx"])
    if set(fitted) != set(target_stats) or any(not np.array_equal(fitted[key], target_stats[key]) for key in fitted):
        raise ValueError("Saved TESS normalization differs from original trainer training-row statistics")
    source_cfg = trainer.train_config_from_dict(json.loads((source_run / "config.json").read_text()))
    if source_cfg.seed != 42 or source_cfg.use_wide_branch or source_cfg.use_aux_branch:
        raise ValueError("Source must be the seed 42 CNN without wide or auxiliary branches")
    model_config = _model_config(source_cfg)
    source_checkpoint, _ = _training_record(source_run, source_cfg, model_config)
    source_files = {}
    for key in ("dataset_path", "splits_path", "manifest_path"):
        historical = Path(getattr(source_cfg, key))
        matches = [Path(name) for name in preparation["inputs"] if Path(name).name == historical.name]
        if len(matches) != 1 or not matches[0].is_absolute():
            raise ValueError(f"Prepared provenance does not identify source {key}")
        path = matches[0]
        expected = preparation["inputs"][str(path)]
        if _sha(path) != expected or (historical.is_file() and _sha(historical) != expected):
            raise ValueError(f"Source training input differs from frozen preparation provenance: {key}")
        source_files[key] = {"path": str(path), "sha256": expected}
    cfg = replace(source_cfg, base_dir=str(base), dataset_path=str(prepared / "dataset_tess_v0.npz"),
                  splits_path=str(splits_path), manifest_path=str(manifest_path),
                  output_root=str(output / "target"), prepare_version=preparation["science"]["version"],
                  device=device)
    resolved_device = trainer.detect_device(device)
    execution = {"requested_device": device, "resolved_device": str(resolved_device),
                 "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}
    if resolved_device.type == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("The requested CUDA device is unavailable")
        device_index = resolved_device.index if resolved_device.index is not None else torch.cuda.current_device()
        execution.update(resolved_device=f"cuda:{device_index}", gpu_name=torch.cuda.get_device_name(device_index))
    indices = splits["test_idx"]
    protocol = {
        "schema_version": 1, "seed": 42, "single_seed_descriptive_comparison": True,
        "arms": ARM_NAMES,
        "scope": "One seed on a curated labelled TOI subset; not a general survey-vetting evaluation",
        "input_schema": "CNN v0 shared views and seven scalars",
        "source_transfer": "zero-shot with frozen Kepler weights and no fine-tuning",
        "selection": {"target_checkpoint": "maximum TESS validation average precision",
                      "target_threshold": "maximum F1 on validation at the selected checkpoint",
                      "source_threshold": "unchanged Kepler validation threshold from source checkpoint",
                      "threshold_grid": {"minimum": .05, "maximum": .95, "size": cfg.threshold_grid_size},
                      "target_test_tuning": False, "source_finetuning": False,
                      "source_target_recalibration": False,
                      "test_evaluation": "one final prediction set per arm on identical fixed test rows"},
        "primary_metric": "sklearn average_precision_score",
        "prepared": {"directory": str(prepared), "provenance_sha256": _sha(prepared / "provenance.json"),
                     "summary_sha256": _sha(prepared / "preparation_summary.json"),
                     "outputs": prepared_summary["outputs"]},
        "source": {"run_dir": str(source_run), "checkpoint_sha256": _sha(source_run / "best_model.pt"),
                   "epoch": int(source_checkpoint["epoch"]), "threshold": float(source_checkpoint["val_threshold"]),
                   "model_config": model_config, "input_files": source_files,
                   "run_files": {name: _sha(source_run / name) for name in RUN_FILES}},
        "normalization": {
            "kepler_frozen": {"fit": "Kepler source train_idx", "path": str(prepared / "kepler_train_normalization.npz"),
                              "sha256": _sha(prepared / "kepler_train_normalization.npz")},
            "tess_trained": {"fit": "TESS train_idx", "path": str(prepared / "tess_train_normalization.npz"),
                             "sha256": _sha(prepared / "tess_train_normalization.npz")}},
        "target_config": asdict(cfg),
        "execution": execution,
        "test_rows": {"count": len(indices),
                      "indices_sha256": hashlib.sha256(np.asarray(indices, dtype="<i8").tobytes()).hexdigest(),
                      "candidate_ids_sha256": hashlib.sha256(_json_bytes(manifest.iloc[indices].candidate_id.tolist())).hexdigest()},
        "environment": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "torch", "scikit-learn")},
        "code": {str(path.relative_to(ROOT)): _sha(path) for path in (
            Path(__file__).resolve(), ROOT / "training/cnn/train_kepler_cnn.py",
            ROOT / "scripts/data/tess_dataset.py", ROOT / "scripts/data/check_tess_prepared.py")},
    }
    signature = hashlib.sha256(_json_bytes(protocol)).hexdigest()
    protocol["signature"] = signature
    protocol_path = output / "protocol.json"
    if protocol_path.exists():
        if json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("Existing comparison protocol differs; use a new output directory")
    elif any(path.name != "comparison.lock" for path in output.iterdir()):
        raise ValueError("Existing output has no matching comparison protocol")
    else:
        _write_json(protocol_path, protocol)
    completion_path = output / "completion.json"
    if completion_path.exists():
        completion = json.loads(completion_path.read_text())
        if completion.get("status") != "complete" or completion.get("protocol_signature") != signature:
            raise ValueError("Completion differs from the frozen comparison protocol")
        _verify_files(output, completion["artifacts"])
        return completion

    status_path = output / "run.json"
    status = {"status": "running", "started_utc": _now(), "protocol_signature": signature}
    _write_json(status_path, status)
    try:
        target_run, target_record, target_files = _target_run(output, cfg, model_config, signature, manifest, splits)
        source_record_path = output / "kepler_frozen_metrics.json"
        source_prediction_path = output / "kepler_frozen_predictions.csv"
        if source_record_path.exists():
            source_record = json.loads(source_record_path.read_text())
            if (source_record.get("protocol_signature") != signature
                    or _sha(source_prediction_path) != source_record["predictions_sha256"]):
                raise ValueError("Saved source evaluation differs from this protocol or checksum")
            predictions = pd.read_csv(source_prediction_path, dtype={"candidate_id": str})
        else:
            if source_prediction_path.exists():
                raise ValueError("Incomplete source evaluation exists without its checksum record; preserve it for review")
            predictions, _ = evaluate_frozen_source(source_run, source_checkpoint, arrays, manifest,
                                                    splits, source_stats, device)
        metrics = _checked_predictions(predictions, manifest, indices, float(source_checkpoint["val_threshold"]))
        if source_record_path.exists():
            if metrics != source_record["metrics"]:
                raise ValueError("Saved source metrics disagree with the fixed prediction set")
        else:
            _write(source_prediction_path, predictions.to_csv(index=False).encode())
            source_record = {"arm": "kepler_frozen", "name": ARM_NAMES["kepler_frozen"],
                             "protocol_signature": signature,
                             "threshold": float(source_checkpoint["val_threshold"]),
                             "threshold_fit_split": "Kepler validation", "best_epoch": int(source_checkpoint["epoch"]),
                             "checkpoint_sha256": protocol["source"]["checkpoint_sha256"], "test_size": len(predictions),
                             "predictions_sha256": _sha(source_prediction_path), "metrics": metrics}
            _write_json(source_record_path, source_record)
        comparison = pd.DataFrame([{"arm": record["name"], "threshold": record["threshold"],
                                    "threshold_fit_split": record["threshold_fit_split"],
                                    "test_size": record["test_size"], **record["metrics"]}
                                   for record in (target_record, source_record)])
        _write(output / "comparison.csv", comparison.to_csv(index=False).encode())
        # Recheck every frozen prepared/source input after both arms finish.
        for name, expected in protocol["prepared"]["outputs"].items():
            if _sha(prepared / name) != expected:
                raise ValueError(f"Prepared input changed during comparison: {name}")
        for name, key in (("provenance.json", "provenance_sha256"), ("preparation_summary.json", "summary_sha256")):
            if _sha(prepared / name) != protocol["prepared"][key]:
                raise ValueError(f"Prepared provenance changed during comparison: {name}")
        for relative, expected in protocol["code"].items():
            if _sha(ROOT / relative) != expected:
                raise ValueError(f"Comparison implementation changed during training: {relative}")
        for record in source_files.values():
            if _sha(Path(record["path"])) != record["sha256"]:
                raise ValueError("Kepler source input changed during comparison")
        for name, expected in protocol["source"]["run_files"].items():
            if _sha(source_run / name) != expected:
                raise ValueError("Frozen source run changed during comparison")
        artifacts = {**target_files, **{name: _sha(output / name) for name in (
            "protocol.json", "target_run.json", "tess_trained_metrics.json", "tess_trained_predictions.csv",
            "kepler_frozen_metrics.json", "kepler_frozen_predictions.csv", "comparison.csv")}}
        completion = {"status": "complete", "finished_utc": _now(), "protocol_signature": signature,
                      "target_run_dir": str(target_run), "source_run_dir": str(source_run),
                      "single_seed_descriptive_comparison": True, "test_size": len(indices),
                      "arms": {record["arm"]: record for record in (target_record, source_record)},
                      "artifacts": artifacts}
        _write_json(completion_path, completion)
        status.update(status="complete", finished_utc=completion["finished_utc"])
        _write_json(status_path, status)
        return completion
    except BaseException as exc:
        status.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "incomplete", error=str(exc))
        _write_json(status_path, status)
        raise


def run_comparison(base_dir: Path, prepared_dir: Path | None = None, output_dir: Path | None = None,
                   source_run_dir: Path | None = None, device: str = "auto") -> dict:
    base = Path(base_dir).resolve()
    prepared = Path(prepared_dir or base / "data/processed/tess/v0").resolve()
    output = Path(output_dir or base / "outputs/tess_baseline/seed42").resolve()
    source_run = _source_directory(base, source_run_dir)
    for protected in (base / "data/raw", base / "data/processed", prepared, source_run):
        protected = protected.resolve()
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError("Comparison output must be separate from source runs and prepared/raw inputs")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "comparison.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_locked(base, prepared, output, source_run, device)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True)
    parser.add_argument("--prepared_dir", type=Path)
    parser.add_argument("--output_dir", type=Path)
    parser.add_argument("--source_run_dir", type=Path)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    result = run_comparison(args.base_dir, args.prepared_dir, args.output_dir, args.source_run_dir, args.device)
    print(_json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
