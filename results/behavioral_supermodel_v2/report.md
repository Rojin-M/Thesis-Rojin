# Behavioral supermodel v2

Six experts, including a distinct dual-view Transformer, are combined by a convex stack and a calibration-gated behavioral residual.

| Method | AP | ROC AUC | Brier | NLL |
| --- | ---: | ---: | ---: | ---: |
| transformer ensemble | 0.7368 | 0.6776 | 0.2295 | 0.6490 |
| uniform mean | 0.7149 | 0.6711 | 0.2296 | 0.6480 |
| convex stack | 0.7278 | 0.6902 | 0.2218 | 0.6288 |
| convex stack calibrated | 0.7278 | 0.6902 | 0.2243 | 0.6346 |
| behavioral supermodel | 0.7070 | 0.6579 | 0.2434 | 0.6808 |
| behavioral supermodel calibrated | 0.7070 | 0.6579 | 0.2454 | 0.6865 |

Calibration-selected behavioral strength: **0.5**.
Behavior improved both AP and calibrated Brier over the convex stack: **False**.

## Boundaries

- Validation-derived audit was used by earlier experiments and is not a pristine final test
- Transformer training is a bounded 120-update pilot without a convergence claim
- Occlusion and perturbation probes measure sensitivity but are not physical planet simulations
- TLS, centroid, contamination and pixel-level experts are not yet included
- Prospective host-disjoint confirmation remains required
