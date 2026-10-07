# Cross-fitted competence supermodel

Each competence target comes from an expert that did not train on that TESS host.

| Method | AP | ROC AUC | Brier | NLL | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| stellar variability | 0.8631 | 0.8194 | 0.1774 | 0.6574 | 0.7805 |
| v4 static stack | 0.8613 | 0.8086 | 0.1806 | 0.6021 | 0.7073 |
| v4 static stack calibrated | 0.8613 | 0.8086 | 0.1805 | 0.6042 | 0.7073 |
| crossfit competence | 0.8613 | 0.8086 | 0.1806 | 0.6021 | 0.7073 |
| crossfit competence calibrated | 0.8613 | 0.8086 | 0.1805 | 0.6042 | 0.7073 |

## Frozen selection

Selection chose ridge alpha **100.0** and routing strength **0.0** using AP as the primary endpoint.
Audit top-route/oracle agreement: **25.6%**.
It beat the static stack and best single expert on the declared metrics: **False**.

## Boundaries

- The audit is validation-derived and was consulted by earlier experiments
- Fold experts use one seed and a fixed bounded update budget
- Selection labels choose ridge penalty and routing strength
- Known catalog ephemerides are used by the labelled physical experts
- A new frozen host-disjoint evaluation is required for a paper-level claim
