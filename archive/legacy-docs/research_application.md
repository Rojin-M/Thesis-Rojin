# Local research application

The application provides a local store, HTTP API and review UI. A bounded local
blind BLS worker now attaches real light-curve proposals, plots and engineering
control results through the APIs below; see [blind detection](blind_detection.md).
The downstream [scoring/vetting worker](scoring_vetting.md) now constructs shared
inputs, applies the retained trained CNN and attaches catalog/diagnostic evidence.
The separate bounded watcher/dispatcher polls MAST and acquires explicit public products. A separate [five-arm experiment interface](mission_adaptation_experiments.md) now trains comparators and DANN and publishes verified local reports on the Models page. Fresh stores start empty. Populated stores
show only their actual persisted records and explicit experiment cohorts.

## Architecture and operation

`scripts/research/` is a small Python package with no new runtime dependencies for
the web application. `store.py` owns SQLite transactions; `artifacts.py` owns
immutable bytes and plot previews; `server.py` serves a fixed set of static files
and JSON endpoints; `reports.py` exports dossiers; `protocol.py` validates the
versioned scientific/resource policy. The feature-contract guard imports the
existing NumPy only when called. HTTP request handlers never load a model.

The application uses SQLite schema version 1, foreign keys, a 10-second busy
timeout, and short serialized write transactions. It intentionally uses rollback
journalling rather than WAL because the project may live on a shared filesystem.
Run the service and workers on one host with working filesystem locks. This is a
single-user development application, not a distributed queue or an authenticated
public service. The database can move to host-local storage with `--db` if the
filesystem cannot provide reliable SQLite locking. Do not copy a live database
file as a backup; use SQLite's backup API.

An additive `processing_runs` table pins downstream code, model hashes, settings
and processing timestamps independently of an earlier detector's source version.
`freeze_processing_run` is atomic: the same job/worker identity reuses its record;
different source/model/settings cannot silently replace an unfinished run.

```bash
.venv/bin/python -m scripts.research init
.venv/bin/python -m scripts.research serve --host 127.0.0.1 --port 8766
.venv/bin/python -m scripts.research status
```

Open `http://127.0.0.1:8766` through an SSH/VS Code port forward. The Academy uses
its independent port 8765. Defaults are:

- Database: `outputs/research/research.sqlite3`.
- Artifact directory: `outputs/research/artifacts/`.
- Protocol: `configs/research_protocol_v1.json`.
- Research server log (when launched in tmux): `outputs/research/server.log`.

Global CLI flags `--db`, `--artifacts`, `--protocol` precede the subcommand. Every
startup validates the protocol and registers its canonical JSON SHA-256. Existing
jobs continue to reference their original snapshot. Changing configuration does
not rewrite old jobs or candidate dossiers. Serving does not start processing or
enable downloads.

For an explicitly synthetic, separate demonstration database:

```bash
.venv/bin/python -m scripts.research \
  --db outputs/research/fixture-demo/research.sqlite3 \
  --artifacts outputs/research/fixture-demo/artifacts seed-fixture
```

The fixture has labelled artificial light curves, assigned ephemerides, no CNN
score, no catalog query, and a deliberate nonretryable failure. Calling the
command again is idempotent. It is never seeded by normal startup. Its contents
must not be reported as detections, successful recovery tests or public data.

## Pipeline integration API

Use Python APIs for pipeline writes; the browser can only review or request a
bounded retry. No mutation endpoint accepts arbitrary paths, commands, downloads
or model execution.

```python
from scripts.research.store import Store
from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import load_protocol
from scripts.research.provenance import register_code, file_sha256

store = Store("outputs/research/research.sqlite3").initialize()
protocol = store.register_protocol(load_protocol())
code = register_code(store)
artifacts = ArtifactStore("outputs/research/artifacts", store)
```

`register_code` captures Git HEAD, working-tree dirtiness, Python version and
per-file hashes of code, static assets and configuration, including untracked
source files. Git HEAD alone is not sufficient for an uncommitted overnight run.

