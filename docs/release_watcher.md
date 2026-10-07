# Bounded public-release watcher

## Automatic website watcher

An opt-in automatic service connects bounded target discovery and metadata
polling to acquisition, blind detection, CNN scoring, diagnostics and saved
dossiers. For new archival targets, use `configs/research_discovery_v1.json`.
This schema-2 configuration has `targets: []`, a `discovery` settings object and
`cohort: "archival_pilot"`; the discovery selection supplies its target IDs.
The older `configs/research_automation_v1.json` remains a schema-1 explicit list
of TIC 231663901 and TIC 150428135, both known-object controls. Its existing
results are historical controls, not results of the new archival discovery run.
The older metadata-only interface below remains available.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research watch-auto-serve \
  --config configs/research_discovery_v1.json
.venv/bin/python -m scripts.research watch-auto-check
```

The first command is a foreground worker, normally launched in tmux. It runs
until stopped; `--max-hours` optionally limits its lifetime. The second queues a
durable check for the active worker, equivalent to **Check for new data** in the
website. With discovery enabled and selection capacity remaining, the check
requests a fresh bounded search for additional targets. It also requests
processing of eligible selected products. Once selection is full, the saved
target list is reused; repeated clicks do not enlarge the batch or its budgets.
`watch-auto-once --config configs/research_discovery_v1.json --force` runs a
single automatic cycle when the service is stopped. The service lock prevents
overlapping metadata/automatic schedulers. See the [website guide](website_guide.md#start-the-website-and-watcher)
for tmux startup commands using this configuration. Stop an existing worker and
wait for it to exit before switching configurations; a running worker retains
the configuration with which it started.

The browser reloads list/dashboard results every 30 seconds while visible and
idle. Focused/edited forms pause updates; candidate review pages never refresh
automatically. A protected POST `/api/watcher/check` accepts only `{}` and requires
the existing same-origin and CSRF checks. It records a request without launching
work in an HTTP handler. Pending requests coalesce and survive worker restarts.

Archive metadata checks use a six-hour interval. Eligible existing queue work
is processed on every worker cycle, even when the metadata result is `not_due`.
That status describes the metadata schedule, not necessarily an idle cycle.
The explicit watchlist mode polls in stable batches of two targets so lists
larger than two do not starve. Only complete successful snapshots can feed
automatic selection.
Each unqueued product gets one immutable pilot; subsequent releases get different
identities. Repeated polls, requests and restarts reuse completed results.
Dispatch respects existing stage leases, retry deadlines, attempt limits and
cumulative byte/product/runtime budgets. An independent heartbeat stays current
during processing. Terminal failures remain visible instead of appearing idle.

Automatic products use the retained offline-first scoring/diagnostic path, then
refresh supported registry evidence when `catalog_mode` is `live`. Each registry
refresh reserves up to 64 MiB in the existing global ledger before network work;
unknown interrupted usage stays conservatively charged. Assessments and failed
refresh attempts are retained for 24 hours to avoid repeated network work;
cached errors remain visible. Unavailable catalogs produce incomplete evidence.

Discovery selects targets from a bounded public standard SPOC metadata search;
it does not scan all TESS pixels or provide a complete archive census. Its source
exclusions include TIC IDs in local processed/raw TESS sources, the recorded
Kepler overlap, and local candidate IDs. Known catalog periods and epochs do not
select targets or seed detection. The resulting `archival_pilot` proposals are
separate from the two historical known-object controls. An unmatched registry
assessment is not evidence of a newly discovered planet.

The existing **20-product and 20-target initial selection limits and 2 GiB byte
cap** apply cumulatively across the database, including earlier control work.
Two previously selected control products/targets leave at most **18 new
product/target slots**; the remaining byte allowance may be more restrictive.
Restarts and repeated checks do not reset the ledger or attempts. Existing pilot
membership stays frozen as new selections are recorded.

The Watcher discovery card reads `automation.discovery` and shows the latest
selection, selected TIC IDs, bounded scope, remaining budget, exhaustion and
errors. Source or budget exhaustion remains visible and does not imply that the
entire public archive has been searched. This feature does not establish
prospective search readiness or planet confirmation.
“Latest batch that added targets” records the last selection event; selected
targets are not counts of completed products or signal proposals. The discovery
budget is captured at selection time; the global budget below includes later
processing charges. At most two products are processed per cycle.

On this installation, the private `forme/WEBSITE.md` guide and `forme/website.sh`
helper provide exact start, open, refresh, status and stop commands.

## Original metadata-only interface

The metadata-only watcher queries the official MAST CAOM API for an explicit TIC
watchlist, records observed public SPOC light-curve products, and exposes health,
errors, provenance and a finite processing queue at `/#watcher` and
`/api/watcher`. Metadata polling **never creates a download pilot**. A separate
CLI command freezes explicit observed product IDs and resource bounds.

