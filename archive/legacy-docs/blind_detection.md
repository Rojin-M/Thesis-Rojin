# Bounded blind light-curve pilot

`scripts.research detect` searches explicit local native TESS/Kepler light
curves. It estimates period, mid-transit epoch, duration and depth with no
catalog ephemeris argument. It then attaches real artifacts and evidence to the
SQLite research application. The website does not launch a background worker;
serving remains read-only except for human reviews and retry requests.

This is an engineering pilot on archival products and labelled controls.
Prospective work is disabled by the provisional protocol. No pixel extraction,
TLS or trained scoring is implemented by this detection worker itself. Separate
[watcher/acquisition](release_watcher.md) and [scoring/vetting](scoring_vetting.md)
workers now connect these stages. The cached-public-product adapter selects only local products
from the existing MAST manifest. It does not imply that a scheduled sector has
been released, revalidate current availability, or create fictitious releases.

## Inputs and provenance

Examples and commands are in the README. Explicit FITS sources must have the
requested native TICID or KEPLERID, barycentric TDB day headers, BJD reference,
PDCSAP flux/errors and mission quality flags. TIMEZERO and BJDREFF are respected.
Kepler BKJD and TESS BTJD are converted to internal BTJD; the candidate store
also retains the absolute BJD TDB epoch. CSV/NPZ inputs have operator-asserted
identity and require an explicit time system. Arbitrary time values are never
guessed from their magnitude. Pickled NPZ content is forbidden.

Each source is read as a bounded byte snapshot, SHA-256 hashed, and interpreted
from those same bytes. Original TESS acquisition receipts are verified and
retained if present. Legacy Kepler original retrieval dates are unknown; local
verification dates and source file modification dates are labelled separately.
Product basenames, sectors/quarters, native cadence, pipeline/data-release
headers, source URIs, quality counts and checksum receipts are preserved.

