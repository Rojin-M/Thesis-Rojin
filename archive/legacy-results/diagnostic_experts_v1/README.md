# Handcrafted diagnostic experts

Two interpretable specialists were fitted on TESS training groups using features
computed from the existing normalized global/local views and scalar diagnostics.
Regularization was selected on the selection partition and temperature scaling
used the separate calibration partition.

| Expert | Audit AP | ROC AUC | Raw Brier | Calibrated Brier | TP / FP at 0.5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Transit morphology | 0.8071 | 0.7428 | 0.2063 | 0.2044 | 27 / 12 |
| Stellar variability | **0.8631** | **0.8194** | **0.1774** | **0.1801** | **36 / 10** |

The stellar-variability expert led the reused 82-row audit at this stage. The
later [nonlinear supermodel](../crossfit_supermodel_v2/report.md) improved ranking
to AP 0.8716; this single expert retains the higher accuracy at the reported
threshold (78.0% versus 74.4%). These results remain provisional because the audit was already consulted by
earlier experiments and the inputs use known catalog ephemerides. The original
TESS test set was not evaluated.
