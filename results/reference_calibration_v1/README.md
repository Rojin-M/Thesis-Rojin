# Experimental reference calibration

This artifact calibrates the frozen reference CNN against **CP/KP versus FP/FA
labels in the curated TESS benchmark**. It does not provide the actual probability
that a blind-search proposal is a planet. Runtime reports retain
`planet_probability: null` and label the separate output **Experimental TESS
benchmark estimate**.

The fixed seed-2718 partition uses only the original TESS validation set:

| Role | Candidates | Star/proximity groups | CP/KP | FP/FA |
| --- | ---: | ---: | ---: | ---: |
| Calibration fit | 81 | 79 | 42 | 39 |
| Descriptive audit | 82 | 79 | 44 | 38 |

The roles are disjoint by candidate and protected star/proximity group. The
remaining validation selection subset is not used. Original test predictions
are never fitted or evaluated by this command. Prepared hashes, split identities,
Kepler-overlap exclusions, model bytes and frozen Kepler training normalization
are checked before inference. The checkpoint and preprocessing stay unchanged.

One-parameter temperature scaling follows the post-processing method studied by
[Guo et al. (2017)](https://proceedings.mlr.press/v70/guo17a.html).
It minimizes calibration-subset log loss, with
the existing fixed bounds 0.05–20 and an identity fallback. The fitted temperature
is **3.407947925485303**. No method, threshold or hyperparameter is selected using
the audit subset or live candidates.

| Audit metric | Raw model | Temperature scaled |
| --- | ---: | ---: |
| Brier score | 0.25727 | 0.19988 |
| Log loss | 1.00979 | 0.58410 |
| Ten-bin ECE | 0.24041 | 0.11263 |

These are descriptive results on 82 labelled benchmark examples, not prospective
search validation. Local support is sparse: the 20–30% estimate bin contains
12 examples, of which six have positive labels. That bin fraction is not an
individual-object confidence interval. Empty bins explicitly report zero support;
the runtime suppresses numeric estimates for them and for logits outside the
observed calibration range.

For example, a raw reference logit of −3.41267 maps to approximately **26.9% on
this benchmark scale**. It cannot be interpreted as a 26.9% probability that the
corresponding blind proposal is a planet. Curated class prevalence, known versus
inferred ephemerides, inferred-companion masks, observation coverage, detection
selection and astrophysical false-positive scenarios differ. Missing centroid,
nearby-source, survey-calibration or registry evidence is not repaired by this
transformation.

The domain limitation is substantive: benchmark calibration does not establish
calibration under changed input distributions or selection. See the empirical
study of calibration under dataset shift by
[Ovadia et al. (2019)](https://papers.neurips.cc/paper_files/paper/2019/hash/8558cb408c1d76621371888657d2eb1d-Abstract.html).

Rebuild from the repository root on two CPU threads:

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -m scripts.experiments.calibrate_reference
```

Existing artifacts are immutable: identical reconstruction succeeds, while a
different result requires a new versioned output directory and review. Source
and input receipts, fixed selection identities, per-row predictions, audit
metrics and reliability bins are included here. The saved pilot experiment spec
is checked when present but is not needed to reconstruct the fixed partition.
Rebuilding requires the recorded prepared arrays and reference model; the
website needs only the small committed `calibration.json`.

The runtime module pins the SHA256 of that JSON, checks its size and contract,
and suppresses the estimate for absent or corrupted calibration, incompatible
model/normalizer/input contracts, invalid scores, non-TESS inputs and synthetic
cohorts. It never changes the original CNN score or writes candidate evidence.

[Validation](validation.json) records 12 focused calibration tests, 43 store/API/
export/model regression tests, six UI rendering checks and a real-browser check.
Candidate lists, dossiers and exports agree; original evidence and review notes
remain unchanged. Missing and synthetic inputs show no percentage, and desktop
and 390px mobile layouts passed. Both research servers loaded the feature and
the new-target watcher resumed after its current cycle was safely drained.
