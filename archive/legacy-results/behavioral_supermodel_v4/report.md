# Behavioral supermodel v4

Eleven experts include CNN/DANN regimes, a Transformer, two light-curve diagnostics, TLS, aperture photometry and difference-image localization.

| Method | AP | ROC AUC | Brier | Available |
| --- | ---: | ---: | ---: | ---: |
| tess only | 0.7489 | 0.7117 | 0.2158 | 82 |
| kepler only | 0.5619 | 0.4946 | 0.3376 | 82 |
| fine tuned | 0.7921 | 0.7512 | 0.2044 | 82 |
| pooled | 0.7154 | 0.6507 | 0.2502 | 82 |
| dann | 0.7019 | 0.6292 | 0.2725 | 82 |
| transformer | 0.7368 | 0.6776 | 0.2295 | 82 |
| transit morphology | 0.8071 | 0.7428 | 0.2063 | 82 |
| stellar variability | 0.8631 | 0.8194 | 0.1774 | 82 |
| tls | 0.7760 | 0.7039 | 0.2246 | 82 |
| aperture photometry | 0.7451 | 0.6639 | 0.2252 | 82 |
| difference image | 0.6991 | 0.6316 | 0.2359 | 82 |
| available uniform mean | 0.8193 | 0.7560 | 0.2011 | 82 |
| convex stack | 0.8613 | 0.8086 | 0.1806 | 82 |
| convex stack calibrated | 0.8613 | 0.8086 | 0.1805 | 82 |
| behavioral supermodel | 0.8472 | 0.7943 | 0.1887 | 82 |
| behavioral supermodel calibrated | 0.8472 | 0.7943 | 0.1883 | 82 |

Calibration-selected behavioral strength: **0.25**.
Behavior beat the strongest single expert on both declared metrics: **False**.

## Boundaries

- The audit is validation-derived and was consulted by earlier experiments
- Physical experts use known catalog ephemerides for labelled training examples
- Pixel-feature availability is explicit and unavailable experts are masked
- The frozen prospective cohort remains necessary for an unbiased final comparison
