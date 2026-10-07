# Supermodel v2 in watcher scoring

The watcher has an adapter for the frozen **cross-fitted nonlinear supermodel v2**.
This is the eleven-expert candidate classifier that achieved 13/14 correct at
threshold 0.5 in the [fresh labelled audit](../results/fresh_classifier_audit_v1/README.md).
The similarly named neural event detectors are separate research models.

The initial detector/vetting job still records the Kepler reference CNN score.
The separate `scripts.research.supermodel_worker` consumes completed TESS jobs,
records a `supermodel_v2` shadow result, and in primary mode appends a new
`model_score` when all eleven expert inputs pass. The current API, candidate sort
and exported dossier use the newest `model_score`. Old scores, candidate IDs,
catalog evidence and human reviews remain intact.

## Inputs and identity

`configs/watcher_supermodel_v2.json` pins 114 artifact/source files across the CNN,
Transformer, morphology/variability, physical and nonlinear suites. The nonlinear
artifact SHA256 is
`487bc15021319dbf16d1a9b10c672b1d27491f398ccd02c6701f5245d1f355b7`.
The frozen normalization, expert order, physical transforms, meta-feature order,
tree model, static blend and calibration temperature are reused without fitting.
Model loading checks the pinned files before deserialization.

The worker reads the stored `shared_v1` input artifact and the exact recorded
native light-curve products. It takes period, epoch and duration from the **blind
proposal**, and masks only other blind proposals in that job. It never reads
catalog dispositions or catalog ephemerides for inference. Physical diagnostics
use the same frozen TLS and aperture/difference-image transforms as the audit,
with one matching 120-second SPOC target-pixel product. The earliest lexical
light-curve filename is selected when a job contains multiple products, consistent
with the physical training adapter's single-product selection convention.

Each result links its feature artifact, source hashes, physical measurements,
expert logits, available-input flags, model release and runtime source hashes.
The new adapter reproduced all fourteen fresh-audit combined logits to within
`4.5e-8` and every expert logit to within `1e-7` in the deployment replay.

## Primary and fallback behavior

- Primary promotion requires the exact v2 identity, all eleven experts, matching
  stored shared inputs, real TESS data and blind timing. A boolean eligibility
  flag alone cannot promote a result.
- Missing shared inputs, unsupported cadence, failed TLS, unavailable pixels or
  insufficient pixel coverage remain explicit gaps. The existing CNN score is
  retained as a labelled fallback when one is available. No score is invented
  when both paths lack valid inputs.
- Incomplete attempts are not retried continuously. An explicit `--retry` allows
  another attempt, capped at three per candidate/release. Successful shadow
  results and primary publication are idempotent.
- Missing experts can produce a diagnostic shadow output, but that output never
  becomes primary. The dashboard shows the current role, model and fallback reason.
- V2 uses a temperature fitted on its labelled calibration partition. Its output
  is still a ranking score, **not a validated blind-search planet probability**.
  The reference CNN calibrator is never applied to v2 logits. Different-model
  scores should be interpreted with their model identities and input coverage.

The 14-candidate audit is small and availability-selected. Its catalog-guided
input geometry differs from blind detections. Operational replay and integration
tests establish implementation behavior; they do not establish survey accuracy,
contaminant rejection, planet confirmation or a universal model winner.

## Bounded service and commands

From the repository root, first run a shadow batch:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m scripts.research.supermodel_worker \
  --mode shadow --limit 3 --allow-download
```

After reviewing shadow evidence and running the integration checks, start the
primary worker in its own persistent session:

```bash
tmux new-session -d -s exoplanet-supermodel-v2 \
  'OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -u -m scripts.research.supermodel_worker --mode primary --watch --limit 3 --allow-download >> outputs/research/supermodel/worker.log 2>&1'
```

The worker polls completed jobs every 60 seconds. CPU inference uses one thread;
each pixel acquisition has a hard 180-second subprocess bound, and physical
diagnostics default to 300 seconds (maximum 600). The shared database ledger
accounts for new target-pixel downloads under the existing **2 GiB cumulative
watcher budget**. Individual products are capped at 320 MiB; the worker retains
at least 128 MiB for normal watcher acquisition. An interrupted or failed download
is conservatively charged. The budget is never increased automatically.

Read `outputs/research/supermodel/service.json`, `/api/overview` or `/api/health`
for mode, heartbeat and score coverage. A heartbeat older than 120 seconds is
shown as stale. Stopping this worker does not stop BLS detection or CNN scoring.

For a candidate whose inputs have become available, stop the continuous worker
before an explicit bounded retry:

```bash
.venv/bin/python -m scripts.research.supermodel_worker \
  --mode primary --candidate-id CANDIDATE_ID --retry --allow-download
```

To roll back, stop only `exoplanet-supermodel-v2` with Ctrl-C and wait until it
exits, then run:

```bash
.venv/bin/python -m scripts.research.supermodel_worker --mode rollback
```

Rollback appends the retained reference values and preserves v2 history. It
does not delete or rewrite scores. Previously published shadow results are not
automatically re-promoted after an explicit rollback; investigate before issuing
a new deployment release.

The local Academy describes the deployed classifier and fallback separately from
the unchanged historical evaluation reports. Its content revision can change
without changing assessment IDs or resetting grades.
