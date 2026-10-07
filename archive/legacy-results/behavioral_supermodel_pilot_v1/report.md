# Behavioral expert supermodel pilot

A meta-model observes frozen experts on the original candidate and four label-free diagnostic probes.
It is trained on selection, calibrated separately, and reported on the validation-derived audit.

| Method | AP | ROC AUC | Brier | NLL |
| --- | ---: | ---: | ---: | ---: |
| best single selection | 0.7154 | 0.6507 | 0.2502 | 0.7006 |
| uniform mean | 0.7072 | 0.6579 | 0.2349 | 0.6591 |
| ordinary stack | 0.6841 | 0.6244 | 0.2565 | 0.7270 |
| ordinary stack calibrated | 0.6841 | 0.6244 | 0.2462 | 0.6913 |
| behavioral supermodel | 0.5907 | 0.5604 | 0.3911 | 6.4019 |
| behavioral supermodel calibrated | 0.5907 | 0.5604 | 0.2769 | 0.7745 |

Behavior features beat ordinary stacking under both predeclared criteria: **False**.

## Boundaries

- Current sealed experts are CNN and DANN-CNN variants; no Transformer expert is yet available
- The 82-row validation-derived audit was used by earlier experiments and is not a pristine final test
- Diagnostic occlusions are counterfactual sensitivity probes, not physical light-curve augmentations
- Known catalog ephemerides are present; this is candidate classification rather than blind detection
- A larger prospective host-disjoint evaluation is required before scientific promotion
