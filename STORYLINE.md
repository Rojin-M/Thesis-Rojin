# Thesis storyline: mission-invariant learning for TESS discovery

**23 September 2026 update:** the original five-arm, three-seed pilot is now
complete. DANN did not demonstrate an advantage: mean TESS audit AP was 0.6934,
versus 0.7067 pooled and 0.7644 fine-tuned. These are short-budget results on
validation-derived groups, not the untouched prospective study. All 15 selected
models were also applied to 44 saved blind proposals as additional evidence.
The website shows their comparisons and a separate persistent worker adds them
to newly completed watcher jobs. The reference scorer remains primary. See the
[completed results and decision](results/mission_adaptation_pilot/README.md).
Historical descriptions below retain the sequence of work and earlier boundaries.

## 1. The project pivot

The project began as a broad Kepler classification practical: tabular models, CNN variants, metadata branches, blending, and transformers. That work established useful engineering skills, but it did not form one clear scientific contribution. The thesis now asks a narrower question:

> Can a shared light-curve encoder learn transit evidence that transfers from Kepler to TESS, and can that model support a reproducible prospective discovery workflow?

The old practical branches are intentionally absent from the active tree. They remain recoverable from Git history, especially commits `bf82783` (complete Kepler practical), `ef683a6` (shared Kepler–TESS milestone), and `42025da` (candidate-registry checker). Removing them from the working tree does not erase the evidence or development history.

## 2. What Phase 1 established

### Shared input contract

Kepler and TESS candidates are represented with the same interface:

- a 200-bin global phase-folded view;
- a 100-bin local transit view;
- flux, scatter, and coverage channels in each view; and
- seven scalar context features.

The `shared_v1` preparation protects known transit windows during detrending, masks companion candidates, requires sufficient sampled events, preserves eligible star-grouped split memberships, and fits normalization using Kepler training rows only.

The completed rebuild retained 5,385 of 5,518 Kepler candidates and all 2,208 TESS candidates. The prepared arrays are local because they are large; compact summaries and hashes are committed.

### Frozen transfer result

The retained CNN uses the same global/local/scalar encoder for both missions. On the fixed 335-candidate TESS test set:

| Kepler-trained source | AP | ROC-AUC |
| --- | ---: | ---: |
| Legacy v0 inputs | 0.8021 | 0.7767 |
| Shared `shared_v1` inputs | 0.7991 | 0.7828 |

Shared preprocessing therefore did not demonstrate an AP improvement. This is a useful negative result: compatible shapes and a common preprocessing implementation do not by themselves remove mission shift.

The result is limited to one seed and a previously consulted labelled benchmark. The rebuilt source cohort also excludes 133 Kepler candidates, so the comparison does not isolate preprocessing as the only changed variable.

### Measured domain shift

The input audit found large differences between Kepler and TESS feature distributions even when their arrays share the same schema. It also demonstrated that the old Kepler clipping function can erase a synthetic transit, while a small real-cache audit did not support blaming that mechanism for the entire transfer gap.

The correct conclusion is not that one mission is simply noisier. Candidate populations, observing cadence, preprocessing, label construction, and scalar-feature relationships all differ. This motivates a controlled domain-adaptation experiment rather than another unrelated architecture sweep.

## 3. The thesis contribution

The proposed model keeps the retained CNN encoder and adds a mission-classification head through a gradient-reversal layer:

```text
Kepler and TESS shared inputs
              |
        shared CNN encoder
          /            \
 planet classifier   mission classifier
                          |
                 gradient reversal
```

The planet head rewards representations useful for classifying transit signals. The mission head learns to distinguish Kepler from TESS, while gradient reversal makes the encoder learn features that make that distinction difficult.

The hypothesis is falsifiable: a mission classifier near chance is not enough. Domain-adversarial training succeeds only if it improves calibrated TESS performance, high-precision recall, low-SNR behavior, or label efficiency without damaging the astrophysical task.

