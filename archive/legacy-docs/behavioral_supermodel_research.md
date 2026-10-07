# Behavioral expert supermodel

This experiment implements a meta-model that learns from how frozen detectors
behave on each candidate. It currently observes five sealed TESS-only,
Kepler-only, fine-tuned, pooled, and DANN expert arms. Each arm is evaluated on:

- the original candidate;
- global-view occlusion;
- local-view occlusion;
- scalar-feature occlusion; and
- a deterministic small-noise probe.

The resulting meta-features contain each expert's original logit, variation
across training seeds, response to each occlusion, jitter sensitivity, and
cross-expert disagreement. The probes are deterministic and never receive the
candidate label. A small nonlinear supermodel learns the final logit from these
behaviors.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.behavioral_supermodel
```

The pilot preserves group-disjoint roles: 162 candidates for fitting, 81 for
calibration, and 82 for audit. The original TESS test partition is integrity
checked but never evaluated.

On the audit, ordinary stacking reached AP 0.6841 and calibrated Brier 0.2462.
The behavioral supermodel reached AP 0.5907 and calibrated Brier 0.2769, so it
did not outperform ordinary stacking. At the fixed 0.5 threshold it retained
the same 26 true positives while reducing false positives from 19 to 16. That
single operating-point improvement does not outweigh the poorer ranking and
calibration.

The result supports keeping the architecture as an experimental framework, not
promoting this fitted model. The current experts mostly share one CNN family,
the fitting set is small for 33 behavior features, and the audit partition was
used by earlier experiments. A serious follow-up needs genuinely different
experts such as a sequence Transformer and a physical transit model, stronger
regularization or hierarchical shrinkage, and a new prospective host-disjoint
test set that remains sealed until the design is frozen.

## Version 2

Version 2 adds a genuinely separate dual-view Transformer expert, deterministic
cadence-dropout and depth-attenuation probes, a convex expert stack, explicit
missing-expert masks, stronger residual shrinkage, and a calibration-only choice
of behavioral correction strength.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.transformer_expert

OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.behavioral_supermodel_v2
```

The Transformer ensemble reached audit AP 0.7368. The six-expert convex stack
reached AP 0.7278. Calibration selected a behavioral correction strength of 0.5,
but the corrected audit AP fell to 0.7070 and its calibrated Brier worsened from
0.2243 to 0.2454. Behavioral corrections therefore remain experimental and are
not promoted to candidate scoring. The Transformer result motivates a new
prospective comparison, but the reused validation-derived audit cannot support
a final improvement claim.

## Version 3 and the next sealed evaluation

Version 3 adds two interpretable specialists. The transit-morphology expert
measures central depth, shoulders, symmetry, coverage and local-view structure.
The stellar-variability expert measures robust global/local distribution,
roughness, autocorrelation, coverage and the existing scalar diagnostics.

The specialists reached audit AP 0.8071 and 0.8631 respectively. The eight-arm
convex stack reached 0.8557. Calibration rejected the behavioral residual by
selecting strength 0.0, so the behavior layer could not degrade the final stack.
This is a useful safety result, while the stellar-variability score is the main
performance improvement.

The repository now freezes 100 cached TESS hosts before applying these models.
They are absent from every shared_v1 partition and the current candidate
database. Their membership cannot change after scores are viewed. This cohort
is the next valid place to compare blind detection and frozen expert rankings.

The first 10 frozen hosts now form a prespecified target-pixel feasibility run.
It downloads their matching public SPOC TPFs with byte limits and SHA-256
receipts, runs catalog-blind BLS and TLS, and derives aperture-depth and
difference-image localization features for both ephemerides. Run it with:

```bash
MPLCONFIGDIR=/tmp/moradian-mpl-cache \
  .venv/bin/python -m scripts.experiments.tls_pixel_pilot \
  --config configs/tls_pixel_pilot_v1.json
```

These physical diagnostics are not yet a calibrated expert in the supermodel.
The pilot must finish, pass source-localization controls, and define a labelled
training cohort before adding a learned pixel score to the frozen stack.

## Version 4 physical-expert run

The labelled cohort is now frozen from the same group-disjoint roles used by
the earlier supermodels: 538 fitting, 162 selection, 81 calibration, and 82
audit candidates across 829 hosts. Original TESS test rows are excluded. One
label-blind, lexically selected 120-second SPOC product is assigned per host.

The public archive preflight found all 829 matching TPFs, totalling 36.6 GiB.
The resumable tmux job masks sibling catalog signals before blind TLS, extracts
known-ephemeris aperture and difference-image features, fits three regularized
physical experts, and then runs an availability-aware 11-expert v4 stack. The
calibration partition can disable the behavioral residual, as in v3.

## Version 5 diagnostic-conditioned routing

