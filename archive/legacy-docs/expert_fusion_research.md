# Evidence-specialized expert fusion

## Research question

Can a feature-conditioned router learn when independently trained transit-vetting
experts are reliable, combine them better than a single model or fixed ensemble,
and abstain when their evidence is insufficient or contradictory?

The repository now contains a bounded pilot of this idea. It uses the five sealed
mission-adaptation arms as provisional experts, learns only on the TESS selection
partition, fits calibration and an empirical abstention rule on the disjoint
calibration partition, and reports once on the disjoint validation-derived audit.
The original test set remains unused.

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.expert_fusion
```

The experiment compares the selection-chosen single expert, uniform averaging,
learned static weighting, and a soft per-candidate gate. Its competence report
shows each expert's AP, ROC AUC and Brier score across period, duration and BLS
signal-to-noise regimes, together with the router's mean weight in each regime.
Unavailable experts can be masked and receive exactly zero routing weight.

This pilot is a mechanism test, not the final scientific experiment. Its experts
share the same CNN input contract and differ mainly in training regime. A paper
test needs genuinely complementary evidence specialists:

1. a folded-light-curve morphology expert;
2. a raw-sequence or self-supervised stellar-behaviour expert;
3. a difference-image and centroid-localization expert;
4. a stellar, orbital and contamination tabular expert; and
5. an instrumental-systematics and event-consistency expert.

Each expert should emit a logit, uncertainty estimate, evidence-availability bit
and provenance. The router should consume only information available at inference
time. Modality dropout and explicit availability masks should prevent a missing
pixel or catalog diagnostic from being mistaken for negative evidence. Expert
collapse, routing entropy, per-regime calibration and leave-one-expert-out
ablations must be reported.

## Literature position as of 2026-09-27

The novelty claim is provisional. Search results already show several nearby
ideas:

- [Yu et al. (2019)](https://arxiv.org/abs/1904.02726) separate TESS triage and
  vetting with deep learning.
- [Schanche et al. (2018)](https://arxiv.org/abs/1811.07754) find that combining
  random forests and CNNs improves wide-field transit classification.
- [ExoNet (2026)](https://arxiv.org/abs/2604.15560) uses multimodal late fusion
  and attention for light curves and stellar parameters.
- [EXOVEIL (2026)](https://arxiv.org/abs/2606.02778) uses self-supervised stellar
  modelling and conformal prediction for transit detection.
- [Ni et al. (2024)](https://proceedings.mlr.press/v238/ni24a.html) demonstrate
  input-dependent expert routing for time-series forecasting.
- [Ticinovic and Han (2026)](https://proceedings.mlr.press/v332/ticinovic26a.html)
  show that multimodal mixtures can lose intended expert specialization, so it
  must be measured rather than assumed.

The targeted gap found in this search is **per-candidate routing among separately
audited exoplanet diagnostic experts, with visible competence maps, missing-evidence
masks, disagreement and abstention**. Failure to find a prior paper is not proof
of novelty; a systematic ADS/arXiv review and expert review are required before
using “first” or “novel” in a manuscript.

## Paper-grade validation

Freeze architecture and metrics before a new evaluation. Use host-disjoint and
future-sector splits, injection/recovery and scrambled or inverted controls.
Compare every expert, fixed averaging, stacking, the contextual gate, and a
same-parameter dense multimodal model. Primary outcomes should include
precision-recall, Brier/NLL calibration, recall at a fixed human-review budget,
selective risk versus coverage, performance with missing diagnostics and compute.
The watcher can then provide the prospective evaluation, but it must not retrain
or retune the frozen gate after seeing those sectors.
