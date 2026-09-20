# TESS candidate classification

Verified saved predictions on the same 335 test candidates (183 positive, 152 negative labels). These are individual seed-42 runs on the existing, previously consulted TESS benchmark.

| Model | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| frozen Kepler CNN v0 on TESS | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| TESS-trained CNN v0 | 0.7672 | 0.8020 | 0.8595 | 0.8401 |
| frozen Kepler transformer v0 on TESS | 0.5761 | 0.4701 | 0.7146 | 0.7121 |

[Full table and confusion counts](comparison.csv) · [Figure](figures/metrics.png) · [Report figure](figures/metrics.pdf) · [Preparation](preparation_summary.json) · [Protocols](protocols.json) · [Provenance](provenance.json)

Frozen Kepler models retain their source-training normalization, selected weights, and Kepler-validation thresholds. The TESS-trained CNN uses TESS training normalization and TESS validation for checkpoint/threshold selection. Threshold-based scores therefore describe different operating points. AP is scikit-learn average precision.

The inputs share v0 geometry and seven scalar definitions. TESS detrending, quality filtering, and companion masking differ from historical Kepler preprocessing. Model families also use different training recipes. These comparisons neither isolate mission effects nor establish performance across all TESS detections; no seed uncertainty is estimated.

Checkpoints, per-candidate predictions, and logs remain in local `outputs/`. This export verifies their checksums and reconstructs metrics without training or inference.

Reproduce into a new or empty directory from the repository root:

```bash
python scripts/analysis/export_tess_results.py \
  --cnn_dir outputs/tess_baseline/seed42 \
  --transformer_dir outputs/tess_transformer/seed42 \
  --output_dir outputs/published_tess_transfer
```