Version 5 freezes all 11 v4 experts and learns only a small candidate-specific
gate. Each expert receives its own perturbation responses plus shared
cross-expert disagreement, scalar, ephemeris, TLS, aperture and difference-image
diagnostics. A fixed mask limits which features can alter each expert's weight.
The gate starts from v4's global convex weights and is regularized back toward
that prior. It trains on the 162-row selection partition; shrinkage, prior KL
and temperature are selected on the 81-row calibration partition before the
82-row audit is evaluated.

Run the sealed comparison with:

```bash
.venv/bin/python -m scripts.experiments.behavioral_supermodel_v5
cat results/behavioral_supermodel_v5/report.md
```

Calibration selected a dynamic gate with shrinkage 0.35 and prior KL 0.25. On
the reused audit, raw NLL improved from 0.6021 for the static v4 stack to 0.5659
and Brier changed from 0.18058 to 0.18049. Ranking did not improve: AP changed
from 0.8613 to 0.8580, below the stellar-variability expert at 0.8631. The gate
therefore fails the declared joint improvement criterion and is not promoted to
the watcher. These are exploratory results because this audit was consulted by
earlier experiments; paper-level evaluation still requires the frozen
prospective, host-disjoint cohort.

## Cross-fitted competence follow-up

The next experiment changes the learning target from the final label to each
expert's observed loss. Five host-disjoint folds refit the four TESS-dependent
CNN arms, Transformer, morphology, variability and three physical experts. The
Kepler-only expert is safe to reuse because it never trains on TESS labels.
Every one of the 538 training candidates is scored exactly once by models that
excluded its host, producing leakage-free competence targets.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.crossfit_competence
cat results/crossfit_competence_v1/report.md
```

The selection partition chose routing strength 0.0: every nonzero competence
route reduced selection AP relative to the static v4 prior. The sealed fallback
therefore reproduces v4 on the reused audit (AP 0.8613, Brier 0.1806) and avoids
another degradation. This is a useful negative result: leakage-free competence
labels alone do not overcome the experts' correlated errors. The dynamic model
is not deployed.

## Corrected nonlinear cross-fitted supermodel

Diagnosis separated the data question from the model question. The linear
competence regressions had mean host-disjoint cross-validated R² of -0.03 for
per-expert loss, but a nonlinear classifier could predict the lowest-loss expert
50.6% of the time against a 21.9% majority baseline. The competence signal was
present as interactions; the linear loss target could not represent it.

The correction trains a strongly regularized histogram gradient-boosted
classifier on the same 538 out-of-fold expert predictions and diagnostics. The
selection partition jointly chooses tree complexity, L2 regularization and a
blend with the safe v4 score. It selected seven leaves, L2 10 and an equal
blend, raising selection AP from 0.8554 to 0.8819 before audit evaluation.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.crossfit_supermodel_v2
cat results/crossfit_supermodel_v2/report.md
```

On the reused audit, AP improves from 0.8613 to 0.8716, ROC AUC from 0.8086 to
0.8325, calibrated Brier from 0.1805 to 0.1662, and threshold accuracy from
70.7% to 74.4%. This also exceeds the stellar-variability expert's AP 0.8631 and
Brier 0.1774, satisfying the declared exploratory criterion. The stellar expert
still has higher threshold accuracy at 78.0%. Because the audit has been used by
earlier experiments, this result is not deployed and requires confirmation on a
new frozen host-disjoint evaluation.

## Fresh labelled audit

The follow-up pins a separate TOI snapshot released on 22 September 2026 and
registers 295 candidate hosts absent from every previously cached TESS host,
research candidate, Kepler proximity quarantine, and linked sky group. Current
archive queries find native 120-second SPOC products for 14 hosts; all 14 pass
the unchanged shared preprocessing and companion-coverage rules. The other 281
remain recorded as unavailable, with no score-driven replacement.

All eleven experts, the nonlinear blend, normalization and calibration
temperature remain frozen. The new inference path first reproduced the previous
82-row audit metrics and physical expert logits. On the fresh three-positive,
eleven-negative cohort, the nonlinear supermodel reaches AP 0.8333, ROC AUC
0.9091, Brier 0.1067 and accuracy 13/14 at threshold 0.5. It finds two of the
three positives and rejects all eleven negatives.

The static v4 stack reaches AP/AUC 1.0000 on these fourteen examples; transit
morphology reaches AP 0.9167 and stellar variability 0.8667. Thus the nonlinear
ranking advantage from the reused audit does not repeat. The small and imbalanced
sample limits generalization, and no model is selected or deployed from this
audit. Individual predictions, exclusions, provenance and paired uncertainty
are linked from the [fresh audit report](../results/fresh_classifier_audit_v1/README.md).
