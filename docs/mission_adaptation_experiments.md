# Reproducible mission-adaptation experiments

The five-arm interface trains real models on the existing prepared shared_v1
arrays. It writes new, isolated runs under `outputs/research/model_experiments/`.
It neither updates the frozen benchmark nor replaces the reference CNN used by candidate
dossiers. A separate comparison service now applies completed models to saved blind
features and displays their scores alongside the reference. The [research note and remaining matrix](mission_adaptation_research.md)
define the provisional scientific claim and its limits.

## Arms and matched budgets

| Arm | Gradient training | Checkpoint and calibration mission |
| --- | --- | --- |
| `tess_only` | TESS training labels | TESS |
| `kepler_only` | Kepler training labels | Kepler; no target-label selection |
| `fine_tuned` | Fresh Kepler pretraining, then all-layer TESS fine-tuning | TESS, only after the mission switch |
| `pooled` | Equal Kepler/TESS examples per batch, both label sets | TESS |
| `dann` | Same supervised pooled batches plus reversed mission gradient | TESS |

All arms instantiate the retained global/local/scalar encoder and planet head
from scratch with the same seed. The reference implementation and weights remain
untouched. The 576-element fusion matches the reference exactly. The DANN head
adds a 128-unit MLP with two mission outputs; its parameter count is separately
reported. Planet-model capacity is identical, total DANN capacity is larger.
The head is excluded from deployment; this interface has no deployment action.

For DANN the loss is binary task cross-entropy plus `mission_loss_weight` times
mission cross-entropy. The mission head minimizes that loss normally, while its
encoder contribution is multiplied by **minus** the scheduled reversal strength.
The schedule is `max_lambda * (2/(1+exp(-10*p))-1)`, with `p` spanning the fixed
update budget. The weight is applied once in the loss; the reversal coefficient
is applied once on the backward path. Setting domain-loss weight to zero gives
the same planet predictions as pooled training in the regression test.

The shipped pilot fixes seeds 42/43/44, 120 optimizer updates and 32 examples per
update: **3,840 draws per arm per seed**. Fine-tuning uses 60 Kepler plus 60 TESS
updates within that total, carries terminal pretrained weights and BatchNorm
statistics, and resets optimizer moments at the switch. It does not import the
60-epoch reference checkpoint. Mixed arms draw 16 examples per mission per step;
single-mission arms draw 32. Deterministic shuffled cycles expose smaller domains
repeatedly. This balances missions, not labels, stars, unique examples or elapsed
compute. All runs complete their budget and select the earliest maximum validation
AP checkpoint at the fixed evaluation intervals; there is no outcome-dependent
early stopping or extra hyperparameter search.

## Data isolation and normalization

Prepared file hashes must match their preparation receipts. The loader validates
the shared input shapes, channel order, labels, original split indices, unique
hosts and proximity groups, and the existing TESS/Kepler overlap quarantine.
Known catalog ephemerides are already embedded in these prepared inputs. The
runner performs classification, not blind period/epoch discovery.

The original train/validation/test memberships are unchanged. The first 512
TRAIN groups per mission under a seed-2718 hash ordering form the pilot training
subset: 578 Kepler rows and 538 TESS rows. Original validation groups are split
once, with the same fixed seed and stratification by group label signature:

| Mission | Selection | Calibration | Descriptive audit |
| --- | --- | --- | --- |
| Kepler | 402 rows / 361 groups | 205 / 181 | 210 / 181 |
| TESS | 162 rows / 158 groups | 81 / 79 | 82 / 79 |

All siblings stay together. The original NPZ is integrity-checked in full;
**no original test row is returned as a model tensor, fitted, selected,
calibrated or predicted**. This is not a newly untouched test study: earlier
benchmark development already consulted validation/test data. Audit outcomes
must not be used for tuning followed by a claim of independent validation.

Every arm uses the exact frozen moments fitted on all 3,759 original Kepler TRAIN
rows. No new normalization is fitted. “TESS-only” therefore means TESS-only
gradient training under a common source-derived feature transform. A completely
source-free normalization comparator is a remaining ablation. Epochs retain
absolute BJD TDB days; periods are days and durations hours. Legacy `bls_snr` is
likelihood power, and `odd_even` is a phase-bin feature: neither is relabelled as
physical SNR or an event diagnostic.

## Calibration and reporting

A bounded one-dimensional positive temperature fit minimizes calibration-subset
NLL, including the identity transform as a candidate. The audit reports raw and
scaled Brier, NLL, ten-bin reliability/ECE, AP and ROC-AUC. Ranking metrics use
logits to avoid numerical sigmoid saturation ties and are unchanged by positive
temperature scaling. Kepler-only fits temperature on Kepler; other arms on TESS.
Calibration can worsen an independent audit and does not imply planet-confirmation
probabilities or calibrated blind-search errors.

Empirical 90% precision and 5% labelled-negative FPR thresholds are selected on
the **selection** subset and transferred unchanged as decision sets to the audit.
An unattainable constraint is recorded, with no selected rows. These are sample
operating points, not confidence-bounded guarantees; using the checkpoint-selection
subset for thresholds is explicitly optimistic. Period subgroups are descriptive.
The pilot does not infer physical SNR from legacy likelihood values.

