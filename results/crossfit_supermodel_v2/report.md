# Cross-fitted nonlinear supermodel v2

A regularized nonlinear classifier learns joint failure patterns from 538 host-disjoint out-of-fold expert predictions, then blends with the v4 prior.

| Method | AP | ROC AUC | Brier | NLL | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| stellar variability | 0.8631 | 0.8194 | 0.1774 | 0.6574 | 0.7805 |
| v4 static stack | 0.8613 | 0.8086 | 0.1806 | 0.6021 | 0.7073 |
| v4 static stack calibrated | 0.8613 | 0.8086 | 0.1805 | 0.6042 | 0.7073 |
| crossfit nonlinear | 0.8716 | 0.8325 | 0.1665 | 0.5286 | 0.7439 |
| crossfit nonlinear calibrated | 0.8716 | 0.8325 | 0.1662 | 0.5347 | 0.7439 |

## Frozen selection

Selection chose **7 leaves**, L2 **10.0** and blend **0.5**.
Selection AP gain over v4: **+0.0264**.
It beat the static stack and strongest single expert on both declared audit metrics: **True**.

## Boundaries

- The audit is validation-derived and was consulted by earlier experiments
- Selection labels choose tree complexity, regularization and blend strength
- Physical experts use known catalog ephemerides on these labelled examples
- A new frozen host-disjoint evaluation is required for a paper-level claim
