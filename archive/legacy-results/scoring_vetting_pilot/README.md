# Blind proposals to trained scores and vetting dossiers

This is an engineering continuation of the [blind detection controls](../detection_pilot/README.md),
not a new search or a model-performance study. All 14 existing jobs completed the
feature/scoring/diagnostic/dossier stages once. All **38 proposals** received the
actual frozen Kepler CNN's scores: **11 known-object-control** proposals and
**27 synthetic/injected/transformed-control** proposals. No proposal was removed
by a model threshold, and no benchmark was retrained or used to select a model.

[summary.json](summary.json) records counts, model/normalizer/code hashes,
primary controls, catalog snapshot URLs/hashes/dates and scientific limitations.
Full local reports, input arrays and dossiers are under
`outputs/research/experiments/scoring-vetting-v1/`,
`outputs/research/artifacts/` and `outputs/research/reports/`.
The [implementation contract](../../docs/scoring_vetting.md) explains methods.

## Actual primary-control scores

These scores use independently detected ephemerides and one cached product per
star. They are **uncalibrated ranking values**, not probabilities of being planets.

| Control | Frozen CNN score | Supported-catalog result |
| --- | ---: | --- |
| TIC 231663901 / TOI-101.01 | 0.070007 | `CONFIRMED_PLANET`: compatible existing NASA record |
| TIC 149603524 / TOI-102.01 | 0.950730 | `KNOWN_PLANET`: compatible existing ExoFOP record |
| KIC 10666592 / K00002.01 | 0.006857 | Incomplete: verified KIC-to-TIC mapping unavailable |
| KIC 10748390 / K00003.01 | 0.008384 | Incomplete: verified KIC-to-TIC mapping unavailable |

Three of these four signals fall below the retained source-validation threshold
0.785. The threshold was not adjusted or applied as a rejection rule. This
illustrates why all signals retain a human-review route and why short-product,
blind-ephemeris inputs need separate calibration and controls. It does not
estimate population recall or demonstrate a mission-adaptation result.

The first TESS control visibly carries a **catalog/model disagreement** flag.
The source/star-group labels and previous control selection stay unchanged;
these selected training-group controls cannot support a generalization claim.

## Catalog and diagnostic evidence

An audited live batch queried exactly **two TICs**, reusing each snapshot for its
three proposals. Four source types were fetched or revalidated per target, with
**5,392,591 bytes** of catalog response content counted. No new light-curve/pixel
science product was downloaded. Six supported-catalog assessments completed:
one confirmed-planet identity match, one known-planet match, two unmatched and
two ambiguous matches. The other 32 proposals have explicit incomplete registry
evidence (Kepler identity mapping or synthetic-control scope).

`UNMATCHED` remains only a result against the supported snapshots. The extra
peaks are not new-planet claims; coordinate, TCE, eclipsing-binary and complete
literature checks are still missing. A known-record match does not independently
validate a detected proposal.

Dossiers retain event coverage, odd/even event comparisons, bounded secondary
phase scans, fixed-epoch harmonic comparisons, available native photometric
centroid measurements and pipeline crowding estimates. Their white-noise errors
and scanned secondary maxima are descriptive. Missing event support remains
incomplete. Difference images, nearby sources, aperture dependence and search
false-alarm/completeness validation remain incomplete for these records.

## Preservation and audit correction

All 14 input files, the frozen checkpoint and the Kepler TRAIN normalizer passed
hash preservation checks. Raw/normalized feature arrays, logits, checkpoint
identities, catalog bytes, stage attempts and review history are retained.
Completed job replay is idempotent; reports contain the actual source manifest
for the original processing, independently of later application updates.

An audit caught one **metadata label** error in the first adapter run:
`bls_duration` was described as days, while the reused legacy function returns
hours. Its numeric values and model inputs had always been passed through
correctly. The label was fixed in code/tests/documentation, and an explicit
append-only correction supersedes the shared-input metadata for all 38 proposals.
Original evidence remains in history. Arrays, scores and stage attempts were
verified unchanged; final dossiers were exported after the correction and live
catalog refresh. This correction is not a rescore or model adjustment.
