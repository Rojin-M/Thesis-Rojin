#!/usr/bin/env python3
"""Compare frozen Kepler v0 and shared_v1 transformers on matched test candidates."""
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
import torch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data.tess_dataset import fit_normalization
from scripts.experiments import evaluate_kepler_transformer_on_tess as previous
from scripts.experiments import run_tess_baseline as baseline
from training.transformer import train_kepler_transformer as trainer


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _run_directory(pointer_path: Path) -> Path:
    pointer = json.loads(pointer_path.read_text())
    if pointer.get("status") != "complete" or pointer.get("model") != "transformer":
        raise ValueError(f"Transformer run is not complete: {pointer_path}")
    saved = Path(pointer["run_dir"])
    relocated = pointer_path.parent / saved.name
    run = relocated if relocated.is_dir() else saved
    if not run.is_dir():
        raise FileNotFoundError(run)
    return run.resolve()


def _prepared(base: Path, mission: str, version: str) -> dict:
    directory = base / "data/processed" / mission / version
    prefix = f"{mission}_{version}"
    paths = {
        "dataset": directory / f"dataset_{prefix}.npz",
        "splits": directory / f"splits_{prefix}_seed42.npz",
        "manifest": directory / f"manifest_{prefix}.csv",
        "normalization": directory / "kepler_train_normalization.npz",
    }
    if mission == "kepler" and version == "v0":
        datasets = list(directory.glob("dataset_kepler_v0_*.npz"))
        if len(datasets) != 1:
            raise ValueError("Expected exactly one Kepler v0 dataset")
        paths["dataset"] = datasets[0]
        paths["normalization"] = base / "data/processed/tess/v0/kepler_train_normalization.npz"
    if version == "shared_v1":
        paths.update(summary=directory / "preparation_summary.json",
                     provenance=directory / "provenance.json")
        summary = json.loads(paths["summary"].read_text())
        if summary.get("status") != "complete":
            raise ValueError(f"Incomplete shared_v1 dataset: {directory}")
        for name, expected in summary["outputs"].items():
            if baseline._sha(directory / name) != expected:
                raise ValueError(f"Prepared artifact changed: {directory / name}")
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    with np.load(paths["dataset"], allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in (*baseline.INPUT_KEYS, "y")}
    splits = baseline._npz(paths["splits"])
    manifest = pd.read_csv(paths["manifest"], dtype={"candidate_id": str, "split_group": str})
    if not np.array_equal(arrays["y"], manifest.y.to_numpy()):
        raise ValueError(f"Dataset labels differ from manifest: {directory}")
    return {"arrays": arrays, "splits": splits, "manifest": manifest, "paths": paths}


