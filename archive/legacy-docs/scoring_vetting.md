# Blind proposal scoring and evidence dossiers

The `vet` worker advances existing, completed `blind_bls_v1` jobs through shared
features, actual frozen CNN inference, diagnostic measurements, catalog checks
and persisted dossiers. It does not rerun detection, fit a normalizer, train a
model or select thresholds. The worker is CPU-only and processes explicit jobs
sequentially. Every proposal remains reviewable, including feature failures and
low model scores. The HTTP server does not start compute or network workers.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research vet \
  --job-id be6c782ecb084da4b16e7cda4cebbd41 --catalog-mode offline
```

Repeat `--job-id` for at most 20 explicit jobs. Completed jobs are no-ops on
restart. `--retry-failed` explicitly queues retryable downstream stage failures
within the original attempt limit; it never erases attempts or reruns completed
stages. A source/model/settings change cannot replace an unfinished processing
run: make a new versioned job. `processing_runs` is an additive SQLite table
created by normal store initialization, preserving all existing records.

## Shared feature and trained-model contract

1. Reopen the exact native/local inputs recorded by detection and verify their
   SHA-256 receipts, identity, quality and time systems.
2. Apply the existing `shared_v1` gap/product-local detrending with transit
   protection at **inferred** ephemerides. Other inferred proposals are masked
   before each candidate fold. Catalog ephemerides never enter this adapter.
3. Reuse the original 200-bin global / 100-bin local / seven-scalar construction
   and sampling requirements. Store raw float32 arrays, coverage and channel-major
   907-feature vectors. Insufficiently sampled inputs produce explicit incomplete
   evidence, without inventing a score or removing the proposal.
4. Preserve the legacy `odd_even` feature (alternating local **phase bins**) and
   `bls_snr` (star-level **likelihood power**, not depth S/N). It returns
   `bls_duration` in **hours** and `bls_period` in **days**; its numeric outputs
   are passed through without conversion. The original search uses 2000 linear
   periods and 20 durations. This expensive operation
   runs in one owned subprocess with a hard maximum 300-second deadline.
5. Apply the saved **Kepler TRAIN** moments via `tess_dataset.apply_normalization`.
   Store normalized inputs separately. Load the actual pinned checkpoint with
   strict parameter shapes, weights-only deserialization and SHA-256 checks;
   run evaluation/inference mode, in batches of up to 32 (library cap 64).

The reference checkpoint is
`outputs/shared_cnn/kepler/dataset_kepler_shared_v1_cnn_20260915_080811/best_model.pt`,
SHA-256 `7890efd17fc072efb74465a9fbfa6fb8b0192388d91af520961349f0066ba703`.
The normalizer is
`data/processed/kepler/shared_v1/kepler_train_normalization.npz`, SHA-256
`6f4ac773f6f2dd6c2200e68b903acb0c7a3f585a593ac2d882c03af03c705dc1`.
Checkpoint epoch 44 and its source-validation threshold 0.785 are recorded,
not reselected. No benchmark/test data are used for model or threshold selection.

Each score records a raw logit, sigmoid **ranking score**, model configuration,
normalizer/model hashes, input artifact IDs, source versions and normalization
scope. Calibration and uncertainty are explicitly unavailable. The single model
cannot yet measure disagreement between planned comparator models. Below-source-
threshold scores, current catalog/model disagreements, unusual transit warnings
and missing evidence receive visible review flags; none is an automatic veto.

This adapter shares feature semantics with the benchmark, but **inferred** masks
and limited product coverage differ from catalog-protected labelled inputs.
False proposals may mask useful samples; unmasked detector arrays remain in the
dossier. Scores on the selected TRAIN-star controls cannot establish generalization.

## Diagnostic measurements and limits

- Sampling includes individual events, baseline coverage and proximity to
  observed gaps/product edges. It is not a spacecraft-event catalog check.
- Odd/even diagnostics group real transit **events**. They retain the original
  white-noise measurement and add a descriptive event-scatter error floor when
  at least two covered events exist per parity. Missing support stays incomplete.
- A maximum 97-phase secondary-event scan excludes the primary window and keeps
  the inferred duration fixed. The phase-half measurement remains available.
  No trials-factor or red-noise false-alarm claim is made.
- P/2, P, 2P and 3P fixed-epoch/depth comparisons complement the detector's
  recorded harmonic relations. These are diagnostic views of the same data,
  not independent searches or a significance-based alias selection.
- Native `MOM_CENTR1/2` columns, when available, yield local in-minus-out event
  centroid shifts in pixels. `CROWDSAP` and `FLFRCSAP` are retained as pipeline
  aperture estimates. Their presence does not complete source localization,
  difference imaging, nearby-source or aperture-dependence evidence. No extra
  crowding correction is applied to already processed PDCSAP flux.

Methods and column semantics were checked against primary documentation:
[Astropy BLS](https://docs.astropy.org/en/stable/timeseries/bls.html),
[TESS data product description](https://archive.stsci.edu/files/live/sites/mast/files/home/missions-and-data/active-missions/tess/_documents/EXP-TESS-ARC-ICD-TM-0014-Rev-F.pdf),
and [NASA TESS crowding tutorial](https://heasarc.gsfc.nasa.gov/docs/tess/UnderstandingCrowdingv2.html).
The runtime package versions are recorded; following current documentation does
not change the frozen local implementation.

## Registry snapshots and refresh

The existing checker compares period and **absolute BJD TDB** epoch against
ExoFOP TOI/cTOI and NASA planet/TOI records. The public lookup is TIC-based.
Kepler proposals without a verified TIC mapping remain incomplete; KIC numbers
are never sent as TIC IDs. Synthetic/transformed experiments skip public lookup
and retain an explicit incomplete/not-applicable explanation.

```bash
.venv/bin/python -m scripts.research refresh-registry \
  --candidate-id ad179520bad644d1b136da2b2defe9bf --catalog-mode live
```

Repeat candidate IDs for at most 60 proposals on at most 20 explicit TICs. For
an initial live control, choose only one or two TICs. A batch reuses each TIC's
snapshot across its proposals and serializes cache refreshes with a filesystem
lock. Each target has a hard 180-second deadline, at most two attempts per source,
5-second connect / 10-second read timeouts, 16 MiB per response and 64 MiB per
refresh. Raw response bytes, URLs, retrieval dates, hashes and report snapshots
are persisted under `outputs/research/registry/` and the candidate artifact store.
No API key, submission or notification is used.

Complete bundles are reused for up to 24 hours; failures for 15 minutes.
`--force --catalog-mode live` makes a deliberate bounded retry/revalidation.
Offline mode reuses verified fresh bundles; expired or imported legacy snapshots
are marked stale, and unavailable required catalogs never produce `UNMATCHED`.
Corrupt cache bytes are rejected. A current NASA known-planet match can coexist
with **incomplete** discovery-catalog coverage. Coordinate, TCE, eclipsing-binary
and literature searches remain outside this limited checker's coverage.

Refreshing appends evidence without resuming completed compute stages. Candidate
API/Markdown exports show current evidence and review flags. Attached stage
dossiers are clearly timestamped snapshots and can predate a later refresh.

## Verification

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m unittest tests.test_research_vetting \
  tests.test_research_vetting_http -v
```

These tests use temporary labelled synthetic stores, real detection/feature
functions and, when locally present, the actual retained trained checkpoint.
They exercise feature/normalizer equality, time systems, useful and unavailable
diagnostics, cache freshness/corruption/retry, partial publication restart,
checksum failures and HTTP reports/plots/review. Public registry responses are
explicit offline fixtures. The loopback HTTP tests require socket permissions.
