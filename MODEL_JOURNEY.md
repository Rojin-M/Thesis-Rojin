# Model journey and current decision

**Evidence reviewed: 28 September 2026.** This is the shortest path through the thesis work. Scores from different tasks and cohorts should not be placed on one leaderboard.

## What is running

The bounded TESS watcher finds blind proposals and records the frozen Kepler `shared_v1` CNN score. The separate [supermodel v2 worker](archive/legacy-docs/watcher_supermodel_v2.md) can add an eleven-expert score in primary mode **only when every required input passes its checks**. Missing inputs retain a labelled CNN fallback. Check the candidate dossier for the current model and score role; a running website alone does not mean the worker is running. These scores rank proposals for review. Neither is a validated probability that a blind signal is a planet.

## How the model choice evolved

| Step | Evidence | Decision |
| --- | --- | --- |
| Shared Kepler → TESS CNN | [Frozen transfer benchmark](results/tess/shared_transfer/README.md): AP 0.7991 on the previously consulted 335-candidate TESS test | Retain as the reference input contract and fallback; shared preparation did not improve AP over the legacy input result (0.8021). |
| Five training approaches | [Three-seed pilot](results/mission_adaptation_pilot/README.md): mean AP 0.7644 fine-tuned, 0.7474 TESS-only, 0.7067 pooled, 0.6934 DANN on 82 validation-derived audit rows | Fine-tuning led this short pilot. DANN did not earn promotion. This cohort cannot be compared directly with the earlier 335-candidate benchmark. |
| More diverse experts | [Transformer](archive/legacy-results/transformer_expert_pilot_v1/README.md), [diagnostic experts](archive/legacy-results/diagnostic_experts_v1/README.md), and [behavioral stacks](archive/legacy-docs/behavioral_supermodel_research.md) | Keep their complementary signals. Behavioral correction and dynamic expert routing did not beat the declared static comparators. |
| Cross-fitted nonlinear stack | [Reused audit](results/crossfit_supermodel_v2/report.md): AP 0.8716, calibrated Brier 0.1662, versus static v4 AP 0.8613 | It improved the reused audit, but earlier consultation limits the strength of that result. |
| Frozen fresh classifier check | [Fresh 14-candidate audit](results/fresh_classifier_audit_v1/README.md): static v4 AP 1.0000; nonlinear AP 0.8333, Brier 0.1067 and 13/14 correct at 0.5 | The nonlinear ranking advantage did not repeat. The three-positive, availability-selected sample is too small to establish a universal winner. No weights were selected from this audit. |
| Watcher adapter | [Supermodel v2 deployment guide](archive/legacy-docs/watcher_supermodel_v2.md) | The adapter reproduces frozen logits and records input provenance. Operational correctness supports conditional scoring, not a claim of better blind-search accuracy. |

## A separate question: can we find events?

The candidate classifiers above start with a period and epoch. Blind event search has its own controls and denominators. On [90 development-disjoint physical-injection hosts](results/ai_telescope_physical_benchmark_v1/README.md), v3 found additional events on 17 hosts versus 13 for v2, but exceeded its control-alert budget; TLS also found 17 hosts with fewer control alerts. On [99 fresh hosts](results/ai_telescope_recovery_v1/README.md), calibrated v3 kept 21 host recoveries while reducing inverted-control alerts to 0.172 per 27 exposure-days. TLS found 22; every method missed the 25 weakest, 500 ppm injections. The proposed hybrid fell to 5/99 and was rejected. No detector result confirms a planet or establishes a survey-wide false-positive rate.

## Next decision gate

1. Freeze a larger host-disjoint classifier cohort with more positive labels and record every archive-availability exclusion before scoring. Compare static v4, nonlinear v2, and the CNN under the same input coverage and calibration rules.
2. Test weak-event sensitivity, contaminating background sources, eclipsing binaries, and multi-sector coverage under a predeclared control-alert budget. Keep BLS and TLS as explicit detector comparators.
3. Promote a model only after the relevant *fresh* task-specific evidence supports it. Preserve the scores, model identity, input gaps, and human review in each candidate dossier.

## Where to look

- [Active evidence index](results/README.md): all retained experiment reports, including negative results.
- [Thesis storyline](STORYLINE.md): the reasoning and chronology behind the experiments.
- [Research website](docs/website_guide.md): live jobs, watcher status, candidates and model identities.
- [Academy](academy/README.md): a guided explanation of the same evidence; its project map is a dated static snapshot.
- `data/` and `outputs/`: local prepared arrays, photometry, checkpoints, logs and database. They remain local because later checks and future experiments may need them.