FITS CHECKSUM/DATASUM are checked over the original serialized bytes, including
padding, before loading table columns. This also handles mission CHECKSUM-only
headers without Astropy 6's absent-DATASUM assumption. The algorithm follows
the [registered FITS checksum convention](https://fits.gsfc.nasa.gov/registry/checksum.html).
Sources without those optional headers still have recorded SHA-256 snapshots;
that records local identity, not independently verified archival authenticity.

The local reader accepts at most 20 files, 64 MiB per file, 512 MiB in a selection,
250,000 usable samples and 400 days of baseline. Duplicate timestamps use the
first sample in sorted product-path order, recorded explicitly. Quality must be
zero, flux/error finite and positive. Negative transit excursions are not clipped.
Original data, processed benchmark arrays and model artifacts are never modified.

## Search and scientific limits

The installed Astropy BLS implementation is used, with its version stored per
result. [Astropy's BLS documentation](https://docs.astropy.org/en/stable/timeseries/bls.html)
describes the likelihood objective and sensitivity to period-grid spacing.
The search has its own versioned configuration, separate from the frozen shared
feature preparation. No known transit masks enter blind detrending.

1. Each product and gap segment is divided by a 1.5-day rolling median, requiring
   at least 15 supported samples. Formal uncertainties are scaled by the trend;
   a robust adjacent-difference white-noise floor avoids using underestimated
   formal errors as excessive weights. This does not model correlated noise.
2. An ascending period grid uniform in frequency covers 0.5 days to the smaller
   of 30 days and baseline/(minimum events − 1). Eight strongest local coarse
   peaks are refined within the fixed total budget of 20,000 periods per round.
   Six durations (0.75, 1.25, 2, 3, 4.5, 6 hours) are tested. The runtime record
   flags a coarse grid that exceeds the shortest-duration frequency heuristic.
   Refinement cannot recover peaks absent from the coarse selection.
3. The top positive-depth peak is retained with alternatives and aliases.
   Its windows are masked by 1.5 times the fitted duration, with at most three
   rounds. Period commensurability and epoch alignment jointly identify repeated
   harmonics; suppressed peaks remain in the search record. This is a heuristic,
   not definitive identification of the physical orbital period.
4. Each proposed ephemeris receives sampled-event counts, per-event depth/errors,
   in-transit coverage, baseline support on both sides, genuine odd/even *event*
   depths, a phase-half secondary test, and single-event S/N dominance flags.
   These do not reuse the legacy CNN scalar named `odd_even` (alternating bins).
   Sampling support is not evidence that an event is astrophysical.

A single owned CPU subprocess enforces a hard 300-second wall-clock deadline,
including compiled BLS calls; grid chunks also check a deadline. It is terminated
on timeout and its failed attempt remains visible. Use one BLAS/OpenMP thread as
shown in the README. This path uses no GPU, model checkpoint or paid API.

No significance cut removes proposals. Noise peaks are expected and preserved.
Missing centroid, difference-image, contamination, registry, feature, model or
control evidence remains incomplete. Long/high-duty-cycle events may be attenuated
by blind detrending. Searches with coarse grid limits, data gaps, masking losses
or too few sampled events are not silently claimed complete. TLS is explicitly
`not_run`; its dependency is absent in the reference environment.

## Persistence and next-stage contract

`run_local_detection(store, artifacts, protocol_id, paths=..., mission=...,
target_id=..., cohort=..., config=..., time_system=..., experiment=..., job_key=...)`
creates an immutable request and executes metadata, selection, acquisition and
detection through the existing stage leases. Source bytes, settings, cohort,
protocol and a full current source manifest determine the default identity.
Changed inputs/code produce a different default job. An explicit key may only
resume identical inputs; changed code cannot resume an unfinished job. Completed
jobs are reused without calling BLS. A browser retry queues the failed stage;
the operator must rerun the same CLI command to execute it.

Candidate/artifact/evidence keys are deterministic. If publication stops between
candidate creation and stage completion, retry reuses the same candidate and
identical blobs. Failures are persisted; completed detection leaves `features`
and later stages queued for the next worker, not falsely marked successful.

Each proposal includes:

- `detection.method=blind_bls_v1`, `ephemeris_origin=blind_search`,
  `used_catalog_ephemeris=false`, explicit experiment/cohort labels;
- period in days, duration in hours, original BTJD and absolute BJD TDB epoch;
- light-curve and detection evidence, incomplete transit/control diagnostics;
- plots of detrended flux, raw normalized flux, trend, folded flux, local transit
  samples, coarse periodogram and individual-event depths;
- `blind-search-lightcurve.npz`: `time_btjd`, `flux`, `flux_err`, `segment`,
  `time`, `flux_raw_normalized`, `trend_normalized`, `flux_err_formal`, and full
  coarse `bls_N_periods`/`bls_N_power` arrays for each round;
- a JSON search report with diagnostics, aliases, grid limitations and versions.

Plots with over 10,000 samples retain the minimum and maximum per ordered bucket;
the preview-reduction rule and counts are recorded. Full arrays are available
through the artifact download link. These arrays are **not normalized shared_v1
model inputs**. Stage 03 must construct the 200×3/100×3/seven-scalar contract using
the inferred ephemerides and frozen training normalizer, recording hashes and
any departure from known-ephemeris preprocessing. Do not re-fit normalization or
model-selection thresholds on the consulted test set. Input features and model
scores remain visibly absent until that work runs.

## Control experiment

`detection-controls --output <new-versioned-directory>` fixes the configuration
and code manifest before processing. It selects two distinct TRAIN-positive
stars per mission sorted by candidate ID, restricted to catalog periods 0.5–10
days and durations below six hours for this small engineering exercise. It checks
that no selected star belongs to a held-out group. This selected sample is not
representative of survey performance. TESS uses the first cached sector; Kepler
uses the first cached quarter with at least 20 days of usable span.

Six box injections (periods 2.731/5.173 days, depths 0.0005/0.002/0.008, duration
2.4 hours) multiply real quality-filtered TESS flux **before** blind detrending.
Original signals remain; recovery is assessed among up to three blind proposals.
The four negatives are flux permutation, flux inversion and two fixed-seed
white-noise realizations on the same real timestamps. Transformed photometry is
stored separately and labelled synthetic; parent source paths/hashes remain
attached. Inverted data are not guaranteed planet-free, and permutation removes
correlations, so these do not establish a controlled false-alarm rate.

Only post-search evaluation sees truth. Direct recovery requires relative period
error ≤0.005, accumulated drift across the observed span ≤one true duration, and
phase error at the observed epoch ≤half the larger duration. Harmonics are
reported separately. S/N 7.1 is a predeclared descriptive reference, not a tuned
threshold or a planet-selection rule. Reported failures and high-scoring negatives
are retained. Scientific readiness stays false regardless of these outcomes.

`experiment.json` freezes the configuration and selected sources; `progress.json`
retains partial outcomes; `report.json` contains all results and is attached to
every control dossier on successful completion. The small experiment is useful
for detecting implementation failures, not estimating weak-signal completeness,
ranking a model, or claiming improved performance.