The stable write interfaces are:

| Method | Required data and behavior |
| --- | --- |
| `register_provenance(kind=…, identity=…, sha256_digest=…, retrieved_at=…, details=…)` | Immutable record of actual source/model/code bytes and an explicit timezone-aware retrieval timestamp; returns `id`. Put source version, endpoint, receipts and environment information in `details`. |
| `register_release(mission=…, release_key=…, available_at=…, provenance_id=…, metadata=…)` | Unique `(mission, release_key)`; caller must supply evidence of actual public availability, never just a scheduled date. Immutable first observation. |
| `register_product(release_id=…, product_key=…, target_id=…, source_uri=…, provenance_id=…, metadata=…)` | Unique `(release_id, product_key)`; record exact archive product/version identity and selection metadata. A URI is stored, never fetched by this layer. |
| `create_job(job_key=…, cohort=…, protocol_id=…, code_provenance_id=…, inputs=…, release_id=…, product_id=…)` | One versioned key for an immutable processing request. The same key and content returns the existing job; differing content raises `ConflictError`. |
| `claim_stage(job_id, stage_name, worker=…, lease_seconds=900)` | Atomically returns stage data including `lease_token`; returns `None` if already succeeded/skipped. A busy stage or unmet prerequisite raises `ConflictError`. |
| `heartbeat(token, lease_seconds=900)` | Extends only an unexpired, current lease, up to 3600 seconds. Long processing must heartbeat before expiry. |
| `finish_stage(token, result={…})` | Commits success only for a live lease. Repeating the same token/result is idempotent. |
| `finish_stage(token, error={"code": …, "message": …, "retryable": True/False})` | Stores an observable failure, preserving the full attempt record. |
| `retry_stage(job_id, stage_name, actor=…, reason=…)` | Explicitly queues a retryable failed stage below its attempt cap. No attempt history is erased. |
| `skip_stage(job_id, stage_name, actor=…, reason=…)` | Explicitly skips an unattempted queued stage after prerequisites; useful for a justified local control. Skipping does not mark candidate evidence complete. |
| `recover_expired()` | Requeues expired leases until the attempt cap; then leaves a failure. Records abandoned attempts. Active leases are never reset at restart. |

Stages run in order: `metadata`, `selection`, `acquisition`, `detection`,
`features`, `scoring`, `diagnostics`, `dossier`. A completed stage cannot be rerun
in place. Version the job key for changed inputs, code, protocols or methods.

For release polling, retain the first observation record and add new provenance
snapshots for revalidations. Do not re-register the same release identity with a
different provenance ID: immutable identity conflicts are deliberate. Use
`list_records("releases")` / `list_records("products")` with bounded pagination
to retrieve known identities. The separate `WatchStore` now supplies cumulative
byte/target accounting, frozen selections and durable reservations. The base
store still performs no network I/O itself.

Do expensive work outside SQLite transactions. Publish each deterministic output
using an immutable key and pass `lease_token` to `put_candidate`, `put_evidence`
and `ArtifactStore.put_bytes` / `put_plot` when called by a worker. This fences out
stale workers. The optional token is omitted only for deliberate local imports
or fixtures. If a worker dies after publishing output but before completion, its
replacement must reuse the output keys and identical content, then finish the
stage. If it discovers a different result, fail visibly and create a new job.
Candidate records written before a crash stay visible with the unfinished job.

## Candidate, evidence and artifact contracts

```python
candidate = store.put_candidate(
    job_id=job_id, signal_key=signal_key, target_id=target_id, mission="TESS",
    period_days=period, epoch=epoch_btjd, epoch_system="BTJD",
    duration_hours=duration, provenance_id=detection_provenance_id,
    detection={"method": "BLS", "ephemeris_origin": "blind_search",
               "used_catalog_ephemeris": False},
    lease_token=token,
)
```