The broad ingredients are not new. Cross-mission training, transfer learning, global/local transit encoders, and domain-adversarial learning all have prior art. [ExoNet 2026](https://arxiv.org/abs/2604.15560) even proposes joint Kepler–TESS training with domain-adversarial regularization as future work. The defensible contribution is a careful implementation and controlled evaluation for this exact Kepler-to-TESS setting, not a claim to have invented DANN or cross-mission learning.

Any final novelty sentence must be qualified by the literature review. A safe working formulation is:

> We evaluate whether mission-adversarial representation learning improves Kepler-to-TESS transit classification under a shared global/local input contract.

## 4. Locked experiment matrix

Every main arm must use the same eligible candidates, encoder capacity, data splits, evaluation code, and reporting rules:

1. TESS-only CNN.
2. Kepler-only CNN evaluated zero-shot on TESS.
3. Kepler pretraining followed by TESS fine-tuning.
4. Ordinary pooled Kepler and TESS training.
5. Pooled training with gradient reversal and a mission head.

Required controls:

- multiple fixed seeds;
- star-grouped splits and explicit leakage checks;
- TESS label-fraction experiments;
- AP, ROC-AUC, calibration, and recall at fixed high precision;
- performance by SNR, magnitude, period, and candidate source;
- mission-head accuracy and representation diagnostics;
- matched parameter counts and training budgets; and
- validation-only checkpoint, threshold, and hyperparameter selection.

The previously consulted TESS test set remains a benchmark. It cannot serve as an unbiased discovery sample.

## 5. From classification to discovery

The current CNN receives an already identified period and epoch. It ranks candidate-like signals; it does not search pixels for periodic dips. A real discovery path requires a separate, prospectively frozen `discovery_v1` pipeline:

```text
new TESS FFI data
      |
target selection and deblended aperture photometry
      |
detrending with transit protection
      |
BLS + TLS signal generation and iterative masking
      |
quality and detectability gates
      |
CNN/DANN ranking and calibrated uncertainty
      |
automated catalog and diagnostic checks
      |
human-vetting dossier
      |
cTOI submission and possible follow-up
```

The initial search scope should be small enough to audit completely. The provisional design is one objectively selected TESS Sector 97 CCD, emphasizing faint cool dwarfs (`13.5 < Tmag <= 15.5`) and longer periods (`16–27` days). This scope is not locked until target counts, pixel access, contamination risk, and injection-recovery feasibility are checked.

Both BLS and TLS should generate proposals because their assumptions differ. The ML score should rank signals rather than act as a hard veto; unusual candidates are exactly where a familiar-data classifier may be least reliable.

Before looking for exciting candidates, the search protocol must freeze:

- target inclusion and exclusion rules;
- detrending and aperture choices;
- search grids and harmonic handling;
- minimum event and coverage requirements;
- candidate merging and iterative masking;
- promotion thresholds and review capacity;
- injection-recovery experiments; and
- inverted, scrambled, or off-target negative controls.

## 6. Automation without false certainty

The watcher is an orchestrator, not a continuously running model. It should poll release metadata, create one immutable release record, download only unseen products, resume failed work, and launch GPU inference only when new prepared candidates exist.

Each stage should be idempotent and leave machine-readable state:

```text
release -> targets -> light curves -> detected signals -> model scores
        -> registry checks -> automated diagnostics -> review queue
```

Every record needs source versions, timestamps, hashes, code version, stage status, and retry information. Failures stay visible; they must not silently become rejected candidates.

`tmux` is appropriate for long development runs over SSH. A system scheduler or job queue is the production mechanism because it can survive reboot, schedule retries, and prevent overlapping releases.

## 7. Registry checking and novelty

The implemented checker answers one narrow question: does the same TIC and compatible ephemeris already occur in the supported ExoFOP or NASA records? It preserves source responses and fails closed when required catalogs are unavailable.

Its valid outcomes include confirmed planet, candidate, false positive, false alarm, harmonic alias, conflict, unmatched, and incomplete lookup. `UNMATCHED` never means “new planet.” It means only that the supported public snapshots contained no compatible record at that time.

Before the checker can support a discovery queue, it still needs:

- coordinate and Gaia-neighbour matching, not only exact TIC identity;
- MAST TCE and eclipsing-binary catalogs;
- stronger aliases and duplicate-target resolution;
- aperture and nearby-source contamination evidence;
- batch operation over a release; and
- a benchmark measuring known objects incorrectly reported as unmatched.

Recent systems such as [ExoMiner++](https://arxiv.org/abs/2502.09790) show why this matters: automated selection can still yield duplicate targets and catalog artifacts that experts reject.

## 8. Human-vetting boundary

Automation prioritizes a signal; experts validate the evidence. A promoted object still requires inspection of:

- individual events, the unfolded curve, and multi-sector repeatability;
- odd/even depths, secondary eclipses, duration, shape, and aliases;
- difference images, centroid motion, aperture dependence, and Gaia neighbours;
- momentum dumps, scattered light, gaps, and detector systematics;
- public candidates, planets, eclipsing binaries, TCEs, coordinates, and literature; and
- whether follow-up imaging, spectroscopy, or time-series photometry can resolve the remaining scenarios.

A cTOI or TOI is a candidate status, not confirmation. Planet validation or confirmation requires additional statistical or observational evidence and collaboration with domain experts.

## 9. Active milestones

| Milestone | Exit condition |
| --- | --- |
| Repository cleanup | One active CNN/data/vetting path; tests pass; historical practical work remains in Git |
| DANN data loader | Balanced mission batches and unchanged star-grouped benchmark splits |
| Five-arm benchmark | Multi-seed metrics, calibration, fixed-precision recall, and label-fraction curves |
| Representation audit | Mission leakage measured without using test labels for selection |
| `discovery_v1` pilot | Locked scope plus passing injection-recovery and negative controls |
| Watcher | Idempotent release processing with retries and immutable provenance |
| Expanded checker | Coordinate, TCE, EB, alias, and batch checks with an offline benchmark |
| Human-vetting pilot | Reproducible dossiers reviewed with an astronomer |
| Prospective run | Pre-registered queue on previously uninspected search data |

The thesis remains successful if DANN does not beat simpler baselines, provided the comparison is controlled and the failure is analyzed. A credible new candidate would be an excellent additional outcome, not a condition for a valid thesis.

## 10. Research application foundation

The first implementation increment adds a local SQLite-backed job and candidate
store, restartable stages with bounded retries, source/code/model provenance
records, evidence dossiers, plots, report export and audited human review. The
research website is separate from the learning Academy. Its default database is
empty; explicitly synthetic fixtures are used only to exercise the interface and
failure handling. A completed execution is not a successful detection or a
scientifically validated signal.

The versioned `research_protocol_v1.json` encodes a bounded initial pilot and
preserves explicit time systems, feature contracts, validation-only model
selection and required evidence gaps. It remains scientifically provisional:
public metadata discovery, blind detection, injection/recovery, negative
controls, model comparisons and a detailed primary-source literature review
still need implementation or evaluation. This increment establishes engineering
infrastructure and makes no new claim about detection performance, DANN benefit,
novelty or planet confirmation.

## 11. Blind light-curve engineering pilot

The next increment implements a separate bounded BLS search on local native
TESS/Kepler photometry. Period and epoch are inferred without catalog ephemerides;
the detector records its own detrending, quality/time conventions, grid bounds,
aliases, iterative masks, event coverage, odd/even event depths and secondary
tests. The known-ephemeris feature preparation and frozen benchmark are unchanged.
Real proposals, plots, full arrays and provenance are now available in the local
research application. This does not yet implement extraction from pixels,
TLS, CNN scoring of proposals, live releases or prospective discovery.

The fixed small engineering experiment recovered all four selected TRAIN-star
controls and four of six box injections into real TESS photometry. Both 500-ppm
injections were missed. Two of four transformed/noise negative controls produced
sampling-supported proposals above a predeclared descriptive white-noise S/N of
7.1. These results were retained without threshold tuning or proposal rejection.
They demonstrate operational signal finding and expose limits; they do not
estimate unbiased completeness, establish a controlled false-alarm rate, or
support a mission-adaptation improvement claim. See the [pilot evidence](results/detection_pilot/README.md).

At the end of the detection increment, all 14 jobs were queued for downstream feature/scoring work after
successful detection, and the 38 proposals are explicitly separated into known
object controls and synthetic/transformed experiments. The protocol remains
provisional with prospective readiness false. Search-quality evaluation, model
comparisons, calibration, full diagnostics and an audited release watcher remain
required before any prospective claim.

## 12. Connecting blind proposals to trained scoring and recorded vetting

The proposal worker now constructs the frozen shared feature contract from
independently inferred ephemerides and runs the retained Kepler CNN. It protects
inferred windows during shared detrending, retains the legacy scalar meanings,
applies the exact saved Kepler TRAIN normalization and records checkpoint, code,
source and input-array receipts. This is a new inference domain: inferred masks,
spurious companions and single-product coverage can differ from labelled
benchmark inputs. Scores remain uncalibrated ranking evidence. The saved source
validation threshold is contextual; it cannot remove proposals from review.

Readable dossiers connect these scores to event coverage, genuine odd/even event
depths, a bounded secondary-event phase scan, fixed-epoch harmonic comparisons,
native centroid measurements and pipeline crowding estimates. Error models and
missing image/source-localization checks are explicit. The catalog checker now
has a bounded batch/cache integration with recorded retrieval dates and raw
bytes, stale/unavailable states and append-only refresh reports. Its supported
catalog coverage still excludes coordinate, TCE, EB and comprehensive literature
searches. A known registry match is identity evidence, not automated validation
of a detected proposal; `UNMATCHED` remains insufficient for novelty.

The engineering contribution is the auditable detection-to-evidence path and a
review route for incomplete inputs, low scores and unusual signals. It is not yet
evidence for mission-adaptation benefit, calibrated uncertainty, a controlled
survey false-alarm rate or a novel planet. The pending comparator/DANN study and
larger, representative controls must test those research hypotheses separately.

The actual increment scored all 38 existing proposals across 14 completed jobs.
Bounded live queries on the two TESS control stars recovered compatible public
planet records; the lower-scoring one remains visible as a catalog/model
disagreement. Three of the four primary known controls were below the retained
source-validation threshold. No threshold was tuned and none of these signals
was removed. These observations caution against treating labelled-benchmark
scores as a ready blind-search classifier. The [scoring/vetting evidence](results/scoring_vetting_pilot/README.md)
records these limits, the unchanged model/input hashes and an audited metadata-only
correction of the legacy BLS duration unit label.


## 13. Public metadata and a finite, auditable work stream

The release watcher now queries the official MAST observation/product API for an
explicit TIC watchlist and records first observed public availability, immutable
product/version identities and hashed response snapshots. Polling does not
expand into a sector download. A separately frozen pilot enforces cumulative
byte, target, product, runtime and retry limits, then connects verified photometry
to the existing blind detector, trained model and human evidence dossiers.
This is scoped selected-product availability; it does not assert completeness
of an entire sector or archive. Kepler remains archival.

The real control pilot revalidated TIC 231663901's sector-105 ordinary SPOC light
curve, reused its previously cached bytes after checksum/receipt validation, and
completed all eight processing stages. It retained three proposals, including a
primary independently inferred period of 1.430428 days and an existing compatible
planet record in the supported cached catalogs. Its CNN ranking score was
0.953799. The original sector-1 control score remains 0.070007; neither result
was used to tune the threshold or model. Different product coverage and inferred
inputs can change scores substantially, and these selected known controls do not
measure generalization or establish a calibrated search.

A repeated live metadata poll added no release/product identities, and dispatch
replay added no candidates, stage attempts or downloads. No new science products
were downloaded: the real pilot reused the exact original sector-105 artifact.
The download transport itself was tested through a local HTTP archive fixture,
including the real downstream model and website. See the [watcher evidence](results/release_watcher_pilot/README.md).

These are engineering results. Prospective readiness remains false. Broad FFI/
pixel coverage, representative injection/negative calibration, model uncertainty,
the comparator/DANN study and a precise literature-grounded contribution remain
required research work. Low scores, catalog nonmatches and incomplete diagnostics
continue to have explicit review paths; none is an automated novelty decision.

## 14. Automatic watchlist operation and visible evidence

The next engineering increment connects scheduled public metadata checks to
bounded product acquisition, blind detection, local CNN inference, diagnostics
and saved dossiers. The website can queue an immediate check and displays its
persisted outcome. Browser refresh reads saved results; it does not run a search.

On 23 September 2026 the automatic service had processed a previously unprocessed
public sector-97 product for TIC 150428135, alongside the earlier TIC 231663901
control. Three additional proposals brought the store to 44: 17 known-object
control proposals and 27 synthetic fixtures. This exercises an actual public
science download and the processing chain; it does not constitute a prospective
discovery result or complete the domain-adaptation study.

The [automatic-watcher record](results/automatic_watcher_run/README.md) retains
the candidate assessments, original processing identities, download failure and
audited recovery, later metadata timeout and successful recheck. Full runtime
logs stay local; the compact dated result export makes this operational evidence
reviewable in Git. The two-target watchlist and outstanding scientific vetting
limits remain explicit.
