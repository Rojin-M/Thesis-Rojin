# Completed five-model pilot and blind-signal comparison

Completed 23 September 2026 from the original, unchanged experiment specification
`0c655a8199a12d0a495cd8200d30cabcb88ef8f1534591d6289471ac3443999e`.
The interrupted run resumed its saved checkpoint. All **15 fits** completed:
five training approaches, seeds 42/43/44, 120 updates and 3,840 training draws
per fit. The completed-run replay verified receipts without retraining.

| Training approach | TESS audit average precision, mean ± seed SD |
| --- | ---: |
| TESS only | 0.7474 ± 0.0131 |
| Kepler only, same short budget | 0.5588 ± 0.0315 |
| Kepler pretraining then TESS fine-tuning | 0.7644 ± 0.0180 |
| Pooled Kepler and TESS | 0.7067 ± 0.0124 |
| Supervised DANN | 0.6934 ± 0.0003 |

Average precision measures ranking on the **82 labelled TESS audit rows / 79
groups**, not planet probability. These rows were partitioned from the original
validation set. The original test set was not evaluated. The short-budget
Kepler-only arm is a newly trained comparator, not the older frozen CNN used by
the watcher. These metrics cannot be compared directly with the separate
335-row frozen test benchmark.

DANN did not demonstrate a benefit over pooling or fine-tuning. All three
paired DANN-minus-pooled bootstrap intervals include zero. The original export's
`paired_dann_pooled[].seed` denotes the bootstrap RNG seed, 2718; entries follow
model-seed order 42/43/44. Most selected checkpoints occur at the update limit,
so convergence is not established. No hyperparameters were changed after seeing
these audit results. Temperature fitting is restricted to the calibration
groups; it does not calibrate probabilities for blind detections.

## Application to saved blind detections

All 15 selected checkpoints were applied to the same saved shared_v1 inputs for
**44 proposals: 17 real known-object controls and 27 synthetic/transformed
controls**. Each candidate retains every seed's score, model checksum, input
checksum and the mean/minimum/maximum across seeds for each approach. No new
light curves were downloaded or detections rerun.

These selected controls establish that the inference integration works; they
are not an independent test of discovery performance. Scores are uncalibrated,
and seed ranges are not probability confidence intervals. Catalog assessments,
human reviews and the original `model_score` evidence remain unchanged.

**Decision: DANN is available for comparison, not promoted to primary scorer.**
The separate `compare-models --watch` service adds these experimental scores to
newly completed watcher jobs. Candidate dossiers and Markdown/JSON exports show
them; the Models page shows the training comparison and service heartbeat.

## Preserved evidence and reproduction

- [report.md](report.md), [summary.json](summary.json) and
  [comparison.png](comparison.png): original completed training exports.
- [spec.json](spec.json), [state.json](state.json), [complete.json](complete.json)
  and `runs/`: frozen split identities, environment, source hashes, runtime
  accounting, per-arm results, labelled audit predictions and receipts.
- [blind_comparison.json](blind_comparison.json): captured reference and new
  scores, source receipts, cohort labels and existing recovery checks.
- [provenance.json](provenance.json): export hashes and all checkpoint receipts.

Checkpoint files remain in `outputs/research/model_experiments/pilot-v1/`.
The vetting snapshot command now includes every comparison checkpoint referenced
by a candidate, as well as the normalizer. Compact reports alone are not an
inference bundle. The previously committed September 23 snapshot predates these
models and scores; preserving the new live state remotely still requires a new
snapshot and push.

With the documented prepared shared_v1 data and environment, reproduce the
frozen configuration into a **new** directory:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.mission_adaptation \
  --config configs/mission_adaptation_pilot_v1.json \
  --output outputs/research/model_experiments/pilot-reproduction-v1
```

Training source files must match `spec.json` to claim an exact replay. See the
[experiment guide](../../docs/mission_adaptation_experiments.md) for data isolation,
restart behavior and automatic candidate comparison commands. Completing this
pilot does not complete the larger validation matrix or establish model novelty.
