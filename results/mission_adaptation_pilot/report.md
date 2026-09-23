# Bounded mission-adaptation pilot

Known-ephemeris classification on validation-derived audit groups.
No original test evaluation, deployment, survey-readiness or novelty claim.

| Arm | Seeds | TESS audit AP (mean ± seed SD) | Raw Brier | Calibrated Brier |
| --- | --- | --- | --- | --- |
| tess_only | 3 | 0.7474 ± 0.0131 | 0.2260 | 0.2190 |
| kepler_only | 3 | 0.5588 ± 0.0315 | 0.3631 | 0.3404 |
| fine_tuned | 3 | 0.7644 ± 0.0180 | 0.2132 | 0.2132 |
| pooled | 3 | 0.7067 ± 0.0124 | 0.2545 | 0.2456 |
| dann | 3 | 0.6934 ± 0.0003 | 0.2753 | 0.2507 |

Each arm: 120 updates × 32 examples; seeds [42, 43, 44]. Fine-tuning includes pretraining in that total.

Calibration and threshold outcomes, actual row identities, parameter counts, model hashes, histories, and paired group-bootstrap intervals are recorded in summary.json and per-arm outputs.

- Known catalog ephemerides; not blind recovery
- Short budgets; no convergence claim
- Validation-derived audit; previously consulted benchmark is not an untouched test
- TESS-only weights share frozen Kepler TRAIN normalization
- Kepler-only selects and calibrates on Kepler; other arms on TESS
- Empirical labelled-negative FPR is not survey false-alarm calibration
- DANN uses both missions' labels; no unsupervised-adaptation claim
- Mission head accuracy alone does not prove invariant representations
- Calibrated scores are not planet confirmation probabilities
