# Thesis storyline: mission-invariant learning for TESS discovery

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
