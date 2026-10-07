# Diagnostic-conditioned supermodel v5

A low-capacity gate adjusts v4's global expert prior per candidate using expert behavior, cross-expert disagreement, TLS, aperture, difference-image and ephemeris diagnostics.

| Method | AP | ROC AUC | Brier | Accuracy |
| --- | ---: | ---: | ---: | ---: |
| stellar variability | 0.8631 | 0.8194 | 0.1774 | 0.7805 |
| v4 static stack | 0.8613 | 0.8086 | 0.1806 | 0.7073 |
| v4 static stack calibrated | 0.8613 | 0.8086 | 0.1805 | 0.7073 |
| diagnostic router | 0.8580 | 0.8032 | 0.1805 | 0.6951 |
| diagnostic router calibrated | 0.8580 | 0.8032 | 0.1806 | 0.6951 |

## Frozen selection

Calibration selected shrinkage **0.35**, prior KL **0.25**, and temperature **0.8278**.
A dynamic gate was selected: **True**.
It beat the static stack and strongest single expert on both declared metrics: **False**.

## Boundaries

- The audit is validation-derived and was consulted by earlier experiments
- The small calibration split can select a noisy routing configuration
- Physical experts use known catalog ephemerides for these labelled examples
- A frozen prospective host-disjoint cohort is required for a paper-level claim
