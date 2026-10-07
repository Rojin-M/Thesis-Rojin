# Continuous-scan-aware AI telescope v3

v3 fine-tunes the four-view v2 localizer on the original training windows plus
one spatially coherent low-depth transit and one model-selected inverted-residual
hard control per training host. It generated 1,340 new windows across 513
training and 157 selection hosts. Calibration, audit, and the separate 90-host
prospective cohort were excluded from optimization.

The same full-sector protocol then selected threshold 0.86 on the 78 calibration
hosts and evaluated the unchanged 79-host audit. Compared with v2 at its own
calibration-selected threshold, v3 improved both recovery measures while also
lowering the empirical control-alert rate:

| Audit result | v2 | v3 |
| --- | ---: | ---: |
| System recovery | 21/79 (26.6%) | **28/79 (35.4%)** |
| Injected-event recovery | 41/276 (14.9%) | **53/276 (19.2%)** |
| Control events per 27 exposure-days | 0.745 | **0.517** |
| Calibration-selected threshold | 0.90 | 0.86 |

The hosts and injection conditions are identical. Ten systems changed from
missed by v2 to recovered by v3, while three changed in the other direction;
18 were recovered by both and 48 by neither. The paired exact McNemar p-value is
0.092, so this small reused audit supports an exploratory improvement rather
than independent confirmation.

Weak and isolated events remain the main limitation. Recovery at 500 ppm rose
from 2/25 to 5/25, while single-event recovery rose from 3/27 to only 4/27.
Physical limb-darkened and background-source injections, a matched BLS/TLS
comparison, repeated training seeds, and evaluation on untouched hosts remain
necessary before production use. The inverted-residual control rate is not a
survey astrophysical false-positive rate.

- [Committed evidence summary](evidence.json)
- [Historical methods and remaining research](../../archive/legacy-docs/ai_telescope_research.md)

All 1,510 registered training and validation artifacts verified, and the
32-test focused suite passed. Detailed reports and per-host tables remain in
local ignored outputs under `outputs/research/ai_telescope/`; v3 has not been
deployed to the watcher or websites.