## Authoritative API and actual scope

The [MAST API tutorial](https://mast.stsci.edu/api/v0/MastApiTutorial.html)
documents POST requests to `/api/v0/invoke`, `Mast.Caom.Filtered`, observation
`obsid` values, `Mast.Caom.Products`, and direct product retrieval. The
[observation field definitions](https://mast.stsci.edu/api/v0/_c_a_o_mfields.html)
and [product fields](https://mast.stsci.edu/api/v0/_productsfields.html) define
public rights, release metadata, sectors, product URIs, sizes and versions.
These APIs were verified against live metadata on 22 September 2026 (Vienna).

The original metadata-only version 1 requests at most one page of 100
observations, then at most two pages
of 100 products (three API calls maximum per poll). It chooses the latest
**standard SPOC light curve per explicitly listed TIC**, according to public
release metadata. Fast-cadence, DV, pixel, FFI and HLSP products are outside this
slice. A truncated observation page is visibly incomplete: no paging loop or
claim that the globally latest observation was found. The displayed scope is
never a whole-archive release census. Watchlists should be small enough for the
observation response to fit one page. No scheduled sector is treated as public.

A release record means first observed availability of a selected product in a
sector and filename processing build. It does **not** assert a complete sector
release or invent an official data-release number. The official observation
release MJD is retained separately and converted as a release timestamp, never
as a transit epoch. Public rights, matching TIC/sector/URI and nonfuture release
time are checked before registering an identity.

Release rows are immutable. Product keys include the original MAST URI and a
hash of processing version, size and selected release metadata; reprocessing
creates a new identity. Every response is retained with retrieval time, SHA256,
request and provenance. Duplicate polls append snapshots and reuse identities.
Changes to bytes at an unchanged URI/metadata are not detectable by metadata-only
polling; acquired bytes are pinned and never silently replaced.

## Configuration and CLI

`configs/research_watcher_v1.json` defaults to one existing known-control TIC,
one selected product per poll, a six-hour interval, a 120-second poll deadline,
and `metadata_only: true`. It selects by identity and public availability, with
no known period or epoch fed into detection.

```bash
.venv/bin/python -m scripts.research watch-poll
.venv/bin/python -m scripts.research watch-status
```

`watch-poll --force` permits an explicit immediate revalidation but cannot bypass
the three-consecutive-failure circuit breaker. `watch-reset` resets that circuit
after inspection; errors and old attempts remain in the audit history. Poll
failures back off exponentially, capped at 24 hours. Requests have 5-second
connect / 10-second read timeouts and a hard 60-second wall deadline. Each
metadata response is at most 1 MiB; automatic HTTP retries and metadata redirects
are off.

Public product downloads may follow one empty-body redirect from the official
MAST download endpoint to the exact selected object in STScI's public TESS cloud
bucket. The sector, TIC directory and filename must match; other hosts, query
strings, product substitutions and further redirects are rejected. Both requests
share the original deadline and byte reservation, and the receipt preserves the
redirect chain. The [MAST product directory definitions](https://archive.stsci.edu/missions-and-data/tess/data-products)
and [TESS public cloud registry](https://registry.opendata.aws/mast-tess/) document
this layout and bucket. This redirect was verified with live metadata and download
headers on 23 September 2026.

Inspect the returned `product_ids` before selecting an explicit finite pilot:

```bash
.venv/bin/python -m scripts.research watch-pilot \
  --pilot-id control-release-v1 --product-id PRODUCT_ID_FROM_POLL \
  --cohort known_object_control --max-bytes 8388608 --max-seconds 900
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research watch-dispatch --pilot-id control-release-v1
```

`archival_pilot` is also supported. The provisional scientific protocol blocks
prospective search. The watcher does not claim representative selection or
survey readiness. A pilot's membership, code identity, protocol, cohort, bytes
and runtime are frozen. Later metadata polls cannot add products. Dispatch is
single-worker, runs once, and stops; repeat it explicitly to resume within caps.
Completed dispatches make no network requests or additional candidates.

After an inspected downloader fix, `watch-repin --pilot-id OLD --replacement-id
NEW --reason 'Explanation of the source correction'` can replace the source pin
of a single failed, unacquired product while the scheduler is stopped. The
failure must remain retryable with attempts and resources available. It rejects
published receipts, existing processing jobs and active leases. The original
specification and accounting remain intact; the replacement carries the remaining
byte/runtime allowance, previous attempt count and retry deadline. An immutable
provenance record and event record the change. For automatic pilots, retain the
`auto-v1:` prefix in the replacement ID. This recovery is never automatic and
cannot reset resource limits or rewrite already processed results.

The path is public metadata → selected product → verified native FITS → blind
BLS → exact shared inputs → retained trained CNN → diagnostics and cached/offline
registry checks → review dossier. Existing cached files are preferred where the
bounded local manifest contains the same product. The default dispatcher never
refreshes catalogs over the network. A missing or stale cache remains incomplete.
Source FITS, BTJD/BJD TDB conventions and model contracts use the already tested
readers/workers. All proposals remain reviewable, regardless of CNN score.

## Persistence, retries and budgets

SQLite uses short serialized transactions; advisory locks serialize the watcher
and dispatcher on this single host. A separate service lock prevents duplicate
schedulers. Existing pipeline stages retain fenced leases and attempt records.
Completed jobs are reused. Active leases are never reset just because a process
starts. Expired stages recover through the existing store. Retryable queue
failures wait 60/120/240 seconds and allow at most three total dispatch attempts;
nonretryable failures remain visible for inspection.

The cumulative ledger reserves capacity **before** any request. The global cap
is 2 GiB, across metadata, scientific products, retries, imported prior usage,
and all pilots in this database. A second pilot does not reset the cap. The
initial selection is also cumulatively limited to 20 products and 20 targets,
including the two historical control selections; those leave at most 18 new
product/target slots for archival discovery.
Individual native files are at most 64 MiB. Each pilot has its own tighter byte
and runtime cap. Each invocation reserves at most 600 seconds of the remaining
allowance, then charges actual elapsed time on orderly completion. The main-thread deadline interrupts
long work and lets owned CPU subprocesses clean up.

A hard crash leaves byte/runtime reservations fully charged. A pilot larger than
one 600-second dispatch slice can resume within its remaining allowance. Waiting
for an active stage lease does not consume a queue attempt. Unknown network
usage is never counted as zero. This deliberately may exhaust a pilot after a
hard kill; the UI shows the conservative charge for operator inspection. A clean
pause/retry retains unused runtime. Never delete accounting rows to reset limits.
The ledger covers this watcher/dispatcher; independent acquisition/catalog CLI
commands must be imported explicitly or integrated before broader automation.

Prior-stage usage can be carried in exactly once:

```bash
.venv/bin/python -m scripts.research watch-account \
  --key prior-stage03-catalogs --bytes 5392591 \
  --reason 'Recorded stage 03 public catalog response bytes'
```

Files download to owned partial paths. Size, SHA256 and native FITS checksum/time/
TIC checks precede publication. Receipts are flushed before atomic publication;
restart can recover a completed file even if its SQLite receipt was interrupted.
A completed receipt is verified and reused; corruption is a visible failure,
never an automatic replacement. Incomplete transfers retry from the beginning,
with their previous reservation still charged; HTTP Range resume is not claimed.

## Service operation

The website is independent and loopback-only on 8766. Its protected check endpoint
queues requests for an already running automatic worker; it cannot launch one.
Existing same-origin/CSRF protections for review and retry operations remain in
force. Watcher health distinguishes running,
stopped, stale heartbeat and circuit-open states, with last success, next poll,
errors, product acquisition progress, stage links and cumulative budgets.

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -u -m scripts.research watch-serve --max-hours 10
```

The service polls metadata only, sleeps between checks, and stops after its
explicit finite lifetime (maximum 12 hours). It performs no GPU work. SIGINT/
SIGTERM stops it cleanly. The supplied user-service and timer templates in
`docs/services/` are optional alternatives; they run one bounded metadata poll
every six hours, and are **not installed or enabled** by this project. Edit the
project/interpreter paths before installing under a user's service directory.
Do not enable both a timer and a persistent scheduler for the same database.

## Verification and remaining limits

`tests/fixtures/mast/` supplies explicitly synthetic replay data. Tests cover
new releases, duplicate rows/polls, reprocessing, source corruption, crashed
publication, cumulative caps, retry exhaustion, backoff, malformed metadata,
future/nonpublic exclusions, time conversions, locks, runtime deadlines and
actual HTTP/CLI restarts. The HTTP integration downloads generated native FITS
from an isolated local archive, runs the real detector and local trained model,
then checks the research API, dossiers and no-redownload replay.

This is a bounded archival pipeline with historical control evidence. It does
not establish complete FFI release monitoring, pixel photometry, calibrated
search performance, prospective-trial readiness or a novel planet claim.
Registry/image/neighbor/calibration and adaptation research limits remain as
described in the preceding evidence reports.
