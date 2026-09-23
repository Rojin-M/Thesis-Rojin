# Active thesis evidence

This directory indexes the evidence retained for the Kepler-to-TESS domain-adaptation and discovery thesis. Live checkpoints, predictions, caches, and reports remain in ignored local `outputs/` and `data/` directories. A [frozen vetting dataset](vetting_snapshot_20260923/README.md) additionally preserves the complete research database, referenced artifacts, selected input light curves and retained inference model for restoration from a clone.

| Evidence | Role | Main limitation |
| --- | --- | --- |
| [Kepler–TESS input audit](tess/input_audit/README.md) | Measures preprocessing and feature-distribution shift | Descriptive; does not prove what caused a model error |
| [Shared-transfer benchmark](tess/shared_transfer/README.md) | Freezes the Phase-1 CNN reference results | Single seed and previously consulted labelled tests |
| [Completed mission-adaptation pilot](mission_adaptation_pilot/README.md) | Five approaches × three seeds; comparison scores on 44 saved blind proposals | Short-budget validation-derived audit; DANN benefit not demonstrated; reference scorer retained |
| [Candidate-registry control](tess/candidate_vetting/README.md) | Verifies recognition of a known confirmed signal in current public catalogs | Catalog matching is not planet validation or proof of novelty |
| [Blind detection engineering pilot](detection_pilot/README.md) | Searches local light curves and evaluates known TRAIN stars, injections and negatives | Small selected sample; white-noise scores and recovery do not establish survey readiness |
| [Proposal scoring and vetting pilot](scoring_vetting_pilot/README.md) | Connects 38 existing blind proposals to the actual trained CNN, diagnostics and catalog evidence | Uncalibrated scores; selected controls; incomplete image/contamination and broader registry coverage |
| [Public release watcher pilot](release_watcher_pilot/README.md) | Verifies official metadata, bounded acquisition/dispatch, budgets and restart deduplication | One cached known control; scoped availability; no new science download or prospective result |
| [Automatic watcher run](automatic_watcher_run/README.md) | Records the subsequent public download, three added proposals, activity/failure history and 44-proposal snapshot | Two watched known controls; 17 real-data and 27 synthetic proposals; no new-planet claim |

These are the only active result groups. Earlier practical-work model sweeps are not part of the thesis evidence index.

The benchmark and catalog checker answer different questions:

- Model metrics measure ranking and classification on labelled examples.
- Registry matching asks whether a compatible public record is present at a recorded time.
- Blind detection asks whether a periodic proposal can be found without catalog ephemerides; recovery and negative controls measure specific failure modes.
- Human and observational vetting asks whether an unmatched signal is astrophysical and plausibly planetary.

None of the committed results constitutes a new candidate or confirmed-planet claim. See the [main README](../README.md) for the active workflow and planned `discovery_v1` protocol.
