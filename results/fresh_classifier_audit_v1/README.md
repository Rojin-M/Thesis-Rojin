# Fresh labelled classifier audit

295 candidates were registered before inference; 14 passed archive and unchanged preprocessing rules.
Class counts: 3 positive and 11 negative.
The existing model weights, blend, normalization and calibration temperature were reused without fitting.

| Model | AP | ROC AUC | Brier | Accuracy at 0.5 |
| --- | ---: | ---: | ---: | ---: |
| crossfit_supermodel | 0.8333 | 0.9091 | 0.1067 | 0.9286 |
| v4_static | 1.0000 | 1.0000 | 0.1351 | 0.8571 |
| tess_only | 0.6984 | 0.8485 | 0.1391 | 0.7857 |
| kepler_only | 0.2714 | 0.4848 | 0.3114 | 0.5714 |
| fine_tuned | 0.6984 | 0.8485 | 0.1510 | 0.7857 |
| pooled | 0.3778 | 0.6667 | 0.1718 | 0.7143 |
| dann | 0.3889 | 0.6970 | 0.1754 | 0.7143 |
| transformer | 0.7917 | 0.8485 | 0.1737 | 0.8571 |
| transit_morphology | 0.9167 | 0.9697 | 0.1212 | 0.8571 |
| stellar_variability | 0.8667 | 0.9394 | 0.1369 | 0.7857 |
| tls | 0.5167 | 0.6061 | 0.1831 | 0.7143 |
| aperture_photometry | 0.1870 | 0.2424 | 0.2472 | 0.7143 |
| difference_image | 0.6389 | 0.6970 | 0.2128 | 0.7143 |

The supermodel uses its frozen calibration temperature. Comparator Brier values use raw logits; AP/AUC do not depend on temperature.
Every acquisition or preprocessing exclusion is retained in preparation.json. The small class counts limit conclusions; this is an independent check, not a large confirmation study.

Paired AP uncertainty and all individual predictions are retained alongside this report. No model was selected on this audit and nothing was deployed.

The frozen static v4 stack has AP 1.0000, compared with 0.8333 for the nonlinear supermodel on this small cohort. The reused-audit nonlinear ranking advantage therefore did not repeat here.

Per-candidate predictions are preserved in [predictions.csv](predictions.csv).
Full acquisition and preprocessing accounting remains in local ignored outputs;
`evidence.json` records the source artifact checksums.
