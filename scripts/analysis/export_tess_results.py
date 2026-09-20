#!/usr/bin/env python3
"""Verify saved TESS predictions and export compact tables, provenance, and figures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from scripts.analysis.export_results import Publication
from scripts.data.check_tess_prepared import check_prepared
from scripts.experiments.run_tess_baseline import _checked_predictions, _npz, _sha, _verify_files


def export(prepared: Path, cnn: Path, destination: Path, transformer: Path | None = None) -> dict:
    prepared, cnn, destination = (p.resolve() for p in (prepared, cnn, destination))
    if transformer is not None:
        transformer = transformer.resolve()
    for protected in (prepared, cnn, transformer, ROOT / "data", ROOT / "outputs/reproduce"):
        if protected is not None and (destination == protected or destination in protected.parents
                                      or protected in destination.parents):
            raise ValueError("Export destination must be separate from input artifacts")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export destination must be new or empty")
    check_prepared(prepared)
    publication = Publication(ROOT / "outputs", destination)
    summary = publication.read_json(prepared / "preparation_summary.json")
    publication.remember(prepared / "provenance.json")
    publication.remember(prepared / "dataset_tess_v0.npz")
    manifest = pd.read_csv(publication.remember(prepared / "manifest_tess_v0.csv"),
                           dtype={"candidate_id": str})
    split_path = publication.remember(prepared / "splits_tess_v0_seed42.npz")
    indices = _npz(split_path)["test_idx"]
    rows = []
    protocols = {}
    for directory in (cnn, transformer):
        if directory is None:
            continue
        completion = publication.read_json(directory / "completion.json")
        protocol = publication.read_json(directory / "protocol.json")
        if completion.get("status") != "complete" or completion["protocol_signature"] != protocol["signature"]:
            raise ValueError("Evaluation is incomplete or does not match its protocol")
        _verify_files(directory, completion["artifacts"])
        for name in completion["artifacts"]:
            publication.remember(directory / name)
        if protocol["prepared"]["outputs"] != summary["outputs"]:
            raise ValueError("Evaluations used different prepared TESS artifacts")
        protocols["cnn" if directory == cnn else "transformer"] = protocol
        for arm, record in completion["arms"].items():
            frame = pd.read_csv(directory / f"{arm}_predictions.csv", dtype={"candidate_id": str})
            metrics = _checked_predictions(frame, manifest, indices, record["threshold"])
            for key, value in metrics.items():
                np.testing.assert_allclose(value, record["metrics"][key], rtol=0, atol=1e-12)
            if record["test_size"] != len(indices):
                raise ValueError("Recorded test size does not match the common split")
            tn, fp, fn, tp = confusion_matrix(frame.y, frame.prediction, labels=[0, 1]).ravel()
            rows.append({"model": record["name"], "seed": 42, "test_size": len(indices),
                         "threshold": record["threshold"], "threshold_fit_split": record["threshold_fit_split"],
                         "best_epoch": record["best_epoch"],
                         **{"test_" + key: value for key, value in metrics.items()},
                         "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)})
    table = pd.DataFrame(rows)
    publication.write_csv("comparison.csv", table)
    publication.write_json("preparation_summary.json", summary)
    publication.write_json("protocols.json", protocols)
    publication.small_plot(table, "Single-seed classification on the fixed TESS test set", "figures/metrics")
    lines = ["# TESS candidate classification", "",
             "Verified saved predictions on the same 335 test candidates (183 positive, 152 negative labels). "
             "These are individual seed-42 runs on the existing, previously consulted TESS benchmark.", "",
             "| Model | Accuracy | F1 | AP | ROC-AUC |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append("| " + row["model"] + " | " + " | ".join(
            f"{row['test_' + metric]:.4f}" for metric in ("accuracy", "f1", "pr_auc", "roc_auc")) + " |")
    lines += ["", "[Full table and confusion counts](comparison.csv) · [Figure](figures/metrics.png) · "
              "[Report figure](figures/metrics.pdf) · [Preparation](preparation_summary.json) · "
              "[Protocols](protocols.json) · [Provenance](provenance.json)", "",
              "Frozen Kepler models retain their source-training normalization, selected weights, and "
              "Kepler-validation thresholds. The TESS-trained CNN uses TESS training normalization and "
              "TESS validation for checkpoint/threshold selection. Threshold-based scores therefore describe "
              "different operating points. AP is scikit-learn average precision.", "",
              "The inputs share v0 geometry and seven scalar definitions. TESS detrending, quality filtering, "
              "and companion masking differ from historical Kepler preprocessing. Model families also use "
              "different training recipes. These comparisons neither isolate mission effects nor establish "
              "performance across all TESS detections; no seed uncertainty is estimated.", "",
              "Checkpoints, per-candidate predictions, and logs remain in local `outputs/`. "
              "This export verifies their checksums and reconstructs metrics without training or inference.", "",
              "Reproduce into a new or empty directory from the repository root:", "", "```bash",
              "python scripts/analysis/export_tess_results.py \\",
              f"  --cnn_dir {publication.portable(str(cnn))} \\"]
    if transformer is not None:
        lines.append(f"  --transformer_dir {publication.portable(str(transformer))} \\")
    lines += [f"  --output_dir outputs/published_{'tess_transfer' if transformer else 'tess_cnn'}", "```"]
    publication.write("README.md", "\n".join(lines))
    publication.remember(Path(__file__))
    publication.remember(ROOT / "scripts/analysis/export_results.py")
    publication.remember(ROOT / "scripts/experiments/run_tess_baseline.py")
    record = {"status": "passed", "metrics_reconstructed": True, "test_candidates": len(indices),
              "source_sha256": publication.sources,
              "export_sha256": {str(path.relative_to(destination)): _sha(path)
                                for path in sorted(destination.rglob("*")) if path.is_file()}}
    publication.write_json("provenance.json", record)
    return {"status": "passed", "models": len(rows), "output_dir": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared_dir", type=Path, default=ROOT / "data/processed/tess/v0")
    parser.add_argument("--cnn_dir", type=Path, default=ROOT / "outputs/tess_baseline/seed42")
    parser.add_argument("--transformer_dir", type=Path)
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.prepared_dir, args.cnn_dir, args.output_dir, args.transformer_dir), indent=2))