The example describes the interface used by the bounded blind BLS worker.
`signal_key` is unique within its job. Do not use float formatting alone to merge
signals across jobs; later detection code must document period/epoch alias and
cross-product association rules. Original ephemeris values are retained, with a
canonical absolute `epoch_bjd_tdb`. Accepted systems are `BJD_TDB`, `BTJD`
(+2457000 days), and `BKJD` (+2454833 days), all TDB days. Period is days and
duration is hours. No implicit UTC or unknown-offset conversion is allowed.

Jobs belong to one of `synthetic_fixture`, `known_object_control`,
`archival_pilot`, or `prospective_search`. Catalog ephemerides require
`ephemeris_origin="catalog_control"` in a known-object-control job. Synthetic
ephemerides require a synthetic job. The current provisional protocol refuses
prospective jobs; enabling that requires a reviewed protocol/schema evolution
after controls, isolation and availability checks.

`put_evidence(candidate_id=…, evidence_key=…, kind=…, state=…, summary=…,
payload=…, provenance_id=…, lease_token=…)` appends immutable evidence. States are
`complete`, `incomplete`, `failed`, `not_run`. The latest inserted record per
kind is the current assessment; all earlier records remain in the dossier.
Use a new, versioned `evidence_key` for a refresh. Complete evidence requires
nonempty recorded values and provenance; absent required categories remain
incomplete. `complete` means evidence was recorded, not that a signal passed a
scientific test. A diagnostic that finds an eclipsing binary can be complete.

The required kinds are `lightcurve`, `detection`, `shared_inputs`, `model_score`,
`transit_diagnostics`, `centroid`, `contamination`, `registry`, and `controls`.
Additional named diagnostics are supported.

- Complete `model_score` payloads require `score` in [0,1], `model_sha256`,
  `normalization_sha256`, and `input_contract="shared_v1"`. Describe calibration,
  uncertainty and out-of-distribution limitations separately. A sigmoid score is
  not a confirmation probability.
- Complete `registry` evidence requires a recorded `status` and
  `required_sources_complete=true`. `INCOMPLETE_LOOKUP` cannot be complete.
  Preserve the checker's snapshots/report rather than converting lookup failure
  into `UNMATCHED` or a false positive.
- `review_candidate(id, status=…, reviewer=…, note=…, expected_revision=…)`
  accepts `unreviewed`, `in_review`, `on_hold`, `follow_up`, `rejected`. Each write
  increments a revision and appends audit history; stale browser edits conflict.
  There is no automated confirmation or novelty label. Review never changes
  evidence completeness or a job's failure state.

Attach bytes through `ArtifactStore.put_bytes(payload, candidate_id=…,
artifact_key=…, kind=…, filename=…, media_type=…, metadata=…, lease_token=…)`.
Artifacts have a 64 MiB individual cap, owned content-addressed paths, atomic
file replacement, size and SHA-256 receipts. HTTP reads verify both size and
hash. Missing/corrupted bytes are a visible error. Uploaded HTML/SVG is not
served. JSON/text/CSV/images/binary downloads use attachment disposition.
This is not an aggregate scientific-download budget; the watcher separately enforces
the cumulative 2 GiB bound independently.

`put_plot(value, candidate_id=…, artifact_key=…, filename=…, metadata=…,
lease_token=…)` accepts paired finite `x`/`y` lists (2–20000 points), `title`,
`x_label`, `y_label`, and `kind` (`time_series`, `phase_folded`, `periodogram`,
`diagnostic`). Time series also require `time_system` and sorted times. Provide
an explicitly bounded scientific preview and record `full_points`,
`preview_points`, and any reduction method in metadata. The server renders all
preview points as safe SVG and links the exact plotted JSON; it does not silently
thin away transits. Keep full arrays as separate binary artifacts when needed.

## Existing data/model interface

Do not call `prepare_shared_star` as a blind detector. It protects **known**
ephemerides in detrending and folds at them. New proposals must estimate period
and epoch independently before shared feature construction.

