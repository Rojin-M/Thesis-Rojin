# Active public evidence

This folder contains the compact evidence set that supports the current thesis narrative. Older exploratory results and unstable configs have been moved under [archive](../archive/README.md) so the repo can be read and continued from a clear checkpoint.

## Start from the current checkpoint

| Item | Why it matters |
| --- | --- |
| [../MODEL_JOURNEY.md](../MODEL_JOURNEY.md) | Current model choice and decision gate |
| [../STORYLINE.md](../STORYLINE.md) | The research reasoning and chronology |
| [../docs/website_guide.md](../docs/website_guide.md) | How the websites and watcher are run |
| [../configs](../configs) | Active frozen run configs |
| [../archive](../archive) | Legacy experimental material kept for provenance |

## Best public evidence set

These are the result folders to read first when continuing the project:

- [mission_adaptation_pilot](mission_adaptation_pilot/README.md)
- [crossfit_supermodel_v2](crossfit_supermodel_v2/report.md)
- [fresh_classifier_audit_v1](fresh_classifier_audit_v1/README.md)
- [ai_telescope_physical_benchmark_v1](ai_telescope_physical_benchmark_v1/README.md)
- [ai_telescope_recovery_v1](ai_telescope_recovery_v1/README.md)
- [vetting_snapshot_20260923](vetting_snapshot_20260923/README.md)
- [reference_calibration_v1](reference_calibration_v1/README.md)
- [tess/shared_transfer](tess/shared_transfer/README.md)

## Supporting and non-promoted evidence

These records support the chronology and explain why some approaches were not promoted:

- [Automatic watcher run](automatic_watcher_run/README.md): bounded processing of two known-object controls.
- [Adaptive-memory pilot](adaptive_memory_pilot_v1/README.md) and [real-photometry follow-up](adaptive_memory_real_v1/README.md): synthetic engineering test followed by a small negative control result.
- [Continuous-scan validation](ai_telescope_continuous_validation_v1/README.md) and [v3 follow-up](ai_telescope_continuous_v3/README.md): threshold/sensitivity trade-off and an exploratory improvement on a reused audit.
- [Frozen unseen-host scan](ai_telescope_prospective_v1/README.md): an unlabeled review queue, not an accuracy or discovery result.
- [Behavioral supermodel v2](behavioral_supermodel_v2/report.md) and [v5](behavioral_supermodel_v5/report.md): exploratory stacks not promoted to candidate scoring.
- [Frozen prospective host cohort](prospective_cohort_v1/README.md) and [TLS/pixel feasibility pilot](tls_pixel_pilot_v1/README.md): cohort and data-flow records for future work.
- [25 September target-search snapshot](../archive/legacy-results/new_target_search_20260925/README.md): historical selection and processing record.

## Keep the evidence compact

Each public result should contain:

- README with cohort, model and question
- evidence.json or equivalent provenance
- a checksum manifest or hash record
- the minimum artifact bundle needed to verify the result
- a brief note on limits and exclusions

Large local outputs remain outside the public repository. Bundles that depend on them state in their README which detailed reports or raw tables are local-only.

## Archive policy

Anything older than the active public evidence set should live under [archive](../archive/README.md), not in the main results index. The archive preserves the research trail without making the repository unreadable.

## Current expectation

The repo is meant to support continuation from a clean checkpoint, not a complete dump of every exploratory branch. If a new result changes the project decision, it should be added as a dated result bundle and then linked from this page.
