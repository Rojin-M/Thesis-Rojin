# Behavioral supermodel v3

Eight experts include CNN/DANN regimes, a Transformer, transit morphology and stellar variability.

| Method | AP | ROC AUC | Brier |
| --- | ---: | ---: | ---: |
| tess only | 0.7489 | 0.7117 | 0.2158 |
| kepler only | 0.5619 | 0.4946 | 0.3376 |
| fine tuned | 0.7921 | 0.7512 | 0.2044 |
| pooled | 0.7154 | 0.6507 | 0.2502 |
| dann | 0.7019 | 0.6292 | 0.2725 |
| transformer | 0.7368 | 0.6776 | 0.2295 |
| transit morphology | 0.8071 | 0.7428 | 0.2063 |
| stellar variability | 0.8631 | 0.8194 | 0.1774 |
| uniform mean | 0.8169 | 0.7542 | 0.2016 |
| convex stack | 0.8557 | 0.8002 | 0.1816 |
| convex stack calibrated | 0.8557 | 0.8002 | 0.1815 |
| behavioral supermodel | 0.8557 | 0.8002 | 0.1816 |
| behavioral supermodel calibrated | 0.8557 | 0.8002 | 0.1815 |

Calibration-selected behavioral strength: **0.0**.
Behavior beat the strongest individual expert on both declared metrics: **False**.

## Boundaries

- The audit was previously consulted and best-single identification is descriptive only
- Diagnostic experts use known-ephemeris prepared views and do not validate blind recovery
- No target-pixel files are cached, so difference-image and source-localization experts remain unavailable
- Prospective host-disjoint confirmation is required before promotion
