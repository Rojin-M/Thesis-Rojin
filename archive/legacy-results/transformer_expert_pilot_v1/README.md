# Dual-view Transformer expert pilot

A compact Transformer independently encodes the normalized 200-bin global and
100-bin local light-curve views, joins them with the seven scalar features, and
outputs a candidate-classification logit. It was trained on TESS training groups
for the same bounded 120-update budget used by the existing comparison arms.

| Seed | Selected update | Selection AP | Audit AP | Audit ROC AUC | Calibrated Brier |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 311 | 120 | 0.7164 | 0.7390 | 0.6782 | 0.2373 |
| 313 | 120 | 0.7288 | 0.7619 | 0.6752 | 0.2409 |
| 317 | 120 | 0.6835 | 0.7273 | 0.6836 | 0.2305 |

Mean per-seed audit AP was **0.7428**. Averaging the three seed logits produced
audit AP **0.7368**. This is stronger than the earlier learned-static fusion AP
of 0.7263 on the same validation-derived audit, but the audit was previously
consulted and therefore cannot establish a new final result.

The original TESS test partition was not evaluated. The run is a short CPU
pilot without a convergence claim and is not deployed to the watcher.