def _source(run: Path, prepared: dict, version: str, device: torch.device) -> dict:
    cfg = trainer.TrainConfig(**json.loads((run / "config.json").read_text()))
    model_cfg = json.loads((run / "model_config.json").read_text())
    if (cfg.seed != 42 or cfg.prepare_version != version or cfg.use_input_norm or cfg.use_aux_branch
            or cfg.evaluate_test or cfg.use_amp or model_cfg.get("use_input_norm")
            or model_cfg.get("use_aux_branch") or model_cfg.get("aux_features") != 0):
        raise ValueError(f"Source is not the selected seed-42 float32 transformer: {run}")
    for key in ("d_model", "num_heads", "global_depth", "local_depth", "mlp_ratio", "dropout",
                "attention_dropout", "token_dropout", "scalar_dropout", "use_input_norm"):
        if model_cfg[key] != getattr(cfg, key):
            raise ValueError(f"Transformer model/config disagreement: {key}")
    if tuple(model_cfg[key] for key in ("global_seq_len", "local_seq_len", "scalar_features")) != (200, 100, 7):
        raise ValueError("Transformer geometry differs from the shared input schema")
    for key in ("dataset", "splits", "manifest"):
        configured = Path(getattr(cfg, key + "_path"))
        path = prepared["paths"][key]
        if configured.name != path.name or (configured.is_file() and baseline._sha(configured) != baseline._sha(path)):
            raise ValueError(f"Source {key} differs from its prepared version")
    checkpoint, summary = baseline._training_record(run, cfg, model_cfg)
    stats = baseline._npz(prepared["paths"]["normalization"])
    fitted = fit_normalization(prepared["arrays"], prepared["splits"]["train_idx"])
    if set(fitted) != set(stats) or any(not np.array_equal(fitted[key], stats[key]) for key in fitted):
        raise ValueError("Saved normalization differs from Kepler training rows")
    model = trainer.ExoFormer(**model_cfg).to(device)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    indices = prepared["splits"]["val_idx"]
    saved = pd.read_csv(run / "val_predictions.csv", dtype={"candidate_id": str})
    expected = prepared["manifest"].iloc[indices]
    if (not np.array_equal(saved.candidate_id.to_numpy(), expected.candidate_id.to_numpy())
            or not np.array_equal(saved.y.to_numpy(), expected.y.to_numpy())):
        raise ValueError("Source validation order or labels changed")
    replay = previous.predict(model, prepared["arrays"], indices, stats, cfg.batch_size, device)
    difference = np.max(np.abs(replay - saved.probability.to_numpy(dtype=np.float32)))
    if not np.allclose(replay, saved.probability.to_numpy(dtype=np.float32), rtol=1e-5, atol=1e-6):
        raise ValueError(f"Source validation replay differs from saved predictions: {difference}")
    return {"config": cfg, "model_config": model_cfg, "checkpoint": checkpoint, "summary": summary,
            "model": model, "stats": stats, "replay_error": float(difference), "validation_rows": len(indices)}


def _predictions(source: dict, prepared: dict, indices: np.ndarray, device: torch.device) -> pd.DataFrame:
    probabilities = previous.predict(source["model"], prepared["arrays"], indices,
                                     source["stats"], source["config"].batch_size, device)
    threshold = float(source["checkpoint"]["val_threshold"])
    frame = prepared["manifest"].iloc[indices].copy()
    frame["probability"] = probabilities
    frame["prediction"] = (probabilities >= threshold).astype(np.int64)
    return frame


