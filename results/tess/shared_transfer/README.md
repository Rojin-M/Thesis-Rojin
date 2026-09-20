# Shared preprocessing transfer milestone

This frozen Phase 1 export reconstructs the saved seed-42 CNN and transformer metrics from per-candidate predictions. All four models use Kepler-only training and validation; the TESS rows use the same 335 labelled `shared_v1` test candidates (183 positive, 152 negative).

## TESS transfer

| Model | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| CNN v0 | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| CNN shared_v1 | 0.7194 | 0.7099 | 0.7991 | 0.7828 |
| Transformer v0 | 0.5761 | 0.4701 | 0.7146 | 0.7121 |
| Transformer shared_v1 | 0.6776 | 0.6842 | 0.7395 | 0.7432 |

## Common Kepler test set

| Model | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| CNN v0 | 0.9098 | 0.8781 | 0.9239 | 0.9606 |
| CNN shared_v1 | 0.9011 | 0.8658 | 0.9422 | 0.9674 |
| Transformer v0 | 0.8739 | 0.8411 | 0.8911 | 0.9438 |
| Transformer shared_v1 | 0.8789 | 0.8488 | 0.9068 | 0.9509 |

The shared preprocessing retained 5,385 of 5,518 Kepler candidates and all 2,208 TESS candidates. It kept the original split membership where candidates remained eligible. The 133 Kepler exclusions changed the source training and validation cohorts, so these comparisons do not isolate preprocessing as the sole cause.

The shared CNN improved Kepler AP but not TESS AP. The shared transformer improved both in this run, but it remained below the shared CNN on TESS AP. These are single-seed results on previously consulted labelled benchmarks, not uncertainty estimates or evidence of a new planet discovery. CNN and transformer training recipes also differ.

The original CNN evaluator file changed after its result was saved. Phase 1 therefore repeated frozen-checkpoint inference with the current evaluator; its comparison and both prediction CSVs are byte-identical to the original. The hash audit is included below.

[TESS table](tess_comparison.csv) · [Kepler table](kepler_common_comparison.csv) · [TESS figure](figures/tess_metrics.png) · [Kepler figure](figures/kepler_common_metrics.png) · [Preparation](preparation_summary.json) · [Protocols](protocols.json) · [CNN reevaluation audit](cnn_reevaluation.json) · [Provenance](provenance.json)

Checkpoints and per-candidate predictions remain in ignored local `outputs/`. The exporter verifies their recorded hashes and reconstructs every metric without training or inference.

Reproduce into a new or empty directory from the repository root:

```bash
.venv/bin/python scripts/analysis/export_shared_transfer_results.py \
  --output_dir outputs/published_shared_transfer
```
