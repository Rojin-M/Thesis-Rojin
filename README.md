 # Kepler-to-TESS exoplanet discovery pipeline

This thesis project studies whether knowledge learned from labelled Kepler transit signals can improve the prioritization of TESS signals. The active direction is a mission-invariant CNN trained with domain-adversarial learning, followed by a prospective search, automated checks, and documented human vetting.

The repository currently contains a frozen shared-preprocessing benchmark, a public-catalog checker, and a local research application with persisted jobs, bounded blind BLS, trained CNN scoring, diagnostic evidence and human review dossiers. An automatic TESS watchlist service connects bounded MAST polling to acquisition, detection and vetting; the metadata-only and explicit finite-pilot interfaces remain available. A separate five-arm experiment interface now implements supervised DANN, comparators and validation-only calibration; full scientific validation, pixel photometry and prospective `discovery_v1` search remain outstanding.

Read the [research storyline](STORYLINE.md) for the decision history and the [active evidence index](results/README.md) for compact, committed results.

**Using the website:** start with the [website and watcher guide](docs/website_guide.md).
The guide also explains the [existing vetting helper and what to do after `UNMATCHED`](docs/website_guide.md#use-the-vetting-helper).
For activity, see [live logs and monitoring](docs/website_guide.md#where-logs-and-results-live)
and the [23 September automatic-watcher results](results/automatic_watcher_run/README.md).
It covers startup, VS Code port forwarding, **Check for new data**, viewing
candidates, useful commands, and recovering a stuck loading screen.

## Research question

> Can a CNN learn transit features that remain useful across Kepler and TESS, then help surface credible signals in under-searched TESS data without hiding unusual candidates?

The implemented research architecture keeps the existing global/local light-curve encoder and adds two heads:

```text
global view + local view + scalar features
                    |
              shared encoder
               /          \
      planet classifier   mission classifier
                              |
                     gradient reversal
```

The planet head learns the scientific task. Gradient reversal makes the encoder worse at identifying whether an example came from Kepler or TESS, encouraging a representation less tied to mission-specific sampling and preprocessing. This is a hypothesis to test, not an assumed improvement.

## Project status

| Phase | Status | Purpose |
| --- | --- | --- |
| Shared Kepler/TESS preprocessing | Complete | Build comparable 200-bin global, 100-bin local, and seven-feature inputs |
| Frozen Kepler-to-TESS CNN benchmark | Complete | Establish the transfer baseline and its limitations |
| Public candidate-registry checker | Complete, limited | Identify compatible records in current ExoFOP and NASA catalogs |
| Local research application foundation | Operational, offline integration tested | Persist jobs, failures, candidate evidence, plots, provenance and review history |
| Blind light-curve BLS pilot | Operational, bounded engineering controls | Estimate period/epoch from cached native photometry; retain plots, aliases and event diagnostics |
| Proposal scoring and vetting | Operational, bounded CPU worker | Shared features, frozen trained CNN, catalog snapshots, diagnostic evidence and human dossiers |
| TESS-only, Kepler-only, fine-tuned, pooled, and DANN experiments | Operational finite CPU interface; bounded pilot | Compare matched update budgets without changing the frozen candidate scorer |
| `discovery_v1` pixel-to-candidate search | Planned | Search new or under-covered TESS targets rather than only re-rank known TCEs |
| Automatic TESS watchlist and finite dispatcher | Operational, scoped pilot | Check configured TICs, process new products, retain evidence and enforce cumulative budgets |
| Human review and cTOI submission | Prospective | Escalate only signals that survive the locked protocol |

The current model consumes a candidate with a supplied period and epoch. A separate blind BLS worker estimates these from existing TESS/Kepler light curves without catalog ephemerides; the vetting worker constructs shared inputs and applies the retained checkpoint. Pixel extraction and optional TLS remain separate milestones. The pilot does **not** perform pixel-based or prospective discovery.

## Discovery workflow

The intended end-to-end path is:

```text
new TESS FFI release
        |
target selection and deblended photometry
        |
BLS + TLS signal generation and iterative masking
        |
CNN/DANN scoring, calibration, and disagreement queues
        |
automated transit, centroid, contamination, and catalog checks
        |
human vetting dossier
        |
cTOI submission and possible follow-up
```

`discovery_v1` will be versioned separately from the labelled benchmark. Candidate selection thresholds and rejection rules must be frozen before prospective inspection. Injection-recovery tests will measure completeness; inverted or scrambled controls will measure false alarms.

The model comparison uses common eligible groups, preprocessing, planet-encoder capacity, splits, and reporting rules:

1. TESS-only CNN.
2. Kepler-only CNN evaluated on TESS.
3. Kepler pretraining followed by TESS fine-tuning.
4. Pooled Kepler and TESS training without domain adaptation.
5. Domain-adversarial training with a gradient-reversal mission head.

Runs use fixed seeds and star-grouped splits. Model selection stays on validation data. The prospective review queue remains separate from the previously consulted labelled TESS test set. The finite [experiment interface](docs/mission_adaptation_experiments.md) separates checkpoint selection, calibration and descriptive validation audits, saves resumable checkpoints and exposes verified reports on `/#experiments`. See the [primary-source research note and full-validation matrix](docs/mission_adaptation_research.md); adaptation benefit and novelty remain provisional.

## Automated watcher

The website now supports automatic processing of new products for a configured
TIC watchlist. Start `python -m scripts.research watch-auto-serve` with the project
interpreter, then use **Check for new data** at `http://127.0.0.1:8766/#watcher`.
List pages refresh every 30 seconds while idle. The worker uses
`configs/research_automation_v1.json`, retains cumulative resource limits, and
processes new products through detection, the frozen CNN and recorded vetting.
The default two targets are known-object controls, not a novel-discovery feed.
See [automatic operation](docs/release_watcher.md#automatic-website-watcher).

The watcher polls official MAST metadata for explicit TICs and records public
SPOC light-curve identities, source responses, retrieval dates and checksums.
Metadata polling never selects an entire sector or starts science downloads.
An explicit finite pilot freezes product IDs, cohort, byte/runtime budgets and
code, then resumes acquisition, blind BLS, trained scoring and review dossiers.

```bash
.venv/bin/python -m scripts.research watch-poll
.venv/bin/python -m scripts.research watch-status
```

The [watcher documentation](docs/release_watcher.md) describes the public API,
selection/retry/lock semantics, cumulative 2 GiB and 20-product caps, bounded
pilot commands, metadata-only service and optional user-scheduler templates.
Its website view at `/#watcher` shows poll health, errors, progress and budget.
The default automatic watchlist contains two existing known-object controls. This is scoped
product availability, not an archive-wide census or prospective search.

## Human-vetting boundary

Automation prioritizes evidence; it does not confirm a planet. A promoted signal still needs review of:

- the unfolded and phase-folded light curve, individual transit events, and multi-sector consistency;
- odd/even depth differences, secondary eclipses, transit-shape plausibility, and period aliases;
- difference images, centroid motion, aperture dependence, and nearby Gaia sources;
- spacecraft events, momentum dumps, scattered light, gaps, and other systematics;
- TOI/cTOI, confirmed-planet, eclipsing-binary, TCE, alias, coordinate, and literature matches; and
- whether follow-up observations can distinguish the remaining astrophysical scenarios.

The checker outcome `UNMATCHED` means only “no compatible public record was found in all required snapshots.” It does not prove novelty, exclude unpublished work, or establish that the signal is planetary.

## Repository layout

```text
configs/cnn_shared_v1.json       Frozen shared-input CNN baseline
scripts/data/                    Shared preprocessing and data utilities
scripts/experiments/             Baseline training and transfer evaluation
scripts/vetting/                 Live public-catalog candidate checker
scripts/research/                Local research store, CLI, HTTP API and review UI
configs/research_protocol_v1.json Bounded, provisional research protocol
docs/research_application.md     Architecture and pipeline integration contract
training/cnn/                    Global/local/scalar CNN implementation
results/tess/input_audit/        Evidence motivating cross-mission adaptation
results/tess/shared_transfer/    Frozen Phase-1 benchmark
results/tess/candidate_vetting/  Known-planet checker control
tests/                           Offline data, model, and vetting checks
data/                            Local raw, interim, and processed artifacts
outputs/                         Local runs, checkpoints, predictions, and logs
```

Large data and run artifacts remain local. Committed `results/` contain compact evidence and provenance, not checkpoints or a live candidate database.

## Environment

The reference environment uses Linux, Python 3.9, and PyTorch 2.1.2. Install PyTorch separately for the available CPU or CUDA runtime.

```bash
git clone https://github.com/Rojin-M/Thesis-Rojin.git
cd Thesis-Rojin
python3.9 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-reference.txt
python -m pip install torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu
```

Use the matching official PyTorch wheel instead of the CPU wheel for GPU training. A GPU accelerates batched CNN training and inference; catalog queries and most orchestration do not need one.

Run the offline suite before changing the pipeline:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The research HTTP tests open ephemeral loopback sockets; they require permission
to bind locally. They use temporary synthetic stores and make no science-data
downloads.

## Local research website

Use the [step-by-step website guide](docs/website_guide.md) for persistent startup,
page navigation, troubleshooting and stop commands. The following quick start
assumes the project environment and retained model files are already available.

From the repository root, run the website in one terminal:

```bash
.venv/bin/python -m scripts.research init
.venv/bin/python -m scripts.research serve --host 127.0.0.1 --port 8766
```

Run the automatic watcher in a second terminal:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research watch-auto-serve
```

For remote development, forward **remote port 8766 to local port 8766** in
VS Code's **Ports** panel, then choose **Open in Browser**. Open
[the Watcher page](http://127.0.0.1:8766/#watcher) and click **Check for new data**.
The request moves through queued, running and succeeded/failed states. The
equivalent command is:

```bash
.venv/bin/python -m scripts.research watch-auto-check
```

The worker checks the configured stars every **six hours**. **Refresh results**
reloads saved records; visible, idle list pages do this every **30 seconds**.
A successful archive check can produce zero new candidates when no new product
is available. The initial two stars are known-object controls.

Foreground commands occupy their terminals; use the guide's **tmux** commands
to keep the website and watcher running after disconnecting.

The default store starts empty under `outputs/research/`. The UI reads real
persisted records, shows failed and incomplete stages, displays recorded plots,
and exports JSON/Markdown dossiers. Review updates retain history and detect
conflicting browser edits. Known-object controls, synthetic fixtures, archival
pilots and prospective work have explicit separate labels.

The server is independent of the CLI watcher and processing workers. Its validated
[protocol](configs/research_protocol_v1.json) limits an initial pilot to 20
targets/products and 2 GiB cumulative new downloads; the watcher dispatcher
enforces durable reservations and receipts across restarts. Scientific approval and prospective readiness are
explicitly unset. See the [application architecture and integration API](docs/research_application.md)
for stage leases, provenance, evidence contracts, fixtures, exports and remaining
work. The existing learning Academy can continue independently on port 8765.

## Blind detection on local light curves

The CLI selects bounded local files, verifies source bytes and native time
headers, applies quality-zero filtering and blind gap-local detrending, runs
BLS, then persists proposals, event diagnostics and downloadable plots/arrays.
The following is a **known-object control**, using the earliest cached TESS
product for TIC 231663901. Its catalog ephemeris is not fed to the search:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m scripts.research detect --cached-tess --max-products 1 \
  --mission TESS --target-id 231663901 --cohort known_object_control
```

Use repeated `--path` arguments for explicit native FITS, CSV or NPZ inputs.
CSV/NPZ require `time`, `flux`, `flux_err`, `quality` and an explicit
`--time-system BJD_TDB`, `BTJD` or `BKJD`. Search defaults are 0.5–30 days,
at most 20,000 trial periods per masking round, three rounds and a hard
300-second CPU-worker deadline. Source hashes, code/configuration identities,
stage leases and deterministic output keys make identical jobs restartable.

Run the small fixed engineering experiment (four TRAIN-star controls, six
injections into real photometry, four negatives) in a new versioned directory:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m scripts.research detection-controls \
  --output outputs/research/experiments/detection-controls-v1
```

Synthetic and transformed controls are explicitly labelled. All retained peaks,
including noise, are review proposals; BLS white-noise S/N is not a calibrated
false-alarm or planet probability. The experiment does not establish survey
completeness or search readiness. No new scientific downloads are required.
See [detection details and stage integration](docs/blind_detection.md).

## Score and vet persisted blind proposals

Advance an existing detection job through shared features, frozen trained CNN
inference, diagnostics and human dossiers. This explicit control job was created
by the local detection experiment; fresh installations must use their own job ID:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research vet \
  --job-id be6c782ecb084da4b16e7cda4cebbd41 --catalog-mode offline
```

Repeat `--job-id` for at most 20 jobs. The CPU worker reuses exact Kepler training
normalization and checkpoint hashes, preserves inferred period/day, epoch/BJD TDB
and duration/hour units, and keeps insufficiently sampled proposals reviewable.
The legacy scalar definitions are unchanged. Sigmoid scores are **uncalibrated
ranking evidence**, not confirmation probabilities; no model threshold rejects
a proposal. Source-training controls do not measure model generalization.

The UI and reports show event odd/even depths, a bounded secondary phase scan,
sampling/aliases, and native centroid/crowding measurements where present.
Difference images, nearby-source and aperture evidence remain incomplete.
Current catalog snapshots can be appended separately, with bounded cached queries:

```bash
.venv/bin/python -m scripts.research refresh-registry \
  --candidate-id ad179520bad644d1b136da2b2defe9bf --catalog-mode live
```

This command targets one real TESS control. Synthetic experiments skip public
lookup; Kepler signals require a verified TIC mapping before using this checker.
Missing/stale catalogs stay incomplete. See [contracts, cache/retry behavior,
diagnostic limitations and tests](docs/scoring_vetting.md).

## Shared data baseline

The shared preparation reads the existing Kepler and TESS source products without modifying them. It writes local artifacts under `data/interim/{kepler,tess}/shared_v1/`, `data/processed/{kepler,tess}/shared_v1/`, and `outputs/shared_preparation/shared_v1/`.

Run the training-only pilot before a full rebuild:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/data/prepare_shared_features.py --stage pilot --prepare_workers 1
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/data/prepare_shared_features.py --stage full --prepare_workers 8
```

The full stage is resumable and guarded by a lock. Verify an existing rebuild without recomputing it:

```bash
.venv/bin/python scripts/data/prepare_shared_features.py --stage full --verify_only
```

The reference rebuild retained 5,385 of 5,518 Kepler candidates and all 2,208 TESS candidates while preserving eligible split memberships. TESS normalization was fitted only on rebuilt Kepler training rows.

## CNN baseline

Train the retained shared-input CNN into a new output directory:

```bash
.venv/bin/python scripts/experiments/run_config.py --model cnn \
  --config configs/cnn_shared_v1.json --output_dir outputs/shared_cnn/kepler_rerun --device auto
```

Compare that run with the frozen v0 source baseline on the identical shared TESS test rows:

```bash
.venv/bin/python scripts/experiments/evaluate_shared_cnn_transfer.py \
  --shared_run_pointer outputs/shared_cnn/kepler_rerun/run.json --output_dir outputs/shared_cnn/tess_transfer_rerun --device auto
```

This evaluation also requires the local frozen v0 CNN run pointer expected by the evaluator; checkpoints are not committed. The committed [shared-transfer export](results/tess/shared_transfer/README.md) is the durable reference.

The seed-42 shared CNN reached TESS AP `0.7991` and ROC-AUC `0.7828`; the frozen v0 CNN reached AP `0.8021` and ROC-AUC `0.7767`. Shared preprocessing therefore did not establish a transfer improvement. The [input audit](results/tess/input_audit/README.md) shows substantial mission distribution differences and motivates the controlled domain-adaptation study.

## Candidate-registry checker

Check a signal using an explicit time system. This known TOI-700 d example is a positive control:

```bash
.venv/bin/python -m scripts.vetting.check_candidate --tic-id 150428135 \
  --candidate-id TOI-700.02 --period-days 37.4236838 \
  --epoch-bjd-tdb 2458330.486155 --duration-hours 3.365
```

The checker refreshes or revalidates its supported public catalogs and writes timestamped source snapshots and reports under ignored local directories. It fails closed with `INCOMPLETE_LOOKUP` when required evidence is unavailable. The committed [positive-control report](results/tess/candidate_vetting/README.md) demonstrates status and ephemeris matching; it is not a discovery result.

## Evidence and limitations

Seven evidence groups are active:

- [Input audit](results/tess/input_audit/README.md): measured preprocessing and distribution shift.
- [Shared transfer](results/tess/shared_transfer/README.md): frozen labelled Phase-1 comparison.
- [Candidate vetting](results/tess/candidate_vetting/README.md): live-catalog positive control.
- [Blind detection pilot](results/detection_pilot/README.md): small training-star, injection and negative controls on local light curves; not survey validation.
- [Scoring and vetting pilot](results/scoring_vetting_pilot/README.md): 38 actual trained-model scores, two-TIC live catalog checks and preserved review paths; not search calibration or planet validation.
- [Release watcher pilot](results/release_watcher_pilot/README.md): real MAST metadata, one cached public control product, three new review proposals and verified deduplication; not prospective discovery.
- [Automatic watcher run](results/automatic_watcher_run/README.md): a subsequent public science download, three additional control proposals, timestamped activity/failure records and a snapshot of all 17 real-data proposals.

The Phase-1 model results use one seed and previously consulted test sets. The shared preprocessing changed the eligible Kepler cohort, so it does not isolate preprocessing as the cause of score changes. The separate DANN pilot uses short matched budgets and validation-derived audits, not an independent discovery test. No prospective `discovery_v1` candidate has been produced, submitted, validated, or confirmed by this repository.
