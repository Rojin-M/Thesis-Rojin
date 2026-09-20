# Kepler transit-candidate classification

A reproducible pipeline comparing tabular HistGradientBoosting, a multi-view CNN, CNN–HGB blending, and a transformer on a fixed Kepler dataset. Metadata-enabled v1 extends the same light-curve inputs used in v0.

Read the [experimental storyline](STORYLINE.md) for the questions, findings, and limitations. The [published results](results/README.md) include the [complete model comparison](results/comparison/COMPARISON.md) from the latest completed reproduction. The workflow below generates your own runs and plots under `outputs/`.

The TESS [acquisition](#thesis-extension-fetch-tess-light-curves), [preparation](#thesis-extension-prepare-tess-inputs), [first CNN comparison](#thesis-extension-compare-cnns-on-tess), and [transformer transfer](#thesis-extension-test-the-kepler-transformer-on-tess) sections follow the Kepler practical workflow. Their verified exports are under [results/tess](results/tess/README.md).

CNN v1 is the main practical model. Transformer v1 has a tiny mean test AP lead (0.960631 versus 0.960548), while CNN v1 has higher mean accuracy, F1, and ROC-AUC and fewer parameters. Both metadata extensions improved all four metrics in every matched seed on the fixed split.

## Repository layout

```text
configs/              Fixed experiment settings, protocol, and data checksums
scripts/data/         Downloading, preprocessing, metadata preparation, verification
scripts/experiments/  Training launchers and the complete reproduction workflow
scripts/analysis/     Metric checks, aggregation, and plots
training/             Tabular, CNN, blending/stacking, and transformer implementations
data/raw/tess/        Local TESS catalog, light curves, and acquisition records; ignored by Git
data/interim/tess/    Reusable star feature caches; ignored by Git
data/processed/tess/  Local prepared TESS inputs, audits, splits, and normalization; ignored by Git
data/processed/kepler/
  v0/                 Base views, scalar/flat inputs, labels, manifest, and split
  v1/                 Identical base inputs plus auxiliary metadata and its provenance
results/              Verified comparison tables, selected plots, and provenance
tests/                Data, training, tracking, and checkpoint checks
outputs/              Local generated runs and figures; ignored by Git
```

## 1. Set up the environment

The tested reference environment uses Linux, Python 3.9, and PyTorch 2.1.2. The pinned scientific dependencies are in `requirements-reference.txt`; `requirements.txt` records broader supported dependency ranges.

```bash
git clone https://github.com/Rojin-M/Thesis-Rojin.git
cd Thesis-Rojin
export PROJECT_ROOT="$(pwd)"
python3.9 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-reference.txt
```

Install the CPU build:

```bash
python -m pip install torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu
```

For the CUDA 11.8 environment used by the reference GPU runs, install this build instead:

```bash
python -m pip install torch==2.1.2 --index-url https://download.pytorch.org/whl/cu118
```

Other hardware may need a different build; see the [official PyTorch installation matrix](https://pytorch.org/get-started/previous-versions/#v212). The existing `python setup/setup_torch_cuda.py` helper detects hardware and replaces installed Torch packages; explicit installation above gives control over the version.

## 2. Verify the installation and processed data

Check the environment, dataset checksums, split, and implementation before training:

```bash
python -c 'import torch; print(torch.__version__); print("CUDA available:", torch.cuda.is_available())'
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
python scripts/data/check_processed.py
python -m unittest discover -s tests -v
```

**Both processed Kepler datasets are included.** The Kepler training and evaluation below require no raw download, interim cache, catalog request, or W&B account. The dataset has 5,518 candidates and a fixed star-grouped train/validation/test split of 3,853/836/829.

## Run the story in order

Run commands from the repository root: the `Thesis-Rojin/` directory containing `README.md` and `scripts/`.

If setup is already complete and you opened a new terminal, enter your clone and reactivate the existing environment first. Replace `/path/to/Thesis-Rojin` with your clone's actual location:

```bash
cd /path/to/Thesis-Rojin
source .venv/bin/activate
export PROJECT_ROOT="$(pwd)"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
```

Continue with the numbered commands below in that same terminal. `--device auto` selects one CUDA device when available; `--device cpu` and `--device cuda:0` choose explicitly. Seeds run sequentially by default, and W&B is disabled. Keep the same device, GPU UUID list, and tracking options across stages sharing an output directory. The optional parallel-GPU commands below must be selected when starting a new workflow.

The following numbered stages follow the storyline. A fresh clone writes to `outputs/reproduce/` by default. If you already have completed runs and intentionally want a new experiment, add the same new `--output_dir` to every stage; retain the existing results for comparison.

Preview the plan without starting training:

```bash
python scripts/experiments/reproduce.py --dry_run
```

### 3. Tabular baselines: scalar versus full inputs

Establish how much the flattened transit views add beyond the seven scalar features.

```bash
python scripts/experiments/reproduce.py --stage tabular --device auto
```

### 4. Multi-view CNN baseline

Train the preserved global/local/scalar CNN configuration.

```bash
python scripts/experiments/reproduce.py --stage cnn-baseline --device auto
```

### 5. CNN ablations: wide branch and regularization

Compare the baseline with the existing wide-input branch and additional regularization options.

```bash
python scripts/experiments/reproduce.py --stage cnn-ablations --device auto
```

### 6. Blend the CNN and full HGB

Select the blend weight and classification threshold using validation predictions from steps 3 and 4.

```bash
python scripts/experiments/reproduce.py --stage blend --device auto
```

### 7. CNN v0 across five seeds

Measure variability of the fixed baseline on the saved split.

```bash
python scripts/experiments/reproduce.py --stage cnn-v0 --device auto
```

### 8. CNN v1 with metadata across the same five seeds

Repeat the shared settings with the prepared auxiliary inputs and branch.

```bash
python scripts/experiments/reproduce.py --stage cnn-v1 --device auto
```

### 9. Compare CNN v0 and v1

Verify predictions and export paired differences, summary tables, and figures without training another model.

```bash
python scripts/experiments/reproduce.py --stage cnn-comparison --device auto
```

### 10. Transformer normalization and metadata study

Screen input normalization on validation, freeze the selection, then compare metadata across five seeds and generate plots.

```bash
python scripts/experiments/reproduce.py --stage transformer --device auto
```

### 11. Compare all models and inspect the findings

Recompute metrics from the saved predictions and export the final comparison.

```bash
python scripts/experiments/reproduce.py --stage comparison --device auto
```

The full workflow trains two HGB baselines, three individual CNN configurations, ten CNN seed runs, and twelve transformer configurations, plus the blend. CPU execution can take much longer than GPU execution. Completion is recorded in `outputs/reproduce/workflow.json`. Completed stages are reused with the same execution settings. Interrupted/failed stages are retained; choose a new `--output_dir` for a fresh attempt.

To execute steps 3–11 consecutively in a fresh output directory:

```bash
python scripts/experiments/reproduce.py --stage all --device auto
```

The primary CNN comparison is available after `cnn-comparison`. The optional transformer adds a two-seed validation screen of input normalization, followed by a five-seed metadata comparison. Its ten final test evaluations occur after all twelve training runs finish. The `comparison` stage requires all model families and exports the complete table.

| Output | Contents |
| --- | --- |
| `outputs/reproduce/comparison/COMPARISON.md` | Overall metrics and interpretation limits |
| `outputs/reproduce/comparison/comparison.png` | All-model comparison |
| `outputs/reproduce/comparison/runs.csv` | Individual run metrics |
| `outputs/reproduce/comparison/summary.csv` | Individual scores or five-seed mean/sample SD |
| `outputs/reproduce/cnn_comparison/` | Paired CNN v0/v1 tables and figures |
| `outputs/reproduce/transformer/results/` | Transformer screen and metadata tables |
| `outputs/reproduce/transformer/figures/` | Transformer comparisons and learning curves |
| `outputs/reproduce/cnn_baseline/`, `outputs/reproduce/cnn_wide/`, `outputs/reproduce/cnn_regularized/` | Individual runs and their `figures/` subdirectories |
| `outputs/reproduce/cnn_v0/`, `outputs/reproduce/cnn_v1/` | Five-seed checkpoints, predictions, histories, and metric tables |
| `outputs/figures/cnn/cnn_v0/`, `outputs/figures/cnn/cnn_v1/` | Five-seed CNN learning curves and aggregate plots |

The CNN aggregate plots in `outputs/figures/cnn/` use shared group names and are replaced by another aggregation of those groups. The workflow's metric tables remain in its own directory; step 12 exports a separate set of publication figures.

Inspect `outputs/reproduce/comparison/COMPARISON.md` and `summary.csv`, and compare them with the [published comparison](results/comparison/COMPARISON.md). AP is average precision. Error bars describe training-seed variability on the fixed split; they are not confidence intervals. GPU operations are seeded but not forced to be deterministic, so exact scores and selected epochs can vary. The storyline distinguishes historical experiments from the latest reproduction.

### 12. Export the results for sharing

After all stages complete, export the comparison, model-specific tables, selected figures, and provenance. This verifies saved prediction metrics and does not train models. A clone already contains the published `results/`, so export your reproduction separately:

```bash
python scripts/analysis/export_results.py --workflow_dir outputs/reproduce --output_dir outputs/published_results
```

The destination must be new or empty. To prepare an initial publication when `results/` is empty, use:

```bash
python scripts/analysis/export_results.py --workflow_dir outputs/reproduce --output_dir results
```

The export contains `comparison/`, `tabular/`, `cnn/`, `blend/`, and `transformer/`, with a guide in each model directory. Detailed runs, checkpoints, and histories remain under `outputs/`.

### Verify existing results without retraining

After the workflow completes, check its status and independently recompute the comparison from its prediction files:

```bash
python -c 'import json; print(json.load(open("outputs/reproduce/workflow.json"))["status"])'
python scripts/analysis/compare_all_models.py \
  --workflow_dir outputs/reproduce --output_dir outputs/recheck
```

The first command should print `complete`. The second writes a new comparison and checks prediction metrics against the saved summaries; it does not train models. Use a new output directory for another verification, because existing comparison exports are protected from overwriting.

<details>
<summary>Individual commands behind the workflow</summary>

These commands use a separate output directory. The configuration files contain the full settings; no input config is taken from an ignored historical run.

These manual commands do not create the `workflow.json` manifest required by the publication exporter in step 12. Use the numbered `reproduce.py` workflow to generate that manifest and prepare the publication export.

```bash
export EXPERIMENT_ROOT="$PROJECT_ROOT/outputs/manual"

python scripts/experiments/run_config.py --model tabular \
  --config configs/hgb_scalar.json --output_dir "$EXPERIMENT_ROOT/hgb_scalar"
python scripts/experiments/run_config.py --model tabular \
  --config configs/hgb_full.json --output_dir "$EXPERIMENT_ROOT/hgb_full"

python scripts/experiments/run_config.py --model cnn --config configs/cnn_v0.json \
  --output_dir "$EXPERIMENT_ROOT/cnn_baseline" --device auto
python scripts/experiments/run_config.py --model cnn --config configs/cnn_wide.json \
  --output_dir "$EXPERIMENT_ROOT/cnn_wide" --device auto
python scripts/experiments/run_config.py --model cnn --config configs/cnn_regularized.json \
  --output_dir "$EXPERIMENT_ROOT/cnn_regularized" --device auto

python scripts/experiments/run_config.py --model blend --config configs/blend.json \
  --cnn_record "$EXPERIMENT_ROOT/cnn_baseline/run.json" \
  --hgb_record "$EXPERIMENT_ROOT/hgb_full/run.json" \
  --output_dir "$EXPERIMENT_ROOT/blend"

python scripts/experiments/run_cnn_multiseed.py --source_config configs/cnn_v0.json \
  --group_dir "$EXPERIMENT_ROOT/cnn_v0" --device auto --wandb_mode disabled
python scripts/experiments/run_cnn_multiseed.py --source_config configs/cnn_v1.json \
  --group_dir "$EXPERIMENT_ROOT/cnn_v1" --device auto --wandb_mode disabled
python scripts/analysis/aggregate_cnn_multiseed.py \
  --experiment "$EXPERIMENT_ROOT/cnn_v0/experiment.json"
python scripts/analysis/aggregate_cnn_multiseed.py \
  --experiment "$EXPERIMENT_ROOT/cnn_v1/experiment.json"
python scripts/analysis/compare_cnn_variants.py \
  --baseline "$EXPERIMENT_ROOT/cnn_v0/experiment.json" \
  --candidate "$EXPERIMENT_ROOT/cnn_v1/experiment.json" \
  --output_dir "$EXPERIMENT_ROOT/cnn_comparison/results" \
  --figure_dir "$EXPERIMENT_ROOT/cnn_comparison/figures"

python scripts/experiments/run_transformer_study.py \
  --source_config configs/transformer_base.json \
  --protocol configs/transformer_protocol.json \
  --study_dir "$EXPERIMENT_ROOT/transformer" --device auto --wandb_mode disabled
python scripts/analysis/analyze_transformer_study.py \
  --study_dir "$EXPERIMENT_ROOT/transformer" \
  --figure_dir "$EXPERIMENT_ROOT/transformer/figures" \
  --cnn_v0 "$EXPERIMENT_ROOT/cnn_v0/experiment.json" \
  --cnn_v1 "$EXPERIMENT_ROOT/cnn_v1/experiment.json"

python scripts/analysis/compare_all_models.py --workflow_dir "$EXPERIMENT_ROOT" \
  --output_dir "$EXPERIMENT_ROOT/comparison"
```

`run_config.py` saves a `run.json` pointer, so blending never chooses an unrelated “latest” run. CNN learning curves are generated automatically. To regenerate one run's curves, obtain its exact directory from that pointer:

```bash
CNN_RUN=$(python -c 'import json, os; print(json.load(open(os.path.join(os.environ["EXPERIMENT_ROOT"], "cnn_baseline/run.json")))["run_dir"])')
python scripts/analysis/plot_cnn_history.py --run_dir "$CNN_RUN" \
  --output_dir "$EXPERIMENT_ROOT/replotted_cnn"
```

The transformer launcher calls the following evaluator for each deferred checkpoint after training finishes. Its CLI is available for a separately trained deferred-test run; it rejects a run already evaluated on test:

```bash
python scripts/experiments/evaluate_transformer_checkpoint.py --help
```

Every trainer and launcher also supports `--help` for individual options. Checkpoints are selected by validation AP and neural classification thresholds by validation F1; the blend configuration uses validation F1 for both weight and threshold selection.

</details>

<details>
<summary>Optional W&B tracking and parallel transformer execution</summary>

Local CSV/JSON files and plots are always produced. The published reproduction used disabled W&B tracking. To add offline W&B logs to the five-seed CNN and transformer studies in a new workflow:

```bash
python -m pip install -r requirements-wandb.txt
python scripts/experiments/reproduce.py --stage all --device auto \
  --wandb_mode offline --output_dir outputs/tracked
```

The three individual CNN runs use the tracking mode in their JSON configurations, which is disabled in the committed configs. The workflow flag above changes tracking for the multi-seed studies.

For multiple GPUs, inspect their UUIDs and pass the selected identifiers with `--gpu_uuids`. The transformer runs one job per selected GPU. The default remains sequential execution on the chosen device.

```bash
nvidia-smi --query-gpu=index,uuid,name --format=csv
python scripts/experiments/run_transformer_study.py --help
```

For example, after assigning your two GPU UUIDs to shell variables `GPU_A` and `GPU_B`, start a new workflow with parallel transformer seeds. GPU parallelism works with W&B disabled:

```bash
python scripts/experiments/reproduce.py --stage all --device cuda:0 \
  --gpu_uuids "$GPU_A" "$GPU_B" --wandb_mode disabled --output_dir outputs/parallel
```

Offline logging does not upload runs. Optional cloud use is a separate action: `wandb login`, a trainer's `--wandb_mode online`, or `wandb sync` with an explicit offline-run directory.

</details>

## Optional: rebuild data from its sources

**Skip this section when using the included processed datasets.** Raw light curves and interim caches are large and excluded from Git. Source catalog updates and data availability can change a rebuild; the committed processed artifacts and checksums define the fixed experiments above.

Raw acquisition and preprocessing may take hours, depending on archive availability, network speed, existing caches, and hardware. This is a planning estimate; the included processed datasets let you skip these steps.

The following commands use a separate rebuild directory, preserving the published processed files:

```bash
export REBUILD_ROOT="$PROJECT_ROOT/outputs/data_rebuild"
python scripts/data/kepler_download_raw.py --base_dir "$REBUILD_ROOT" --target_n 10000
python scripts/data/kepler_prepare_features.py \
  --base_dir "$REBUILD_ROOT" --target_n 10000 --seed 42 \
  --global_bins 200 --local_bins 100 --global_window 0.5 --local_window_mult 4.0 \
  --detrend_window_days 1.5 --sigma_clip_sigma 5.0 --prepare_workers 8 --use_bls

python scripts/data/kepler_prepare_aux_v1.py \
  --dataset "$REBUILD_ROOT/data/processed/kepler/v0/dataset_kepler_v0_target10000_g200_l100_gw0.5_lwm4.0_bls1_seed42.npz" \
  --splits "$REBUILD_ROOT/data/processed/kepler/v0/splits_kepler_v0_seed42.npz" \
  --manifest "$REBUILD_ROOT/data/processed/kepler/v0/manifest_kepler_v0.csv" \
  --metadata "$REBUILD_ROOT/data/raw/kepler/metadata/koi_cumulative.csv" \
  --output_dir "$REBUILD_ROOT/data/processed/kepler/v1" \
  --audit_dir "$REBUILD_ROOT/outputs/metadata_audit"
```

Raw caches are written under `$REBUILD_ROOT/data/raw/kepler/`; folded/BLS/view caches under `$REBUILD_ROOT/data/interim/kepler/v0/`. The metadata builder fits transformations on training rows and preserves the base candidates and split.

To rebuild candidate caches while reusing downloaded raw light curves:

```bash
python scripts/data/kepler_prepare_features.py \
  --base_dir "$REBUILD_ROOT" --target_n 10000 --seed 42 \
  --global_bins 200 --local_bins 100 --prepare_workers 8 --use_bls \
  --force_recompute_candidate_cache
```

To audit metadata against the published v0 without writing another dataset:

```bash
python scripts/data/kepler_prepare_aux_v1.py \
  --dataset "$PROJECT_ROOT/data/processed/kepler/v0/dataset_kepler_v0_target10000_g200_l100_gw0.5_lwm4.0_bls1_seed42.npz" \
  --splits "$PROJECT_ROOT/data/processed/kepler/v0/splits_kepler_v0_seed42.npz" \
  --manifest "$PROJECT_ROOT/data/processed/kepler/v0/manifest_kepler_v0.csv" \
  --metadata "$REBUILD_ROOT/data/raw/kepler/metadata/koi_cumulative.csv" \
  --audit_dir "$REBUILD_ROOT/outputs/published_v0_audit" --audit_only
```

Audit/output directories must be new. Use explicit dataset, split, and manifest paths in a separate config when training on a rebuilt dataset; the committed experiment configs continue to select the published artifacts.

## Thesis extension: fetch TESS light curves

TESS acquisition is the first step toward comparing models across Kepler and TESS. After completing the environment setup, run this command from the repository root to download one file at a time:

```bash
export PROJECT_ROOT="$(pwd)"
python scripts/data/tess_download_raw.py \
  --base_dir "$PROJECT_ROOT" \
  --max_sector 105 \
  --dispositions CP KP FP FA \
  --download_workers 1
```

The downloader saves the full [NASA TESS Objects of Interest catalog](https://exoplanetarchive.ipac.caltech.edu/docs/API_TOI_columns.html), selects stars with a confirmed planet (`CP`), known planet (`KP`), false positive (`FP`), or false alarm (`FA`), and fetches their available native SPOC two-minute light curves through Sector 105 from [MAST](https://archive.stsci.edu/tess/bulk_downloads/bulk_downloads_ffi-tp-lc-dv.html). Stars without matching light curves are recorded in the coverage report. It retains every catalog candidate on the selected stars; unconfirmed `PC`/`APC` candidates are not assigned negative labels.

Only the catalog and light-curve FITS files are fetched. PDFs, validation time series, XML reports, and pixel files are excluded from this first light-curve experiment.

```text
data/raw/tess/
  lightcurves/TIC.../       Original SPOC light-curve FITS files
  metadata/                Catalog snapshot, candidates, manifest, coverage, and checksums
logs/tess_download_raw.log  Acquisition progress and errors
```

**Speed:** on our server, we use `--download_workers 4` to overlap four transfers. The default of one keeps downloads sequential. We also reduced the download list to the model's inputs and obtain light-curve URLs directly from archive observation records; the [storyline](STORYLINE.md#10-start-the-thesis-extension-with-tess-acquisition) records the measured speed comparison.

Add `--dry_run` to the command to fetch or reuse the metadata and show the plan without downloading FITS files. Rerun the same command to resume: the saved catalog and manifest are reused, and completed files are checked against their recorded hashes. The worker count can change when resuming; use a separate `--base_dir` for a different sector limit or candidate selection. Keep the metadata and receipts with the files to preserve the exact input snapshot; a fresh catalog query later may select different candidates even with the same sector limit.

For a download that continues after disconnecting from SSH, start `tmux new -s tess-download`, activate the project environment inside that session, and run the command above. Detach with **Ctrl+B**, then **D**, and reconnect with `tmux attach -t tess-download`.

These are raw acquisition inputs. Continue with the preparation stage below before using the models. The published classification results remain Kepler experiments.

## Thesis extension: prepare TESS inputs

The preparation script reads the completed TESS download and the preserved Kepler reference. It labels `CP`/`KP` as positive and `FP`/`FA` as negative, applies the Kepler period/duration limits, and quarantines TESS stars within five arcseconds of a processed Kepler star. Unknown companions remain available for transit masking. Nearby TESS identifiers share a split group.

The saved Kepler KOI catalog is needed for sky-coordinate checks. Use the copy from Kepler raw acquisition, or fetch this catalog once if it is missing:

```bash
python - <<'PY'
import io
from pathlib import Path
from urllib.request import urlopen
import pandas as pd

path = Path("data/raw/kepler/metadata/koi_cumulative.csv")
if not path.exists():
    url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=select+*+from+cumulative&format=csv"
    with urlopen(url, timeout=180) as response:
        content = response.read()
    if not {"kepid", "ra", "dec"}.issubset(pd.read_csv(io.BytesIO(content)).columns):
        raise ValueError("Unexpected KOI catalog columns")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
PY
```

An existing catalog is preserved. If it is stored elsewhere, pass the same `--kepler_catalog /path/to/koi_cumulative.csv` to both preparation commands. Keep this snapshot with the dataset; changed catalogs can change the overlap exclusions.

Start with a balanced pilot and verify its outputs:

```bash
python scripts/data/tess_prepare_features.py \
  --base_dir "$PROJECT_ROOT" \
  --output_dir "$PROJECT_ROOT/outputs/tess_preparation/pilot" \
  --pilot_candidates 24 --prepare_workers 1
python scripts/data/check_tess_prepared.py \
  --prepared_dir "$PROJECT_ROOT/outputs/tess_preparation/pilot" --check_models
```

Inspect the time-series and folded plots under `outputs/tess_preparation/pilot/figures/`. The pilot has no test split; all inspected star groups are reserved for training in the full dataset. `--check_models` only checks finite forward outputs from the existing CNN and transformer architectures; it produces no accuracy result.

After inspecting the pilot, prepare the full set and verify it:

```bash
python scripts/data/tess_prepare_features.py \
  --base_dir "$PROJECT_ROOT" \
  --pilot_dir "$PROJECT_ROOT/outputs/tess_preparation/pilot" \
  --prepare_workers 1
python scripts/data/check_tess_prepared.py \
  --prepared_dir "$PROJECT_ROOT/data/processed/tess/v0" --check_models
```

The default processes one star at a time. On our server we use four workers for the pilot and eight for the full run, with `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1`. The exact Kepler BLS period search is computed once per star and can take hours over the full set. Run inside `tmux` for SSH disconnections, as in the acquisition section. Progress is recorded in the output directory's `prepare.log` and `preparation_summary.json`.

Rerunning the same command reuses matching star caches. To verify a completed preparation without rewriting its artifacts, use `check_tess_prepared.py`. Changed inputs or scientific preparation settings/code require a new pilot and a new full `--output_dir`. Compatible scientific star caches under `data/interim/tess/` remain reusable; changes limited to output reporting need a new output directory but can retain a scientifically matching pilot. Raw inputs and the published Kepler datasets are preserved.

The full output under `data/processed/tess/v0/` includes:

- `dataset_tess_v0.npz`: global `(N, 200, 3)` and local `(N, 100, 3)` views, seven scalars, 907 flat features, and labels.
- `manifest_tess_v0.csv` and `splits_tess_v0_seed42.npz`: candidate identities and approximately 70/15/15 percent training/validation/test groups.
- Catalog, overlap, and processing audits, plus input/code provenance and output checksums.
- `kepler_train_normalization.npz` and `tess_train_normalization.npz`: statistics fitted exclusively on each source mission's training rows.

TESS uses sector- and gap-local detrending with known transit windows protected. Other candidates' transit windows are masked before folding. Candidates need at least two sampled transit events after this masking, each with at least half the expected two-minute samples and a minimum of three points. This checks sampling, not signal detection. Missing companion ephemerides and insufficient coverage are recorded as exclusions.

The feature geometry and calculations match Kepler v0; TESS quality filtering and detrending differ from the historical Kepler preparation. The legacy names `feat_odd_even` and `bls_snr` retain their original meanings: alternating phase-bin difference and BLS likelihood power. Full Kepler v1 auxiliary metadata is not supplied here.

For independent transfer, apply the source mission's saved normalization unchanged to the target inputs. The current training loader fits normalization on the supplied training split, so substituting TESS paths alone does not perform frozen Kepler inference. The comparison below handles this explicitly; the [storyline](STORYLINE.md#11-prepare-tess-inputs-and-check-a-small-batch) records completed preparation checks.

## Thesis extension: compare CNNs on TESS

After full TESS preparation passes verification, compare two CNN v0 models on the same fixed TESS test candidates: one trained from scratch on TESS, and the existing Kepler model applied with frozen weights. The Kepler baseline from stage 4 must already be complete.

```bash
python scripts/experiments/run_tess_baseline.py \
  --base_dir "$PROJECT_ROOT" --device auto
```

The script locates the source run through `outputs/reproduce/cnn_baseline/run.json`. For a source run stored elsewhere, add `--source_run_dir /path/to/completed/cnn/run`. Use `--device cpu` or an explicit CUDA device if needed.

Before training, the script records the dataset, splits, checkpoint hashes, and comparison settings in `outputs/tess_baseline/seed42/protocol.json`. It retains the source CNN's architecture and training recipe with seed 42. The TESS model uses only TESS training rows for normalization; validation average precision selects its checkpoint, and validation F1 selects its classification threshold. The frozen Kepler model keeps its original Kepler training normalization and Kepler validation threshold, with no TESS fine-tuning or recalibration.

Results are written to `comparison.csv`, per-model prediction and metric files, and `completion.json` in that comparison directory. Rerunning the same command verifies and reuses completed results. Changed settings or incomplete training require a new `--output_dir`; existing runs are preserved.

This is an initial, single-seed comparison on a curated labelled TOI subset. It does not establish performance on all TESS detections. The differing mission preprocessing described above also affects interpretation. These CNN v0 results use fewer inputs than the practical CNN v1 results. The [storyline](STORYLINE.md#12-first-cnn-comparison-on-tess) records the first completed comparison and its limitations.

Export the completed CNN comparison into a new or empty directory:

```bash
python scripts/analysis/export_tess_results.py \
  --output_dir outputs/published_tess_cnn
```

The reference export is [results/tess/cnn_baseline](results/tess/cnn_baseline/README.md). It includes preparation counts, metrics, confusion counts, PNG/PDF figures, protocols, and source checksums. Predictions and checkpoints remain in local `outputs/`.

## Thesis extension: test the Kepler transformer on TESS

After the Kepler transformer study in stage 10 and full TESS preparation are complete, evaluate the existing seed-42 v0 checkpoint:

```bash
python scripts/experiments/evaluate_kepler_transformer_on_tess.py \
  --base_dir "$PROJECT_ROOT" --device auto
```

The script reads the Kepler validation choice from `outputs/reproduce/transformer/selection.json`, then locates its seed-42 run. It verifies the original study's artifact hashes and replays Kepler validation predictions before evaluating the same fixed TESS test rows. The saved architecture, weights, Kepler training normalization, and Kepler validation threshold are retained. There is no training, TESS recalibration, or threshold search. The selected reference model bypasses initial input LayerNorm and has no v1 auxiliary branch.

The protocol is saved before TESS inference in `outputs/tess_transformer/seed42/`. That directory receives predictions, metrics, completion, and verification records. The command requires a new output directory; inspect a completed evaluation without inference with:

```bash
python scripts/experiments/evaluate_kepler_transformer_on_tess.py \
  --base_dir "$PROJECT_ROOT" --verify_only
```

Use `--output_dir` for a separate evaluation and `--device cpu` or an explicit CUDA device as needed. Export the completed transformer evaluation alongside the two CNN references:

```bash
python scripts/analysis/export_tess_results.py \
  --transformer_dir outputs/tess_transformer/seed42 \
  --output_dir outputs/published_tess_transfer
```

Export destinations must be new or empty. The exporter reconstructs metrics from saved predictions and checks identical test identities and artifact hashes; it performs no model inference. The reference [transfer results](results/tess/transformer_transfer/README.md) and [storyline](STORYLINE.md#13-evaluate-the-existing-kepler-transformer-on-tess) report the completed single-seed experiment. This is a reused TESS benchmark, and differing preprocessing and training recipes limit causal comparisons. It is an evaluation of the existing transformer; the combined CNN–transformer remains future work.

## Thesis extension: audit Kepler and TESS inputs

After the CNN comparison and frozen transformer evaluation, inspect preprocessing compatibility and feature distributions:

```bash
python scripts/analysis/audit_tess_inputs.py \
  --base_dir "$PROJECT_ROOT" \
  --output_dir outputs/tess_input_audit
```

The destination must be new or empty. The audit checks input geometry, feature order, engineered features, source normalization, training distributions by label, and saved prediction metrics. It demonstrates the two detrending functions on one synthetic transit and checks the legacy clipping rule on 24 randomly selected Kepler training candidates per label where raw caches are available. It writes tables, figures, and provenance without changing data or models, running inference, or tuning thresholds. Missing raw caches are recorded; the prepared-data comparisons remain available.

The [reference audit](results/tess/input_audit/README.md) reports substantial distribution differences despite structural compatibility. Its measurements motivate a controlled preprocessing experiment; they do not establish the cause of the accuracy gap.

### Thesis extension: shared Kepler and TESS preprocessing

`shared_v1` rebuilds both missions from the downloaded native light-curve FITS files using the same transit-preserving algorithm. It applies quality filtering, quarter/sector- and gap-local 1.5-day detrending, protection of all catalog transit windows, companion masking, folding, and the existing 200-bin global / 100-bin local views with seven scalar features. The native Kepler long cadence and TESS two-minute cadence remain different; gap and coverage checks account for each cadence. This experiment does not resample the missions to a common cadence or guarantee better transfer.

The starting cohorts are the existing Kepler and TESS v0 manifests. Retained candidates keep their original labels and train/validation/test membership; additional coverage or companion-ephemeris exclusions are recorded. The rebuilt TESS dataset stores normalization fitted only on the **rebuilt Kepler training rows**. Any frozen v0 source model instead retains its own v0 Kepler training normalization. Compare old and new preprocessing on common retained candidates to avoid confusing preprocessing changes with cohort changes.

Run a small training-only pilot first, then the full rebuild. From the project root, after the environment and original datasets are available:

```bash
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python scripts/data/prepare_shared_features.py \
  --base_dir "$PROJECT_ROOT" --stage pilot --prepare_workers 1
```

The fixed pilot selects four training candidates per label per mission and includes their siblings on the same stars. Inspect `outputs/shared_preparation/shared_v1/pilot/{kepler,tess}/training_preview.png` and the processing audits. No test examples are used for this inspection. The pilot normalization is fitted on its Kepler training sample only and is replaced by full Kepler-training normalization in the full run.

For a full run that survives SSH disconnection (using the project's `.venv`):

```bash
mkdir -p outputs/shared_preparation/shared_v1
tmux new-session -d -s shared-preparation -c "$PROJECT_ROOT" \
  'env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -u scripts/data/prepare_shared_features.py --stage full --prepare_workers 1 >> outputs/shared_preparation/shared_v1/full.log 2>&1'
```

The full command verifies the completed pilot before processing Kepler and then TESS. One worker is the reproducible sequential setting; our server uses **eight workers**, with one numerical-library thread per worker. Completed stars are cached so the same command can resume after interruption. Frozen input/code/environment signatures and output checksums prevent mixing different versions. Concurrent preparation jobs are blocked by a lock.

| New local artifacts | Location |
| --- | --- |
| Per-star BLS, folded curves, views, and completion records | `data/interim/{kepler,tess}/shared_v1/{bls,folded,views,stars}/` |
| Datasets, manifests, retained splits, normalization, and audits | `data/processed/{kepler,tess}/shared_v1/` |
| Pilot, frozen protocol, logs, and overall progress | `outputs/shared_preparation/shared_v1/` |

Raw files, v0/v1 datasets, and previous results are preserved. New data remain local and ignored by Git. No additional downloads or PDFs are needed.

Check progress and verify completed outputs:

```bash
tmux attach -t shared-preparation
# Detach without stopping: press Ctrl-b, release, then d.
tail -f outputs/shared_preparation/shared_v1/full.log
# After completion:
python scripts/data/prepare_shared_features.py \
  --base_dir "$PROJECT_ROOT" --stage full --verify_only
```

`full_status.json` records the overall state. While processing, each mission's `preparation_summary.json` records completed stars and accepted/rejected candidates. A successful run also writes `full_verification.json`; this is a data-preparation check, not a new model result. The reference full run completed on 14 September 2026 and passed verification: **5,385/5,518 Kepler candidates** (3,759 train, 817 validation, 809 test) and **2,208/2,208 TESS candidates** (1,548 train, 325 validation, 335 test) were retained. Kepler rejected 132 for insufficient sampled transit events and one for missing companion timing.

### Thesis extension: first CNN result on shared inputs

The seed-42 CNN uses the same architecture, hyperparameters, and Kepler-validation selection rule as the v0 baseline, with only its Kepler inputs changed to `shared_v1`. After training, the evaluator replays both source validation predictions, checks source-only normalization and artifact hashes, and applies both frozen CNNs to the identical `shared_v1` TESS test rows. It does not fit statistics or thresholds on TESS. The reference run used GPU 0 in `tmux` and saved its checkpoint and figures under `outputs/shared_cnn/kepler/`; transfer predictions, protocol, and verification are under `outputs/shared_cnn/tess_transfer/`.

| Frozen Kepler CNN on 335 TESS test candidates | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| v0 | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| shared_v1 | 0.7194 | 0.7099 | 0.7991 | 0.7828 |

The shared CNN recovered 115 of 183 positive TESS labels, compared with 124 for v0; its Kepler-validation threshold was 0.785 versus 0.83 for v0. On the **809 Kepler test candidates retained in both versions**, shared_v1 AP was 0.9422 versus 0.9239 for v0, while F1 was 0.8658 versus 0.8781. These single-seed results do not show a TESS transfer improvement. The 133 Kepler exclusions also change source training and validation cohorts, so this comparison does not isolate preprocessing as the cause. Both test sets were previously consulted.

To reproduce the CNN result into new directories, first verify the completed preparation, then train and evaluate:

```bash
.venv/bin/python scripts/data/prepare_shared_features.py --stage full --verify_only
.venv/bin/python scripts/experiments/run_config.py --model cnn \
  --config configs/cnn_shared_v1.json --output_dir outputs/shared_cnn/kepler_rerun --device auto
.venv/bin/python scripts/experiments/evaluate_shared_cnn_transfer.py \
  --shared_run_pointer outputs/shared_cnn/kepler_rerun/run.json \
  --output_dir outputs/shared_cnn/tess_transfer_rerun --device auto
```

The original saved transfer can be checked without inference using `--verify_only` with its default output directory. During the Phase 1 audit, the evaluator file's hash no longer matched the hash recorded by that original protocol. We therefore repeated frozen-checkpoint inference into `outputs/shared_cnn/tess_transfer_phase1/`; its comparison and both prediction CSVs are byte-identical to the original, and its current code hash is recorded. Reruns need new directories because completed training and comparison artifacts are preserved.

### Thesis extension: transformer result on shared inputs

The seed-42 `shared_v1` transformer uses the same float32 training recipe and bypass-input-normalization architecture selected by Kepler validation in the v0 study. Training skips test inference; the evaluator replays both source validation sets, then evaluates the frozen v0 and shared-v1 checkpoints on the same **809 retained Kepler test candidates** and **335 TESS test candidates**. Each model keeps its own Kepler-training normalization and Kepler-validation threshold. No TESS labels or statistics are used for fitting or selection.

| Frozen Kepler model on shared_v1 TESS test inputs | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| Transformer v0 | 0.5761 | 0.4701 | 0.7146 | 0.7121 |
| Transformer shared_v1 | 0.6776 | 0.6842 | 0.7395 | 0.7432 |
| CNN shared_v1 (reference) | 0.7194 | 0.7099 | 0.7991 | 0.7828 |

The shared transformer recovered **117/183** positive TESS labels versus **63/183** for v0, with 42 versus 22 false positives. Its TESS AP improved by 0.0249, which reflects better ranking independently of the Kepler-selected thresholds (0.745 versus 0.725). On common Kepler test candidates, AP was **0.9068** versus **0.8911** for v0. The shared transformer remains below the shared CNN on TESS AP, and the architecture families use different training recipes. This is one seed on previously consulted benchmarks; 133 Kepler exclusions also changed the source training and validation cohorts, so the comparison does not isolate preprocessing as the cause.

The reference training completed in `tmux` on GPU 1 under `outputs/shared_transformer/kepler/`. Matched Kepler and TESS predictions, comparison tables, artifact hashes, and exact validation replays are under `outputs/shared_transformer/tess_transfer/`. To reproduce into new directories on this server:

```bash
.venv/bin/python scripts/experiments/run_config.py --model transformer \
  --config configs/transformer_shared_v1.json \
  --output_dir outputs/shared_transformer/kepler_rerun --device cuda:1
.venv/bin/python scripts/experiments/evaluate_shared_transformer_transfer.py \
  --shared_run_pointer outputs/shared_transformer/kepler_rerun/run.json \
  --output_dir outputs/shared_transformer/tess_transfer_rerun --device cuda:1
```

Verify the original saved result without inference using `.venv/bin/python scripts/experiments/evaluate_shared_transformer_transfer.py --verify_only`.

### Phase 1: freeze the shared benchmark milestone

On 20 September 2026, the full `shared_v1` preparation, CNN transfer, and transformer transfer passed artifact, input, and metric reconstruction checks. The compact public export is in [`results/tess/shared_transfer/`](results/tess/shared_transfer/README.md). It contains the two common-candidate tables, figures, preparation summaries, protocols, source hashes, and the CNN reevaluation audit; checkpoints and per-candidate predictions remain in ignored local `outputs/`.

Rebuild the export without training or inference into a new directory:

```bash
.venv/bin/python scripts/analysis/export_shared_transfer_results.py \
  --output_dir outputs/published_shared_transfer
```

This is the boundary of the completed labelled-benchmark work. Both test sets were previously consulted, only seed 42 was run for the shared comparison, and the 133 Kepler exclusions changed the source cohorts. Any future search for genuinely new candidates should use a separately versioned, unlabelled dataset and locked selection/vetting protocol rather than adding more decisions to these benchmark results.

### Phase 2: check a signal against current public catalogs

The candidate registry checker is deliberately separate from model training. Given a TIC, period, BJD-TDB epoch, and optional duration, it checks the signal-level ephemeris rather than treating every signal on the same star as the same object. It queries:

- the current [ExoFOP TOI](https://exofop.ipac.caltech.edu/tess/json/tois.csv) and [Community Candidate](https://exofop.ipac.caltech.edu/tess/json/ctois.csv) catalogs;
- the NASA Exoplanet Archive [`ps`](https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html) confirmed-planet table for that TIC;
- the NASA [`toi`](https://exoplanetarchive.ipac.caltech.edu/docs/API_TOI_columns.html) mirror as secondary evidence.

ExoFOP bulk files are conditionally revalidated on every invocation and NASA is queried live. Each report records source URLs or queries, retrieval and catalog timestamps, raw-response SHA-256 hashes, matching tolerances, and direct or small-integer-period harmonic matches. Raw snapshots go under ignored `data/raw/vetting/registry/`; JSON and Markdown dossiers go under ignored `outputs/vetting/`.

For a known example:

```bash
.venv/bin/python -m scripts.vetting.check_candidate \
  --tic-id 150428135 \
  --candidate-id TOI-700.02 \
  --period-days 37.4236838 \
  --epoch-bjd-tdb 2458330.486155 \
  --duration-hours 3.365
```

The epoch flag is explicit to prevent mixing time systems. If an input table stores the usual TESS BTJD value instead, use `--epoch-btjd`; the CLI adds `2457000` before matching.

Allowed outcomes distinguish NASA-confirmed and controversial planets, ExoFOP planet statuses, candidates, false positives, false alarms, period aliases, catalog conflicts, unmatched signals, and incomplete lookups. `UNMATCHED` means only that no compatible signal appeared in every required current snapshot; it never means “new planet.” A source outage or schema change fails closed as `INCOMPLETE_LOOKUP`.

The dossier also shows public ExoFOP **target-level** imaging, spectroscopy, and time-series observation counts and publication references when available. These show deposited follow-up evidence, not signal-specific completeness or whether someone is privately studying the object now. There is no scientifically defined “research completion percentage,” so the checker reports a categorical stage and evidence instead of inventing one.

The committed [TOI-700 d positive-control result](results/tess/candidate_vetting/README.md) records the successful live check and source hashes without treating a known object as a discovery.

Run the deterministic offline tests, then optionally test the current external contracts:

```bash
.venv/bin/python -m unittest tests.test_candidate_registry -v
RUN_LIVE_CATALOG_TESTS=1 \
  .venv/bin/python -m unittest \
  tests.test_candidate_registry.LiveCatalogContractTests -v
```
