# Thesis storyline: from transfer learning to evidence-led search

This is the research path in chronological order. The [model journey](MODEL_JOURNEY.md) gives the short decision table and current scoring status; the [evidence index](results/README.md) retains every report, including negative results.

## 1. Narrow the question

The project began as a broad Kepler classification practical with tabular models, CNNs, blending and Transformers. That branch did not yield one clear thesis claim. Earlier code remains recoverable from Git history (especially `bf82783`, `ef683a6` and `42025da`). The thesis question became whether a shared light-curve encoder transfers from Kepler to TESS and helps prioritize signals found in a reproducible blind search.

This requires two different evaluations. **Classification** starts with a supplied period and epoch and asks how to rank candidate-like signals. **Detection** must find events or periods without catalog ephemerides. The tasks have different inputs, controls and denominators, so their scores cannot share a single leaderboard.

## 2. Establish the shared baseline

`shared_v1` represents each Kepler and TESS example with a 200-bin global view, a 100-bin local view and seven scalar features. It protects known transit windows during detrending and fits normalization on Kepler training data. The rebuild retained 5,385/5,518 Kepler and 2,208/2,208 TESS candidates. The frozen Kepler CNN reached AP 0.7991 on the previously consulted 335-candidate TESS test, versus 0.8021 for legacy inputs. Compatible preprocessing alone did not improve AP. The [input audit](results/tess/input_audit/README.md) also found substantial cross-mission feature shift.

The initial thesis hypothesis was that a mission-adversarial head, using gradient reversal, could help the encoder learn transit evidence that transfers across missions. This is a testable use of known methods, not a claim to have invented cross-mission learning or DANN. The five-arm comparison held the core encoder, eligible data and reporting rules together: TESS-only, Kepler-only, fine-tuned, pooled and DANN.

## 3. Reject easy winner stories

The [three-seed short-budget pilot](results/mission_adaptation_pilot/README.md) found mean AP 0.7644 for fine-tuning, 0.7474 for TESS-only, 0.7067 for pooled training and 0.6934 for DANN on an 82-row validation-derived audit. DANN did not earn promotion. All 15 selected models were later applied to 44 saved blind proposals as an engineering comparison, not evidence of 44 discoveries. The frozen CNN stayed the reference scorer.

The team then tested feature-conditioned fusion, behavioral probes, a dual-view Transformer, morphology and variability experts, physical diagnostics, and candidate-specific expert routing. Some components improved a reused audit; dynamic routing and behavioral correction did not consistently beat static comparators. Cross-fitting produced 538 host-disjoint competence examples and exposed a poor linear expected-loss target. The corrected [nonlinear eleven-expert stack](results/crossfit_supermodel_v2/report.md) reached AP 0.8716 and calibrated Brier 0.1662 on the reused audit, above the static v4 stack there.

A [fresh frozen classifier check](results/fresh_classifier_audit_v1/README.md) registered 295 candidate hosts; only 14 had eligible public native products and passed unchanged preparation. On its three positives and eleven negatives, static v4 ranked perfectly (AP 1.0000), while nonlinear v2 had AP 0.8333, Brier 0.1067 and 13/14 correct at threshold 0.5. The nonlinear ranking advantage did not repeat. This sample is too small and availability-selected to establish broad superiority. The [watcher adapter](archive/legacy-docs/watcher_supermodel_v2.md) can score with the frozen nonlinear model when all eleven inputs pass, while retaining the CNN fallback and recording model identity. Operational replay does not establish blind-search accuracy.

## 4. Turn ranking into a bounded research workflow

The local Research site and persistent store now retain jobs, light curves, blind BLS proposals, model scores, catalog snapshots, diagnostic plots, failures and human review history. A watcher checks a finite set of recent public TESS products under cumulative target, product and byte limits. The [23 September run](results/automatic_watcher_run/README.md) and [25 September target-search snapshot](archive/legacy-results/new_target_search_20260925/README.md) show what was actually processed. The [frozen vetting snapshot](results/vetting_snapshot_20260923/README.md) preserves the database and referenced evidence for restoration.

A model score ranks review effort. `UNMATCHED` means a compatible record was not found in the supported catalog snapshots; it is not proof of novelty. Validation would still need individual-event checks, pixel/source localization, contaminant and eclipsing-binary rejection, multi-sector consistency and potentially new observations. The current bounded archival workflow is not the planned production `discovery_v1` survey.

## 5. Ask whether the search can recover weak events

Blind event-search experiments added BLS/TLS, target-pixel photometry, neural event scans, adaptive-memory trials and physical injections. The memory follow-up did not beat raw BLS on a small real-photometry test. The [90-host physical-injection comparison](results/ai_telescope_physical_benchmark_v1/README.md) found more v3 than v2 host recoveries (17 versus 13), but v3 exceeded its control-alert budget; TLS also recovered 17 hosts with fewer alerts and more individual events.

The [99-host fresh recovery follow-up](results/ai_telescope_recovery_v1/README.md) kept v3 host recovery at 21 while calibration reduced inverted-control alerts from 0.332 to 0.172 per 27 exposure-days. TLS recovered 22 hosts. The proposed single-event hybrid recovered only five and was rejected. All methods missed the 25 weakest 500 ppm injections. These controls measure specified synthetic-signal recovery and inverted alerts, not a survey false-positive rate or a new planet.

## 6. What earns the next model change

Freeze a larger independent classifier cohort with more positives and complete archive-availability accounting. Compare the frozen CNN, static v4 and nonlinear v2 under matching input coverage, calibration and review rules. Separately, test weak events, background-source and eclipsing-binary contamination, and multi-sector data against predeclared recovery and control budgets. Keep negative findings, exact configs and concise decisions in [results](results/README.md); update the [model journey](MODEL_JOURNEY.md) only when evidence changes the choice. The [Academy](academy/README.md) teaches the methods and clearly labels its dated project snapshot.