def _score(frame: pd.DataFrame, threshold: float) -> dict:
    probabilities = frame.probability.to_numpy(dtype=np.float32)
    if (not np.isfinite(probabilities).all() or not np.isin(frame.y, [0, 1]).all()
            or not np.array_equal(frame.prediction.to_numpy(), (probabilities >= threshold).astype(np.int64))):
        raise ValueError("Predictions are invalid or differ from the source threshold")
    metrics = trainer.compute_metrics(frame.y.to_numpy(), probabilities, threshold)
    tn, fp, fn, tp = confusion_matrix(frame.y, frame.prediction, labels=[0, 1]).ravel()
    return {**metrics, "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def verify(output: Path) -> dict:
    output = output.resolve()
    completion = json.loads((output / "completion.json").read_text())
    protocol = json.loads((output / "protocol.json").read_text())
    if completion.get("status") != "complete":
        raise ValueError("Shared transformer transfer is incomplete")
    for name, expected in completion["artifacts"].items():
        if baseline._sha(output / name) != expected:
            raise ValueError(f"Saved result artifact changed: {name}")
    for name, expected in protocol["inputs"].items():
        if baseline._sha(Path(name)) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    for name, expected in protocol["code"].items():
        if baseline._sha(ROOT / name) != expected:
            raise ValueError(f"Evaluation code changed: {name}")
    for mission, table in (("tess", "tess_comparison.csv"), ("kepler", "kepler_common_comparison.csv")):
        comparison = pd.read_csv(output / table)
        for version in ("v0", "shared_v1"):
            frame = pd.read_csv(output / f"{mission}_{version}_predictions.csv", dtype={"candidate_id": str})
            row = comparison.loc[comparison.arm == version].iloc[0]
            metrics = _score(frame, float(row.threshold))
            if any(not np.isclose(metrics[key], row[key], rtol=0, atol=1e-12) for key in metrics):
                raise ValueError(f"Saved {mission} {version} metrics disagree with predictions")
    return {"status": "passed", "tess_test_candidates": 335, "kepler_common_test_candidates": 809}


def evaluate(base: Path, output: Path, device_name: str = "auto",
             shared_run_pointer: Path | None = None) -> dict:
    base, output = base.resolve(), output.resolve()
    if (output / "completion.json").is_file():
        return verify(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Evaluation output directory must be new or empty")
    status = json.loads((base / "outputs/shared_preparation/shared_v1/full_status.json").read_text())
    verification = json.loads((base / "outputs/shared_preparation/shared_v1/full_verification.json").read_text())
    if status.get("status") != "complete" or verification.get("status") != "verified":
        raise ValueError("Both shared_v1 datasets must be verified before model evaluation")
    previous.verify(base / "outputs/tess_transformer/seed42")
    selection = json.loads((base / "outputs/reproduce/transformer/selection.json").read_text())
    if selection.get("selected_variant") != "bypass_input_norm":
        raise ValueError("V0 transformer selection differs from the completed study")
    old_runs = list((base / "outputs/reproduce/transformer/bypass_input_norm/seed_42").glob("*/best_model.pt"))
    if len(old_runs) != 1:
        raise ValueError("Expected one selected seed-42 v0 transformer checkpoint")
    runs = {
        "v0": old_runs[0].parent,
        "shared_v1": _run_directory(shared_run_pointer or base / "outputs/shared_transformer/kepler/run.json"),
    }
    prepared = {arm: _prepared(base, "kepler", arm) for arm in runs}
    target = _prepared(base, "tess", "shared_v1")
    if len(target["splits"]["test_idx"]) != 335:
        raise ValueError("TESS test split differs from the fixed benchmark")
    device = trainer.detect_device(device_name)
    trainer.set_seed(42)
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("high")
    sources = {arm: _source(runs[arm], prepared[arm], arm, device) for arm in runs}
    excluded = {"base_dir", "dataset_path", "splits_path", "manifest_path", "output_root",
                "prepare_version", "device"}
    recipes = [{key: value for key, value in asdict(sources[arm]["config"]).items() if key not in excluded}
               for arm in runs]
    if recipes[0] != recipes[1]:
        raise ValueError("Transformer training recipes differ between v0 and shared_v1")

    shared_indices = prepared["shared_v1"]["splits"]["test_idx"]
    common_ids = prepared["shared_v1"]["manifest"].iloc[shared_indices].candidate_id.to_numpy()
    old_test_indices = prepared["v0"]["splits"]["test_idx"]
    old_test_ids = prepared["v0"]["manifest"].iloc[old_test_indices].candidate_id.to_numpy()
    positions = pd.Index(old_test_ids).get_indexer(common_ids)
    if len(common_ids) != 809 or (positions < 0).any():
        raise ValueError("Shared Kepler test candidates differ from the original fixed test split")
    old_common_indices = old_test_indices[positions]
    if not np.array_equal(prepared["v0"]["arrays"]["y"][old_common_indices],
                          prepared["shared_v1"]["arrays"]["y"][shared_indices]):
        raise ValueError("Kepler common test labels differ between prepared versions")
    target_indices = target["splits"]["test_idx"]
    inputs = [base / "outputs/reproduce/transformer/selection.json",
              base / "outputs/tess_transformer/seed42/completion.json"]
    for item in (*prepared.values(), target):
        inputs += list(item["paths"].values())
    for arm in runs:
        inputs += [runs[arm] / name for name in baseline.RUN_FILES]
    inputs += [runs["v0"] / "test_predictions.csv"]
    input_hashes = {str(path.resolve()): baseline._sha(path) for path in inputs}
    code_paths = [Path(__file__).resolve(), ROOT / "scripts/experiments/evaluate_kepler_transformer_on_tess.py",
                  ROOT / "scripts/experiments/run_tess_baseline.py", ROOT / "training/transformer/train_kepler_transformer.py",
                  ROOT / "training/cnn/train_kepler_cnn.py", ROOT / "scripts/data/tess_dataset.py"]
    output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "seed": 42,
        "selection": "Frozen bypass-input-norm transformer; checkpoint by Kepler validation AP; threshold by Kepler validation F1",
        "normalization": "Each source uses only its own Kepler training moments; no TESS fitting or tuning",
        "recipe": recipes[0],
        "replay": {arm: {"rows": sources[arm]["validation_rows"],
                         "maximum_probability_difference": sources[arm]["replay_error"]} for arm in runs},
        "kepler_common_candidates_sha256": hashlib.sha256(json.dumps(common_ids.tolist()).encode()).hexdigest(),
        "tess_test_candidates_sha256": hashlib.sha256(json.dumps(
            target["manifest"].iloc[target_indices].candidate_id.tolist()).encode()).hexdigest(),
        "inputs": input_hashes,
        "code": {str(path.relative_to(ROOT)): baseline._sha(path) for path in code_paths},
        "test_status": "Previously consulted Kepler and TESS benchmarks; one seed; source cohorts differ",
    }
    _write_json(output / "protocol.json", protocol)

    for mission, indices in (("kepler", {"v0": old_common_indices, "shared_v1": shared_indices}),
                             ("tess", {arm: target_indices for arm in runs})):
        records = []
        for arm in runs:
            candidate_set = prepared[arm] if mission == "kepler" else target
            frame = _predictions(sources[arm], candidate_set, indices[arm], device)
            threshold = float(sources[arm]["checkpoint"]["val_threshold"])
            if mission == "tess":
                baseline._checked_predictions(frame, target["manifest"], target_indices, threshold)
            elif not np.array_equal(frame.candidate_id.to_numpy(), common_ids):
                raise ValueError("Kepler common prediction identities changed")
            if mission == "kepler" and arm == "v0":
                saved = pd.read_csv(runs["v0"] / "test_predictions.csv", dtype={"candidate_id": str})
                old_saved = saved.set_index("candidate_id").loc[common_ids]
                if not np.allclose(frame.probability.to_numpy(dtype=np.float32),
                                   old_saved.probability.to_numpy(dtype=np.float32), rtol=1e-5, atol=1e-6):
                    raise ValueError("V0 Kepler test replay differs from saved deferred evaluation")
            frame.to_csv(output / f"{mission}_{arm}_predictions.csv", index=False)
            records.append({"arm": arm, "threshold": threshold,
                            "best_epoch": int(sources[arm]["checkpoint"]["epoch"]),
                            "test_size": len(frame), **_score(frame, threshold)})
        pd.DataFrame(records).to_csv(output / (
            "kepler_common_comparison.csv" if mission == "kepler" else "tess_comparison.csv"), index=False)
    for name, expected in input_hashes.items():
        if baseline._sha(Path(name)) != expected:
            raise ValueError(f"Frozen input changed during inference: {name}")
    for name, expected in protocol["code"].items():
        if baseline._sha(ROOT / name) != expected:
            raise ValueError(f"Evaluation code changed during inference: {name}")
    artifacts = {name: baseline._sha(output / name) for name in (
        "protocol.json", "kepler_common_comparison.csv", "tess_comparison.csv",
        "kepler_v0_predictions.csv", "kepler_shared_v1_predictions.csv",
        "tess_v0_predictions.csv", "tess_shared_v1_predictions.csv")}
    _write_json(output / "completion.json", {"status": "complete",
                                             "finished_utc": datetime.now(timezone.utc).isoformat(),
                                             "artifacts": artifacts})
    return verify(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, default=ROOT)
    parser.add_argument("--output_dir", type=Path, default=ROOT / "outputs/shared_transformer/tess_transfer")
    parser.add_argument("--shared_run_pointer", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--verify_only", action="store_true")
    args = parser.parse_args()
    result = verify(args.output_dir) if args.verify_only else evaluate(
        args.base_dir, args.output_dir, args.device, args.shared_run_pointer)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
