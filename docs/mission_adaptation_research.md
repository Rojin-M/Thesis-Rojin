# Mission adaptation: provisional hypothesis and validation matrix

Primary-source review: 22 September 2026 (Vienna). This is a bounded review,
not a systematic search establishing priority. Versions matter.

## Prior work and the actual question

[ExoMiner++ v4, 19 May 2025](https://arxiv.org/html/2502.09790v4), especially
Sections V–VI and VII, already evaluates TESS-only against pooled TESS–Kepler
training. It groups cross-validation by target star and uses richer diagnostic
inputs than this repository. Its authors found pooling more effective than
their attempted fine-tuning approaches. Scores are explicitly uncalibrated
ranking indicators; catalog nonmatches still required duplicate checks and
expert review. Their nearby-source limitations reinforce the need for independent
vetting here. The earlier v3 title emphasized transfer learning; v4 calls the
pooled approach multi-source learning. Neither pooled learning nor cross-mission
planet vetting is a new contribution of this thesis.

[ExoNet v3, 22 April 2026](https://arxiv.org/html/2604.15560v3) describes
temperature scaling and explicitly suggests domain-adversarial joint training
as future work. Its preprocessing section reports absent FITS photometry for
approximately 99.8% of Kepler training examples and all TESS inference examples;
the corresponding branches receive zeros. The limitations acknowledge this
constraint. Its stated split is label-stratified, without a demonstrated
host-group isolation audit in that description. The version history records
TOI/TIC corrections in v2 (withdrawn); use v3, not v1 numbers. These observations
limit its suitability as evidence about photometric morphology or blind weak
signal recovery. They do not establish that its catalog is invalid. Its
calibration results cannot establish calibrated false-alarm rates for our search.

[Kopparapu et al., AJ 172, 100, 20 July 2026](https://doi.org/10.3847/1538-3881/ae7d0f)
also studies instrument-agnostic prioritization using six postprocessed catalog
features and joint mission training. This recent primary source further rules
out broad claims of first instrument-independent prioritization. Its task and
inputs differ from blind photometric search.

[Ganin et al. (2016)](https://jmlr.org/papers/v17/15-239.html) supplies the
gradient-reversal method. Our five-arm implementation tests a **supervised
pooled adaptation variant**, with both missions' training labels, rather than
claiming classic unsupervised adaptation. [Guo et al. (2017)](https://proceedings.mlr.press/v70/guo17a.html)
motivates a positive scalar temperature fitted on held-out calibration logits.
Rank-preserving scaling cannot improve AP or ROC-AUC by itself, and calibration
on known candidates does not imply calibration under blind-search selection.

Earlier [Ansdell et al. (2018)](https://arxiv.org/abs/1810.13434) and
[Yu et al. (2019)](https://arxiv.org/abs/1904.02726) already use astronomical
diagnostic information and neural TESS vetting. Our retained encoder's name is
historical: it is not an exact reproduction of NASA's ExoMiner++ architecture.

**Provisional hypothesis:** under matched training budgets and protected star
groups, mission adaptation plus validation-fitted calibration improves weak
signal prioritization at a predeclared false-alarm constraint while preserving
review access for unusual signals. A failure to outperform ordinary pooling is
a useful negative result. The potential contribution is a reproducible,
failure-aware evaluation connecting classification to independently detected
signals and controlled injections, not the neural architecture alone.

## What the local model pilot can establish

The new experiment is on prepared **known-ephemeris** labelled data. Its audit
subset comes from existing validation groups, not a newly untouched test set.
No original test row may enter training, normalization fitting, checkpoint
selection, calibration, threshold selection, or reported pilot predictions.
The earlier benchmark remains frozen and previously consulted. Pilot outcomes
are descriptive development evidence; do not tune on the audit and continue
calling it held out. If it informs a change, a new untouched evaluation cohort
is required for the eventual claim.

The common frozen Kepler TRAIN normalization preserves the reference contract.
Thus “TESS-only” describes gradient training, not a completely source-free data
pipeline. Kepler-only checkpoint and temperature selection use Kepler validation
groups; the other arms use TESS validation groups. Fine-tuning pretrains from
scratch within its total budget and carries terminal pretraining weights forward.
It does not inherit the much larger frozen benchmark training budget.

## Remaining full-validation matrix

| Dimension | Required locked experiment | Current boundary |
| --- | --- | --- |
| Main comparison | Five arms, at least five seeds, matched updates/examples, converged budgets; paired star bootstrap | Bounded CPU pilot only; no convergence claim |
| Selection | Separate star groups for checkpoint selection, calibration, thresholding and untouched audit; prospectively freeze hyperparameters | Selection and thresholding share the selection subset; report that optimism |
| Normalization | Common reference versus per-arm TRAIN moments | Common source moments only |
| Label efficiency | TESS training labels at fixed 1/5/10/25/100% group fractions; repeated label draws | Full-label supervised adaptation first |
| Adversary | Zero-strength control, fixed lambda grid selected only on validation, independent frozen-encoder mission probe | Gradient correctness and head accuracy are engineering checks, not invariance proof |
| Uncertainty | Temperature, seed ensembles, reliability, NLL/Brier/ECE and group intervals; abstention without deleting candidates | Calibration scaffolding; no confirmation probability |
| Weak signals | Native-time injections before detrending across depth, duration, period, magnitude, crowding, sectors and transit counts | Existing small engineering controls are insufficient |
| False alarms | Disjoint realistic inverted/scrambled/systematic negatives; threshold freeze and independent rate/interval audit | Labelled nonplanet FPR is not survey false-alarm rate |
| Subgroups | Physical SNR/MES, magnitude, period, provenance, cadence, labels and rare failure classes | Legacy `bls_snr` is likelihood power, not physical SNR |
| Leakage | Source receipt hashes, host/proximity grouping, cross-mission overlap quarantine, label snapshot dates | Preserve existing audited grouping; wider coordinate/duplicate audit remains |
| Search transfer | Score blind-ephemeris injections and native control proposals; compare to known folds without tuning test data | New models remain outside the operational candidate scorer |
| Prospective test | Locked release/target selection and review budget on newly uninspected data; retain all failures/disagreements | Readiness remains false |

This matrix is not a claim that all rows are implemented. No result here supports
a new planet, improved discovery completeness, or a calibrated survey.
