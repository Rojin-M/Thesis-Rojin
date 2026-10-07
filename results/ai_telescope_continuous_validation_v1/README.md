# AI-telescope continuous-scan validation

The frozen v2 localizer completed 314 full-sector inferences: a synthetic transit
and a sign-inverted pixel-residual control on each of 78 calibration and 79 audit
hosts. Injection conditions were assigned before inference from a repeated factorial across four depths,
three durations and single, periodic or timing-variable events. The separate
90-host prospective cohort was not used.

The predeclared calibration rule selected threshold 0.900000, up from the
centered-window threshold of 0.854588. It reduced duration-compatible controls
on the audit from 2.569 to 0.745 events per 27 exposure-days, so the calibration
target generalized. Sensitivity also fell:

| Audit operating point | System recovery | Event recovery | Control events / 27 d |
| --- | ---: | ---: | ---: |
| Frozen 0.854588 | 31/79 (39.2%) | 60/276 (21.7%) | 2.569 |
| Selected 0.900000 | 21/79 (26.6%) | 41/276 (14.9%) | 0.745 |

At the selected threshold, system recovery rose with depth: 2/25 at 500 ppm,
5/18 at 1,000 ppm, 6/18 at 2,000 ppm and 8/18 at 5,000 ppm. Single-event
recovery was 3/27, compared with 10/26 periodic and 8/26 timing-variable systems.
This is evidence that threshold adjustment alone cannot make the present model
both selective and sensitive; low-depth and single events require a detector
trained and calibrated for continuous scanning.

The control is an empirical null based on sign-inverted real pixel residuals.
It is not a survey astrophysical false-positive rate. The injected target signal
uses an estimated spatial PSF and trapezoidal transit shape; it does not yet
cover physical limb darkening, background-source eclipses, multi-sector data or
an unbiased sky population. The reused audit is also not a pristine external
test.

- [Committed evidence summary](evidence.json)
- [Historical methods and remaining research](../../archive/legacy-docs/ai_telescope_research.md)

All 162 registered artifacts verified, and the 28-test focused suite passed.
Detailed reports and per-host tables remain in local ignored outputs under
`outputs/research/ai_telescope/`. The new operating point has not been deployed
to the watcher or websites.