`scripts.research.contracts.validate_shared_inputs(arrays)` guards the raw,
batched `float32` contract: `X_global (N,200,3)`, `X_local (N,100,3)`,
`X_scalar (N,7)`, and `X (N,907)`. The flat vector concatenates channels before
bins (global, local, scalars); ordinary interleaved `.reshape` is wrong.
Use `scripts.data.tess_dataset.apply_normalization` with the saved Kepler
training moments. Its outputs `x_global`, `x_local`, `x_scalar`, `x_flat` feed
`ExoMinerStyleCNN.forward` in that order. The model performs its own view-axis
transpose. The retained checkpoint keys include `model_state`, `model_config`,
`config`, `val_threshold`, `epoch`, and `val_pr_auc`.

The local reference pointer is `outputs/shared_cnn/kepler/run.json`; arrays,
splits, provenance and normalization live under each mission's
`data/processed/<mission>/shared_v1/`. Do not replace these artifacts or refit
normalization to prospective data. The legacy scalar named `odd_even` compares
alternating **phase bins**, and `bls_snr` contains BLS likelihood power. Preserve
those names for checkpoint compatibility, but compute genuine transit-event
odd/even and detection SNR diagnostics separately with accurate labels.

## HTTP and exports

Read endpoints: `/api/health`, `/api/overview`, `/api/protocol`, `/api/session`,
`/api/jobs`, `/api/jobs/<id>`, `/api/candidates`, `/api/candidates/<id>`,
`/api/releases`, `/api/products`, `/api/provenance/<id>`,
`/api/artifacts/<id>`, `/api/artifacts/<id>/plot.svg`, and
`/api/candidates/<id>/report.json` or `.md`. Lists support `limit` (1–200) and
`offset`; job/candidate lists support `cohort`, candidate lists `review_status`.

Write endpoints accept JSON with exactly these fields:

- `POST /api/candidates/<id>/review`: `status`, `reviewer`, `note`,
  `expected_revision`.
- `POST /api/jobs/<id>/retry`: `stage`, `actor`, `reason`.

Writes require the exact loopback `Host`, matching `Origin`, and
`X-CSRF-Token` from `/api/session`; browsers also receive a restrictive CSP,
no CORS access, and no external assets. Request bodies are capped at 64 KiB,
socket timeouts at 10 seconds, and concurrent HTTP handlers at four. An accepted
connection waits at most two seconds for a handler, with a bounded socket backlog;
ordinary concurrent plot requests are queued before overload receives HTTP 503. All science
I/O is outside the server. Keep the service on `127.0.0.1`; an SSH tunnel is for
the user's own browser, not a public deployment.

The JSON and Markdown dossier includes the candidate, job stages/attempts,
protocol snapshot, current evidence and history, reviews, source provenance,
artifact receipts and interpretation cautions. Artifacts remain separate files
linked by local API ID; the report is not a self-contained data archive.

```bash
.venv/bin/python -m scripts.research export CANDIDATE_ID \
  --format md --output outputs/research/reports/CANDIDATE_ID.md
.venv/bin/python -m scripts.research recover
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m unittest discover -s tests -v
```

Exports refuse overwrite. `recover` changes only expired leases; it does not
start a worker. Tests use temporary databases and labelled synthetic records.
HTTP tests open actual ephemeral loopback sockets and deliberately fail, rather
than skip, if execution permissions prevent HTTP testing.

## Remaining integration work

Scoped public metadata, frozen selections, cumulative reservations, verified
acquisition and a finite dispatcher are now implemented. Blind BLS, shared features,
trained-model scores, bounded catalog checks, transit diagnostics and small
control results are now connected. TLS, pixel extraction and complete image/
contamination/coordinate/TCE/EB/literature checks remain outstanding.
Multi-seed DANN/comparator experiments, calibrated uncertainty and prospective
science validation remain separate research milestones.

## Public-product integration

The bounded [MAST watcher and explicit dispatcher](release_watcher.md) now implement
scoped public metadata, immutable product/release observations, acquisition
receipts and cumulative budget reservations. `/api/watcher` exposes actual health
and progress. Serving alone still starts no scientific processing.
