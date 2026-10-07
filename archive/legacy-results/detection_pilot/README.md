# Blind detection engineering pilot

Run locally on 22 September 2026 using existing cached products only. These are
selected known-object, injected-signal and negative **controls**, not prospective
discoveries. The frozen labelled CNN benchmark and datasets were not altered.

The [machine-readable export](summary.json) records the fixed search settings,
source and code-manifest hashes, per-control truth evaluation,
proposal IDs, source hashes and limitations. The full experiment and source
manifest are local under `outputs/research/experiments/detection-controls-v1/`.
Candidate dossiers, plots, full arrays and experiment reports are persisted in
the research website's default SQLite store.

| Control | True period (days) | Blind BLS period (days) | Direct ephemeris recovery |
| --- | ---: | ---: | --- |
| TESS TOI-101.01 / TIC 231663901 | 1.4303699 | 1.430443883 | Yes |
| TESS TOI-102.01 / TIC 149603524 | 4.4119372 | 4.411463873 | Yes |
| Kepler K00002.01 / KIC 10666592 | 2.204735417 | 2.206838185 | Yes |
| Kepler K00003.01 / KIC 10748390 | 4.887803076 | 4.887215735 | Yes |

All four selected stars belong exclusively to frozen TRAIN groups; these are
engineering controls, not held-out performance estimates. Catalog ephemerides
were evaluated only after blind proposals were persisted. Direct recovery
requires both period and epoch agreement, with the tolerances recorded in the
report; all four also passed the local event-sampling gate.

Six 2.4-hour box transits were injected into real TESS photometry before blind
detrending, at periods 2.731 and 5.173 days and depths 500, 2000 and 8000 ppm.
**Four of six** were directly recovered among at most three proposals. Both
500-ppm injections were missed. Existing stellar signals remained in the curves;
the result is not a standalone detection-limit measurement or complete survey
injection/recovery experiment.

**Two of four** negative controls had at least one sampling-supported proposal
above the predeclared descriptive white-noise S/N reference of 7.1. The strongest
permuted-flux proposal had S/N 7.73, and the strongest inverted-flux proposal had
S/N 17.46. Two Gaussian-noise controls stayed below that reference. Inversion
does not guarantee signal-free astrophysical data, permutation destroys time
correlations, and four controls cannot calibrate survey false alarms. These
outcomes are retained and demonstrate why this statistic alone is insufficient.

The persisted run contains **14 jobs and 38 proposals**: 11 from known-object
controls and 27 from synthetic/transformed experiments. Low-S/N proposals are
retained. Detection is complete; feature construction and scoring remain queued.
A complete rerun reused all jobs/candidates with one detection attempt per job.

Search readiness remains **false**. Grid truncation, detrending attenuation,
correlated noise, more representative controls, pixel/centroid/contamination
diagnostics and prospective isolation still require evaluation. No model was
trained or selected, no new planet is claimed, and no new science bytes were
downloaded. Method and next-stage details: [blind detection](../../docs/blind_detection.md).