Reports contain each seed, means/sample seed SD, actual selected update, counts,
parameter budgets, temperatures, confusion counts, missing metrics, mission-head
balanced accuracy, and paired star/proximity-group bootstrap AP-difference
intervals (200 resamples). Seed SD is not a population confidence interval. The
adversary's own accuracy is not an independent representation probe. Saved audit
predictions preserve candidate, host/group, label and physical time metadata.

## Commands and restart behavior

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.mission_adaptation \
  --config configs/mission_adaptation_pilot_v1.json \
  --output outputs/research/model_experiments/pilot-v1
```

Use `--audit-only` to validate inputs and print group counts without training.
Use `--resume` to resume/replay exactly the frozen configuration, source hashes,
prepared-data receipts and package versions. Changed specifications require a
new output directory. No existing benchmark or completed run can be overwritten.
Checkpoint, optimizer, torch RNG, best weights and update position are saved
atomically at evaluation boundaries. Restart verifies hashes and resumes the
deterministic sample sequence; uncheckpointed work may repeat. The latest restart
checkpoint supersedes only the previous checkpoint belonging to that same arm.
Completed arms verify their weights, predictions and report receipts and skip
training. Completion replay changes no run files.

An exclusive file lock prevents concurrent owners. A signal deadline enforces
the per-invocation cap; cumulative reservations and at most three explicit
attempts bound retries. A hard crash conservatively charges the whole reserved
invocation (up to 1,800 s in the shipped config); a clean exit charges actual
runtime. The total cap is 3,600 s. Exhaustion is visible, not automatically reset.
CPU execution uses two threads and zero DataLoader subprocesses. GPUs were busy
at the overnight check; this first CLI intentionally supports CPU only. No new
packages or science downloads are required.

`spec.json` freezes input/role identities, source hashes and environment. Exact
source snapshots are retained under `source/`; `state.json` records attempts,
progress, runtime charges and failures. Each arm keeps its selected weights,
predictions, history, result and receipt. The suite writes `summary.json`,
`report.md`, `comparison.png` and a completion receipt. These files are local.

## Website and tests

The read-only Models page is `http://127.0.0.1:8766/#experiments`. Its
`/api/experiments` endpoint lists at most 50 local runs and exposes metrics only
after export hashes and specification identities verify. Running/failed/corrupt
runs remain visible without invented scores. Fixed routes serve verified JSON,
Markdown and PNG reports; clients cannot request arbitrary paths or checkpoints.
The web server never imports a model or launches training.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m unittest tests.test_mission_adaptation \
  tests.test_research_experiments_http -v
```

Tests exercise actual retained-module forwards and gradients, group isolation,
balanced batch cycles, calibration failures, matched-budget training across all
five arms, deliberate interruption/resume, byte-preserving completed replay,
zero-domain-weight equivalence, corruption, and actual HTTP report/PNG behavior.

## Completed pilot and automatic candidate comparisons

The [23 September pilot](../results/mission_adaptation_pilot/README.md) completed
all five arms and three seeds. DANN's mean TESS audit AP was 0.6934; pooled was
0.7067 and fine-tuned was 0.7644. This short experiment does not support replacing
the reference CNN with DANN. Both training results and the negative conclusion
are retained.

The new comparison service loads all 15 validation-selected checkpoints from a
completed run, verifies their hashes and explicit specification pin, and uses
the frozen shared_v1 normalizer. It scores saved blind-search inputs and appends
`model_comparison` evidence. It never rewrites `model_score`, catalog matches,
review notes, feature arrays or completed processing stages. Means and ranges
across seeds are descriptive rankings, not probabilities or confidence intervals.
The training calibration temperatures are not applied to blind proposals.

Run one bounded pass over at most 60 pending completed candidates:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.research compare-models \
  --run-id pilot-v1 \
  --spec-sha256 0c655a8199a12d0a495cd8200d30cabcb88ef8f1534591d6289471ac3443999e
```

Add `--watch` to poll newly completed jobs every 60 seconds until stopped. The
service uses two CPU threads, makes no downloads, performs no training, and
stops after three consecutive failed batches. A database lock prevents duplicate
services; a batch lock also protects manual passes. Existing comparison evidence
is reused on restart. Explicit `--candidate-id` values select a finite pass;
they cannot be combined with `--watch`.

For persistent operation from the repository root:

```bash
tmux new-session -d -s exoplanet-model-comparisons -c "$PWD" \
  'exec env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python -u -m scripts.research compare-models --run-id pilot-v1 --spec-sha256 0c655a8199a12d0a495cd8200d30cabcb88ef8f1534591d6289471ac3443999e --watch >> outputs/research/logs/model-comparison.log 2>&1'
```

Use this once; an existing session means the service is already started. It
survives an SSH disconnect, not a machine reboot. Stop with
`tmux kill-session -t exoplanet-model-comparisons`.

The **Models** page shows the service heartbeat and marks old heartbeats stale.
Open a candidate's **Experimental model comparison** table for the five scores
and seed ranges. Refresh an already-open dossier to see a newly appended result.
Markdown and JSON exports include the comparison. Operator files are
`outputs/research/model-comparison-service.json` and
`outputs/research/logs/model-comparison.log`.

The existing vetting snapshot command now preserves referenced comparison
weights as well. A new snapshot and push are still manual; the earlier frozen
snapshot does not acquire new model scores automatically. Full retraining still
requires the prepared shared_v1 datasets described above.
