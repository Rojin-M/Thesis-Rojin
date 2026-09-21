# Shared preprocessing transfer milestone

This frozen Phase 1 export reconstructs the saved seed-42 CNN metrics from per-candidate predictions. Both models use Kepler-only training and validation; the TESS rows use the same 335 labelled `shared_v1` test candidates (183 positive, 152 negative).

## TESS transfer

| Model | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| CNN v0 | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| CNN shared_v1 | 0.7194 | 0.7099 | 0.7991 | 0.7828 |

## Common Kepler test set

| Model | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| CNN v0 | 0.9098 | 0.8781 | 0.9239 | 0.9606 |
| CNN shared_v1 | 0.9011 | 0.8658 | 0.9422 | 0.9674 |

The shared preprocessing retained 5,385 of 5,518 Kepler candidates and all 2,208 TESS candidates. It kept the original split membership where candidates remained eligible. The 133 Kepler exclusions changed the source training and validation cohorts, so these comparisons do not isolate preprocessing as the sole cause.

The shared CNN improved Kepler AP but not TESS AP. These are single-seed results on previously consulted labelled benchmarks, not uncertainty estimates or evidence of a new planet discovery.

The original CNN evaluator changed after the first result was saved. The Phase 1 source bundle at commit `ef683a6` records the frozen-checkpoint replay; the current exporter reconstructs these metrics from the preserved predictions without training or inference.

[TESS table](tess_comparison.csv) · [Kepler table](kepler_common_comparison.csv) · [TESS figure](figures/tess_metrics.png) · [Kepler figure](figures/kepler_common_metrics.png) · [Preparation](preparation_summary.json) · [Protocol](protocols.json) · [Provenance](provenance.json)

Checkpoints and per-candidate predictions remain in ignored local `outputs/`. The exporter verifies their recorded hashes and reconstructs every metric without training or inference.

Reproduce into a new or empty directory from the repository root:

```bash
.venv/bin/python scripts/analysis/export_shared_transfer_results.py \
  --output_dir outputs/published_shared_transfer
```
