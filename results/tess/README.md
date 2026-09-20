# TESS thesis results

These exports follow the Kepler practical work. The first three use the prepared TESS v0 dataset: 2,208 labelled candidates, with 1,548 training, 325 validation, and 335 test examples. The shared milestone rebuilds both missions with the same transit-preserving algorithm and retains all 2,208 TESS candidates with the same split membership.

| Completed step | Evidence |
| --- | --- |
| First CNN comparison, 11 September 2026 | [Two CNN results and preparation record](cnn_baseline/README.md) |
| Frozen Kepler transformer, 13 September 2026 | [Transformer and CNN comparison](transformer_transfer/README.md) |
| Input compatibility audit, 13 September 2026 | [Preprocessing, feature distributions, and clipping checks](input_audit/README.md) |
| Shared preprocessing, CNN, and transformer milestone, 20 September 2026 | [Verified shared_v1 comparison](shared_transfer/README.md) |
| Candidate-registry checker control, 21 September 2026 | [TOI-700 d live-catalog recognition](candidate_vetting/README.md) |

Each export contains metrics reconstructed from saved predictions, confusion counts, PNG/PDF figures, preparation summaries, evaluation protocols, and source hashes. The transformer comparison includes the existing CNN results as references; those CNNs were not retrained. Per-candidate predictions and checkpoints remain in local `outputs/`.

Reproduce each export into a new or empty directory from the repository root:

```bash
python scripts/analysis/export_tess_results.py \
  --output_dir outputs/published_tess_cnn

python scripts/analysis/export_tess_results.py \
  --transformer_dir outputs/tess_transformer/seed42 \
  --output_dir outputs/published_tess_transfer

.venv/bin/python scripts/analysis/export_shared_transfer_results.py \
  --output_dir outputs/published_shared_transfer
```

The [main README](../../README.md#thesis-extension-test-the-kepler-transformer-on-tess) provides evaluation commands. The [storyline](../../STORYLINE.md#12-first-cnn-comparison-on-tess) explains the findings. All comparisons use seed 42 on the same previously consulted TESS test subset, with thresholds selected on each model's source validation set. They do not establish general survey performance or isolate preprocessing, training-recipe, and mission effects.

The input audit compares training distributions and inspects saved predictions without model inference. Its reproduction command and limitations are in the [audit report](input_audit/README.md).

The shared export verifies the full preparation and both transfer protocols, reconstructs CNN and transformer metrics on 809 common Kepler candidates and 335 common TESS candidates, and records the Phase 1 CNN reevaluation audit. It is the frozen boundary for the completed benchmark work; prospective unlabelled-data screening and human vetting are not part of these results.

The candidate-vetting control starts Phase 2 without changing the frozen benchmark. It records a live positive-control lookup for the already confirmed TOI-700 d and validates catalog identity/status handling; it is not a model-performance result or discovery claim.
