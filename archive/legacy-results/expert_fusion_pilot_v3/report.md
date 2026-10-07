# Feature-conditioned expert-fusion pilot

A soft router learned on the TESS selection partition combines five frozen training-regime experts.
Calibration and abstention use a separate partition; the validation-derived audit is reported once.

| Method | AP | ROC AUC | Brier | NLL |
| --- | ---: | ---: | ---: | ---: |
| best single selection | 0.7154 | 0.6507 | 0.2502 | 0.7006 |
| uniform mean | 0.7072 | 0.6579 | 0.2349 | 0.6591 |
| learned static | 0.7263 | 0.6740 | 0.2289 | 0.6449 |
| feature conditioned gate | 0.6671 | 0.6675 | 0.2369 | 0.6706 |
| feature conditioned gate calibrated | 0.6671 | 0.6675 | 0.2321 | 0.6568 |

## Mean audit routing

- tess_only: 0.271
- kepler_only: 0.265
- fine_tuned: 0.179
- pooled: 0.127
- dann: 0.158

## Boundaries

- Pilot experts differ by training regime but share one CNN architecture and input contract
- The 82-row audit is validation-derived and too small for a final paper claim
- Known catalog ephemerides are used; this is classification, not blind transit recovery
- The abstention rule is empirical and does not provide conformal coverage
- Competence by regime is descriptive and requires replication on a prospective sector split
- Pixel, centroid, contamination and catalog experts are future modalities, not present in this pilot
