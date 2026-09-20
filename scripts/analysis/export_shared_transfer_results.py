#!/usr/bin/env python3
"""Verify and export the frozen shared_v1 CNN and transformer comparisons."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from scripts.analysis.export_results import Publication, sha256
from training.cnn.train_kepler_cnn import compute_metrics


METRIC_COLUMNS = ("accuracy", "precision", "recall", "f1", "pr_auc", "roc_auc")


def _verify_artifacts(publication: Publication, directory: Path, values: dict[str, str]) -> None:
    directory = directory.resolve()
    for name, expected in values.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or sha256(publication.remember(path)) != expected:
            raise ValueError(f"Saved result artifact changed: {path}")


def _score(frame: pd.DataFrame, threshold: float) -> dict[str, float | int]:
    probabilities = frame.probability.to_numpy(dtype=np.float32)
    labels = frame.y.to_numpy(dtype=np.int64)
    predictions = (probabilities >= threshold).astype(np.int64)
    if (not np.isfinite(probabilities).all() or not np.isin(labels, (0, 1)).all()
            or not np.array_equal(frame.prediction.to_numpy(dtype=np.int64), predictions)):
        raise ValueError("Saved predictions are invalid or differ from the frozen threshold")
    metrics = compute_metrics(labels, probabilities, threshold)
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {**metrics, "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def _checked_comparison(publication: Publication, directory: Path, table_name: str,
                        prediction_names: dict[str, str]) -> pd.DataFrame:
    comparison = pd.read_csv(publication.remember(directory / table_name))
    if set(comparison.arm) != set(prediction_names):
        raise ValueError(f"Unexpected comparison arms in {directory / table_name}")
    for arm, prediction_name in prediction_names.items():
        frame = pd.read_csv(publication.remember(directory / prediction_name),
                            dtype={"candidate_id": str})
        row = comparison.loc[comparison.arm == arm].iloc[0]
        metrics = _score(frame, float(row.threshold))
        for key, value in metrics.items():
            np.testing.assert_allclose(row[key], value, rtol=0, atol=1e-12)
        if int(row.test_size) != len(frame):
            raise ValueError(f"Saved test size disagrees with {prediction_name}")
    return comparison


def _verify_preparation(publication: Publication, processed: Path,
                        status_path: Path, verification_path: Path) -> dict:
    status = publication.read_json(status_path)
    verification = publication.read_json(verification_path)
    if status.get("status") != "complete" or verification.get("status") != "verified":
        raise ValueError("The full shared_v1 preparation is not complete and verified")
    summaries = {}
    for mission in ("kepler", "tess"):
        directory = processed / mission / "shared_v1"
        summary = publication.read_json(directory / "preparation_summary.json")
        if summary.get("status") != "complete" or summary.get("mission") != mission:
            raise ValueError(f"Invalid shared_v1 {mission} preparation summary")
        _verify_artifacts(publication, directory, summary["outputs"])
        if summary["retained_candidates"] != verification["missions"][mission]["retained_candidates"]:
            raise ValueError(f"The {mission} summary and full verification disagree")
        summaries[mission] = summary
    return {"status": status, "verification": verification, "missions": summaries}


def _protocol(publication: Publication, directory: Path, *, inputs_in_completion: bool) -> dict:
    completion = publication.read_json(directory / "completion.json")
    protocol = publication.read_json(directory / "protocol.json")
    if completion.get("status") != "complete":
        raise ValueError(f"Incomplete comparison: {directory}")
    _verify_artifacts(publication, directory, completion["artifacts"])
    publication.verify_hashes(completion["inputs"] if inputs_in_completion else protocol["inputs"])
    publication.verify_hashes(protocol["code"])
    return {"completion": completion, "protocol": protocol}


def _cnn_reevaluation_audit(publication: Publication, prior: Path, current: Path,
                            current_evidence: dict) -> dict:
    completion = publication.read_json(prior / "completion.json")
    protocol = publication.read_json(prior / "protocol.json")
    if completion.get("status") != "complete":
        raise ValueError("The original CNN comparison is incomplete")
    _verify_artifacts(publication, prior, completion["artifacts"])
    publication.verify_hashes(completion["inputs"])
    changed = "scripts/experiments/evaluate_shared_cnn_transfer.py"
    for name, expected in protocol["code"].items():
        if name == changed:
            continue
        if sha256(publication.remember(ROOT / name)) != expected:
            raise ValueError(f"Original CNN dependency changed: {name}")
    current_hash = sha256(ROOT / changed)
    if protocol["code"].get(changed) == current_hash:
        raise ValueError("Expected the recorded CNN evaluator drift to be present")
    if current_evidence["protocol"]["code"].get(changed) != current_hash:
        raise ValueError("The Phase 1 CNN reevaluation does not record the current evaluator")
    matched = {}
    for name in ("comparison.csv", "v0_predictions.csv", "shared_v1_predictions.csv"):
        prior_hash = sha256(prior / name)
        current_hash_for_artifact = sha256(current / name)
        if prior_hash != current_hash_for_artifact:
            raise ValueError(f"Phase 1 CNN reevaluation changed predictions or metrics: {name}")
        matched[name] = prior_hash
    return {
        "status": "passed",
        "reason": "The evaluator source changed after the original result was written, so Phase 1 repeated inference with the frozen checkpoints and current code.",
        "changed_code_file": changed,
        "original_recorded_sha256": protocol["code"][changed],
        "phase1_sha256": current_hash,
        "byte_identical_artifacts": matched,
    }


def _rows(comparison: pd.DataFrame, family: str) -> list[dict]:
    records = []
    for _, row in comparison.iterrows():
        records.append({
            "model_family": family,
            "arm": row.arm,
            "model": f"{family} {row.arm}",
            "seed": 42,
            "test_size": int(row.test_size),
            "threshold": float(row.threshold),
            "threshold_fit_split": "Kepler validation",
            "best_epoch": int(row.best_epoch),
            **{f"test_{key}": row[key] for key in METRIC_COLUMNS},
            **{key: int(row[key]) for key in ("tn", "fp", "fn", "tp")},
        })
    return records


def _cnn_kepler_comparison(publication: Publication, protocol: dict) -> tuple[pd.DataFrame, list[str]]:
    sources = {}
    for value in protocol["inputs"]:
        path = Path(value)
        if path.name != "test_predictions.csv":
            continue
        if "outputs/reproduce/cnn_baseline/" in value:
            sources["v0"] = path
        elif "outputs/shared_cnn/kepler/" in value:
            sources["shared_v1"] = path
    if set(sources) != {"v0", "shared_v1"}:
        raise ValueError("Could not identify both CNN source prediction files")

    shared = pd.read_csv(publication.remember(sources["shared_v1"]), dtype={"candidate_id": str})
    old = pd.read_csv(publication.remember(sources["v0"]), dtype={"candidate_id": str})
    if shared.candidate_id.duplicated().any() or old.candidate_id.duplicated().any():
        raise ValueError("CNN source predictions contain duplicate candidate IDs")
    old = old.set_index("candidate_id").reindex(shared.candidate_id).reset_index()
    if old.probability.isna().any() or not np.array_equal(old.y.to_numpy(), shared.y.to_numpy()):
        raise ValueError("CNN source predictions do not contain the same 809 labelled candidates")

    records = []
    for arm, frame in (("v0", old), ("shared_v1", shared)):
        summary = publication.read_json(sources[arm].parent / "summary.json")
        threshold = float(summary["best_threshold"])
        metrics = _score(frame, threshold)
        records.append({"arm": arm, "threshold": threshold,
                        "best_epoch": int(summary["best_epoch"]), "test_size": len(frame), **metrics})
    comparison = pd.DataFrame(records)
    if len(shared) != 809:
        raise ValueError("Expected 809 common Kepler candidates")
    return comparison, shared.candidate_id.tolist()


def _table(lines: list[str], rows: list[dict]) -> None:
    lines += ["| Model | Accuracy | F1 | AP | ROC-AUC |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append("| " + row["model"] + " | " + " | ".join(
            f"{row['test_' + metric]:.4f}" for metric in ("accuracy", "f1", "pr_auc", "roc_auc")) + " |")


def export(processed: Path, preparation_output: Path, cnn: Path, cnn_prior: Path,
           transformer: Path, destination: Path) -> dict:
    processed, preparation_output, cnn, cnn_prior, transformer, destination = (
        path.resolve() for path in (
            processed, preparation_output, cnn, cnn_prior, transformer, destination))
    for source in (processed, preparation_output, cnn, cnn_prior, transformer):
        if destination == source or destination in source.parents or source in destination.parents:
            raise ValueError("Export destination must be separate from input artifacts")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export destination must be new or empty")

    publication = Publication(ROOT / "outputs", destination)
    preparation = _verify_preparation(
        publication, processed, preparation_output / "full_status.json",
        preparation_output / "full_verification.json")
    cnn_evidence = _protocol(publication, cnn, inputs_in_completion=True)
    transformer_evidence = _protocol(publication, transformer, inputs_in_completion=False)
    reevaluation = _cnn_reevaluation_audit(publication, cnn_prior, cnn, cnn_evidence)

    cnn_tess = _checked_comparison(
        publication, cnn, "comparison.csv",
        {"v0": "v0_predictions.csv", "shared_v1": "shared_v1_predictions.csv"})
    transformer_tess = _checked_comparison(
        publication, transformer, "tess_comparison.csv",
        {"v0": "tess_v0_predictions.csv", "shared_v1": "tess_shared_v1_predictions.csv"})
    transformer_kepler = _checked_comparison(
        publication, transformer, "kepler_common_comparison.csv",
        {"v0": "kepler_v0_predictions.csv", "shared_v1": "kepler_shared_v1_predictions.csv"})
    cnn_kepler, common_ids = _cnn_kepler_comparison(publication, cnn_evidence["protocol"])
    transformer_ids = pd.read_csv(
        transformer / "kepler_shared_v1_predictions.csv", dtype={"candidate_id": str}).candidate_id.tolist()
    if transformer_ids != common_ids:
        raise ValueError("CNN and transformer Kepler comparisons use different candidate identities")

    tess_rows = _rows(cnn_tess, "CNN") + _rows(transformer_tess, "Transformer")
    kepler_rows = _rows(cnn_kepler, "CNN") + _rows(transformer_kepler, "Transformer")
    tess_table, kepler_table = pd.DataFrame(tess_rows), pd.DataFrame(kepler_rows)
    publication.write_csv("tess_comparison.csv", tess_table)
    publication.write_csv("kepler_common_comparison.csv", kepler_table)
    publication.write_json("preparation_summary.json", preparation)
    publication.write_json("protocols.json", {
        "cnn": cnn_evidence["protocol"],
        "transformer": transformer_evidence["protocol"],
    })
    publication.write_json("cnn_reevaluation.json", reevaluation)
    previous_source_date = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = "0"
    try:
        publication.small_plot(tess_table, "Kepler-trained models on the fixed TESS test set",
                               "figures/tess_metrics")
        publication.small_plot(kepler_table, "Models on 809 common Kepler test candidates",
                               "figures/kepler_common_metrics")
    finally:
        if previous_source_date is None:
            os.environ.pop("SOURCE_DATE_EPOCH")
        else:
            os.environ["SOURCE_DATE_EPOCH"] = previous_source_date

    lines = [
        "# Shared preprocessing transfer milestone", "",
        "This frozen Phase 1 export reconstructs the saved seed-42 CNN and transformer metrics from "
        "per-candidate predictions. All four models use Kepler-only training and validation; the TESS "
        "rows use the same 335 labelled `shared_v1` test candidates (183 positive, 152 negative).", "",
        "## TESS transfer", "",
    ]
    _table(lines, tess_rows)
    lines += ["", "## Common Kepler test set", ""]
    _table(lines, kepler_rows)
    lines += [
        "",
        "The shared preprocessing retained 5,385 of 5,518 Kepler candidates and all 2,208 TESS "
        "candidates. It kept the original split membership where candidates remained eligible. "
        "The 133 Kepler exclusions changed the source training and validation cohorts, so these "
        "comparisons do not isolate preprocessing as the sole cause.", "",
        "The shared CNN improved Kepler AP but not TESS AP. The shared transformer improved both in "
        "this run, but it remained below the shared CNN on TESS AP. These are single-seed results on "
        "previously consulted labelled benchmarks, not uncertainty estimates or evidence of a new "
        "planet discovery. CNN and transformer training recipes also differ.", "",
        "The original CNN evaluator file changed after its result was saved. Phase 1 therefore "
        "repeated frozen-checkpoint inference with the current evaluator; its comparison and both "
        "prediction CSVs are byte-identical to the original. The hash audit is included below.", "",
        "[TESS table](tess_comparison.csv) · [Kepler table](kepler_common_comparison.csv) · "
        "[TESS figure](figures/tess_metrics.png) · "
        "[Kepler figure](figures/kepler_common_metrics.png) · "
        "[Preparation](preparation_summary.json) · [Protocols](protocols.json) · "
        "[CNN reevaluation audit](cnn_reevaluation.json) · [Provenance](provenance.json)", "",
        "Checkpoints and per-candidate predictions remain in ignored local `outputs/`. The exporter "
        "verifies their recorded hashes and reconstructs every metric without training or inference.", "",
        "Reproduce into a new or empty directory from the repository root:", "", "```bash",
        ".venv/bin/python scripts/analysis/export_shared_transfer_results.py \\",
        "  --output_dir outputs/published_shared_transfer", "```",
    ]
    publication.write("README.md", "\n".join(lines))
    publication.remember(Path(__file__))
    publication.remember(ROOT / "scripts/analysis/export_results.py")
    publication.remember(ROOT / "training/cnn/train_kepler_cnn.py")
    provenance = {
        "status": "passed",
        "metrics_reconstructed": True,
        "seed": 42,
        "kepler_common_candidates": 809,
        "tess_test_candidates": 335,
        "source_sha256": publication.sources,
        "export_sha256": {
            str(path.relative_to(destination)): sha256(path)
            for path in sorted(destination.rglob("*")) if path.is_file()
        },
        "limitations": [
            "Both labelled benchmark test sets were previously consulted.",
            "Only seed 42 is included; no seed uncertainty is estimated.",
            "The shared preprocessing excludes 133 Kepler candidates, changing source cohorts.",
            "Cross-family CNN and transformer comparisons use different training recipes.",
        ],
    }
    publication.write_json("provenance.json", provenance)
    return {"status": "passed", "models": len(tess_rows), "output_dir": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed_dir", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--preparation_output", type=Path,
                        default=ROOT / "outputs/shared_preparation/shared_v1")
    parser.add_argument("--cnn_dir", type=Path,
                        default=ROOT / "outputs/shared_cnn/tess_transfer_phase1")
    parser.add_argument("--cnn_prior_dir", type=Path,
                        default=ROOT / "outputs/shared_cnn/tess_transfer")
    parser.add_argument("--transformer_dir", type=Path,
                        default=ROOT / "outputs/shared_transformer/tess_transfer")
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.processed_dir, args.preparation_output, args.cnn_dir,
                            args.cnn_prior_dir, args.transformer_dir, args.output_dir), indent=2))
