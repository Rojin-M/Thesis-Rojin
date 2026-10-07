# Follow-up to the research issues

Calibration and evaluation tooling improved. Weak-transit detection is still unresolved, the hybrid proposal is rejected, and the fresh classifier audit remains too small for a broad superiority claim.

The original 90-host benchmark and 82-row classifier audit remain unchanged. New detector settings were calibrated before the fresh 99-host run, and the classifier was applied with frozen weights.

| Issue | Implemented change | Fresh evidence |
| --- | --- | --- |
| v3 control-rate transfer | 50% calibration margin with Poisson and host-bootstrap upper estimates | Calibrated v3: 0.172 alerts / 27 d versus original v3: 0.332 on the same hosts |
| Weak and single events | Local sideband search over 0.5–12 h durations, plus a budgeted neural hybrid | Hybrid: 5/99 hosts; see depth/mode breakdown below |
| Coarse BLS calibration | Exact observed-score boundaries, tied events counted together | Mechanically resolved; conservative transfer margin can still choose a high threshold |
| Reused classifier audit | Newly acquired data, unchanged preprocessing and all eleven frozen experts | 14 fresh candidates (3 positive, 11 negative); independent but too small for a broad superiority claim |

| Subset | Original v3 | Calibrated v3 | Single-event search | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| Single transits | 4/33 | 4/33 | 1/33 | 1/33 |
| 500 ppm | 0/25 | 0/25 | 0/25 | 0/25 |

[Detector protocol, figure and full results](../ai_telescope_recovery_v1/README.md).
[Fresh classifier audit and individual predictions](../fresh_classifier_audit_v1/README.md).

Implementation checks: 48 focused tests passed; the new classifier inference path also reproduced the previous 82-row AP, AUC, Brier and log-loss values and physical expert logits within 1e-7 (metrics) / 1e-5 (logits).
No model was deployed. These studies still do not establish background-source rejection, binary rejection, multi-sector detector performance, or a survey false-positive rate.
