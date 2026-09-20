# Kepler–TESS input audit

The inputs are structurally compatible, but their distributions and preprocessing differ substantially. This is evidence of a transfer problem; it does not identify the contribution of each difference to model accuracy. No data, checkpoints, thresholds, or existing predictions were changed.

The audit compares **3,853 Kepler training candidates** with **1,548 TESS training candidates**, both overall and separately by class. It checks saved test predictions descriptively, without selecting a new threshold or model. The TESS test remains a previously consulted benchmark.

## Checks that passed

- Both missions use global `(200, 3)` and local `(100, 3)` views, the same seven scalar features, and the same channel-major flat ordering.
- Labels match manifest rows; arrays are finite; the three engineered features recompute from the stored views.
- Saved source normalization matches the original Kepler training rows. The preceding transformer evaluation replayed its Kepler validation predictions exactly.
- Both training cohorts have median global/local bin coverage of 100%. Missing bins are not a widespread explanation for this transfer gap.

## Measured differences

| Training feature | Kepler median | TESS median |
| --- | ---: | ---: |
| Global view: median within-bin scatter | 0.7930 | 0.7348 |
| Local view: median within-bin scatter | 0.7903 | 0.7314 |
| Scaled local dip-strength feature, planet labels only | 0.6254 | 1.3229 |
| BLS likelihood power, planet labels only | 186.81 | 769.51 |
| BLS best-search period, days | 15.73 | 6.96 |
| Catalog period, days | 4.31 | 3.60 |
| Positive-label fraction | 39.06% | 54.07% |

The global scatter distribution has a **KS distance of 0.787 overall and 0.918 for planet labels**. KS distance measures the largest difference between cumulative distributions, from 0 (identical) to 1 (fully separated). These are descriptive candidate-level distances; candidates can share stars, so no independent-sample significance claim is made.

Feature–label associations also change: median scaled dip strength is **1.009 for Kepler negatives versus 0.625 for positives**, but **0.769 for TESS negatives versus 1.323 for positives**. BLS likelihood power shows a similar reversal. A model relying on those associations could transfer poorly, but this audit does not prove either model relies on them.

Scatter and dip strength here are computed after robust scaling; they are **not absolute photometric noise or physical transit depth**. These measurements do not establish that TESS is noisier. `bls_snr` is the inherited name for BLS likelihood power, not a calibrated signal-to-noise ratio; `feat_odd_even` compares alternating bins, not odd/even transit events. The BLS best-search period is star-level context and need not equal the catalog candidate period.

## Preprocessing differences and clipping check

The legacy Kepler path stitches quarters, applies symmetric five-sigma clipping with interpolation, and then a rolling-median detrend. It does not protect known transit windows or mask companion transits. TESS uses strict quality filtering, detrends separately within sectors and gaps while protecting known transit windows, and masks companion transits before folding. Both paths then use the same folding, robust scaling, binning, and scalar-feature functions.

On **one synthetic two-minute curve** containing a 10,000 ppm transit and 100 ppm Gaussian noise, the legacy Kepler function erased the dip (measured residual depth approximately −41 ppm); the TESS function retained approximately 9,997 ppm. This isolates a possible failure mechanism in the functions. It is not a measurement of how many real Kepler transits were erased, and the common synthetic cadence does not reproduce the Kepler observing setup.

A separate check of existing raw caches sampled **24 Kepler training candidates per label**, using seed 42. All 48 caches were available. The legacy clipping rule flagged some in-transit samples for **6 candidates**, with **none exceeding 50% of in-transit samples**. This limited sample does not support attributing the entire transfer failure to clipping. It measures flags at catalog transit times, not changes in classification accuracy or the fraction of genuine transit signal lost.

## Why the transformer accuracy is low

The saved transformer predicts positive for only **63 of 183 TESS positive labels**, missing 120. Their median predicted probability is **0.178**, below its frozen Kepler-validation threshold of **0.725**. This is not solely a threshold issue: its AP is also lower than the frozen CNN's (0.7146 versus 0.8021).

The measured distribution changes, differing preprocessing, and changed candidate populations are plausible contributors. The audit cannot separate their causal effects or explain why this particular transformer is more affected than this particular CNN. Different training recipes and one seed further limit interpretation.

The recommended next experiment is a small, controlled preprocessing comparison using **training stars**, preserving transits in both missions. Inspect whether input distributions become more comparable before rebuilding any full dataset or training a hybrid. Existing datasets/results should remain the reference. No such preprocessing change has been made in this audit.

## Evidence and reproduction

- [Feature distributions by class](feature_distributions.csv), [distribution figure](distributions.png), [PDF](distributions.pdf).
- [Source-normalized scalar outliers](normalization_outliers.csv) and [saved prediction summary](prediction_summary.csv).
- [Synthetic clipping measurements](synthetic_clipping.csv), [figure](clipping_demonstration.png), [PDF](clipping_demonstration.pdf).
- [Real-cache clipping sample](kepler_raw_clipping_sample.csv), [summary](summary.json), and [provenance](provenance.json).

Run from the repository root, using a new or empty destination:

```bash
python scripts/analysis/audit_tess_inputs.py \
  --base_dir "$PROJECT_ROOT" \
  --output_dir outputs/tess_input_audit
```

The script reads the prepared datasets and completed CNN/transformer evaluations. It optionally reads available raw Kepler caches for the sample check and records missing caches. It performs no downloading, dataset rewriting, training, inference, or threshold search. Hashes record and verify the source artifacts; the report contains summaries rather than additional training inputs.
