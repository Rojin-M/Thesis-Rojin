# Kepler-to-TESS exoplanet discovery pipeline

This thesis project studies whether knowledge learned from labelled Kepler transit signals can improve the prioritization of TESS signals. The active direction is a mission-invariant CNN trained with domain-adversarial learning, followed by a prospective search, automated checks, and documented human vetting.

The repository currently contains a frozen shared-preprocessing benchmark and a live public-catalog checker. The domain-adversarial model, blind `discovery_v1` search, and release watcher are the next phases; they are not presented as completed work.

Read the [research storyline](STORYLINE.md) for the decision history and the [active evidence index](results/README.md) for compact, committed results.

## Research question

> Can a CNN learn transit features that remain useful across Kepler and TESS, then help surface credible signals in under-searched TESS data without hiding unusual candidates?

The planned architecture keeps the existing global/local light-curve encoder and adds two heads:

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
| TESS-only, fine-tuned, pooled, and DANN baselines | Planned | Measure whether mission-invariant learning adds value |
| `discovery_v1` pixel-to-candidate search | Planned | Search new or under-covered TESS targets rather than only re-rank known TCEs |
| Automated release watcher and vetting queue | Planned | Process only newly available data and produce review dossiers |
| Human review and cTOI submission | Prospective | Escalate only signals that survive the locked protocol |

The current model consumes a candidate with a known period and epoch. It does **not** yet discover periodic events directly from pixels. That requires the planned photometry and BLS/TLS detection stage.

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

The model comparison will use the same eligible targets, preprocessing, encoder capacity, splits, and reporting rules:

1. TESS-only CNN.
2. Kepler-only CNN evaluated on TESS.
3. Kepler pretraining followed by TESS fine-tuning.
4. Pooled Kepler and TESS training without domain adaptation.
5. Domain-adversarial training with a gradient-reversal mission head.

Runs will use multiple fixed seeds and star-grouped splits. Model selection stays on validation data. The prospective review queue remains separate from the previously consulted labelled TESS test set.

## Automated watcher

The watcher should poll release metadata on a schedule, not keep a GPU busy continuously. For each unseen release it will:

- record source versions and checksums;
- resume downloads and preprocessing safely;
- run CPU-heavy extraction and transit searches once;
- batch GPU inference only when new inputs exist;
- refresh public-catalog matches;
- append idempotent review records without duplicating candidates; and
- retain failures for retry and audit.

`tmux` is suitable for development runs that must survive an SSH disconnect. A system scheduler is the safer long-term deployment because `tmux` does not survive reboot and does not provide job retry semantics by itself.

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

Only three evidence groups are active:

- [Input audit](results/tess/input_audit/README.md): measured preprocessing and distribution shift.
- [Shared transfer](results/tess/shared_transfer/README.md): frozen labelled Phase-1 comparison.
- [Candidate vetting](results/tess/candidate_vetting/README.md): live-catalog positive control.

The Phase-1 model results use one seed and previously consulted test sets. The shared preprocessing changed the eligible Kepler cohort, so it does not isolate preprocessing as the cause of score changes. The planned DANN study has no result yet. No prospective `discovery_v1` candidate has been produced, submitted, validated, or confirmed by this repository.
