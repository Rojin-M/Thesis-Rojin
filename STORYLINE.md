# From tabular baselines to metadata-assisted transit classification

This project classifies known Kepler transit candidates as confirmed planets or false positives. The experimental question is how much useful information comes from the light-curve representation, the model, and auxiliary catalog measurements.

The [README](README.md) gives the executable workflow. The [published results](results/README.md) and [complete model comparison](results/comparison/COMPARISON.md) contain the latest completed reproduction. Sections 2–8 describe the historical development, including 37 historical/study runs and an earlier isolated reproduction whose artifacts are archived separately. Section 9 reports the latest runs; historical scores are retained to show what repeated and what changed. Classification metrics were checked against saved predictions. AP means scikit-learn average precision, not trapezoidal area under a precision–recall curve.

CNN v1 remains the main practical model: it combines strong five-seed results with a smaller model. The latest transformer v1 has a tiny mean AP lead, while CNN v1 has higher mean accuracy, F1, and ROC-AUC. Both metadata extensions improve all four metrics in every matched seed.

## 1. Make the data reusable and define the evaluation

Raw light curves are cached per star. Preprocessing detrends and folds each candidate using its catalog ephemeris, constructs global and local views, and saves reusable candidate caches. Separating downloading from feature preparation made it possible to iterate without fetching the light curves again. A BLS duration/period constraint was corrected during development; candidate preparation was also parallelized. These are engineering improvements, not measured classification gains: no controlled before/after performance experiment was preserved for them.

The published v0 contains 5,518 candidates around 4,929 stars: 2,128 confirmed planets and 3,390 false positives. Candidates around the same star stay together in the saved split.

| Split | Candidates | Confirmed planets | Stars |
| --- | ---: | ---: | ---: |
| Training | 3,853 | 1,505 | 3,449 |
| Validation | 836 | 327 | 740 |
| Test | 829 | 296 | 740 |

| Input | Shape | Meaning |
| --- | --- | --- |
| `X_global` | 5,518 × 200 × 3 | Folded global view |
| `X_local` | 5,518 × 100 × 3 | Transit-centered local view |
| `X_scalar` | 5,518 × 7 | Engineered shape and BLS features |
| `X` | 5,518 × 907 | Flattened views plus scalar features |

The view channels contain mean flux, scatter, and a validity mask. Neural-model flux/scatter and scalar normalization use training rows; the mask is preserved. The feature named `feat_odd_even` compares alternating bins, **not separate odd and even transit events**.

The saved split and base arrays remain identical between v0 and v1. The models use validation data for model/threshold selection. The test split was inspected repeatedly during development, so it is a development-era holdout, not an untouched final assessment.

**Finding:** the pipeline supports comparisons on a fixed candidate pool with disjoint star groups. This reduces a clear leakage route; it does not establish that every possible source of bias has been eliminated.

## 2. Establish tabular baselines

**Question:** are a few scalar measurements enough, or does the full transit representation matter?

HistGradientBoosting (HGB) was trained on the scalar features and on the full flattened input. The full-feature workflow includes a small validation-driven regularization search; its selected configuration was the base configuration. The scalar reference used that base configuration without the search.

| Historical individual run | Test accuracy | Test F1 | Test AP | Test ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| HGB scalar | 0.7998 | 0.7530 | 0.7782 | 0.8772 |
| HGB full | 0.8938 | 0.8581 | 0.9225 | 0.9598 |

**Finding:** the full representation was substantially more useful in these runs. This is consistent with transit-shape information being lost when only the scalar summary is used. It does not identify which bins or channels matter most.

The full HGB reached training AP of about 0.999 while test AP was 0.9225, so fitting the training set almost perfectly did not remove the generalization gap. Three recorded full-HGB runs returned the same result; they are repetitions of the same seed/settings, not three independent seeds for uncertainty estimation.

Reproduce with the README's `tabular` stage and `configs/hgb_scalar.json` / `configs/hgb_full.json`.

## 3. Explore the multi-view CNN

**Question:** can separate global, local, and scalar branches learn a useful representation?

The CNN combines the branch embeddings for classification. Development explored stronger transit branches, a wide branch over flattened inputs, and additional regularization.

| Historical experiment | Test AP | Test F1 |
| --- | ---: | ---: |
| Initial CNN | 0.8813 | 0.8409 |
| Early wide-branch experiment | 0.8153 | 0.7767 |
| Stronger transit branches | 0.9259 | 0.8685 |
| Subsequent ranking-metric rerun | 0.9315 | 0.8682 |
| Added label smoothing and input noise | 0.9128 | 0.8631 |
| Plain rerun | 0.9238 | 0.8627 |
| Rerun later used for blending | 0.9266 | 0.8734 |

**Finding:** the final focused multi-view design was more promising than the initial and early wide-branch experiments. The additional regularization did not improve the recorded result. These are exploratory comparisons: several architecture details changed, so the table does not isolate one layer or prove that wide branches or regularization are generally harmful.

Some early runs do not have saved source snapshots, and an exact matching source version has not been recovered from Git. Their predictions and metrics remain valid historical evidence, but the repository does not claim to reconstruct those exact earlier architectures. The `cnn-baseline` and `cnn-ablations` stages run the preserved final architecture, its wide-branch variant, and its regularized variant. They are labeled separately in the reproduction results.

## 4. Combine CNN and HGB predictions

**Question:** do the two models make sufficiently different errors for a blend to help?

The historical blend selected its weight and classification threshold on validation F1: 0.58 CNN probability plus 0.42 HGB probability. Its test AP was **0.9415**, compared with 0.9266 and 0.9225 for its component runs; test F1 was **0.8851**.

**Finding:** the blend improved on these particular component runs. Complementary errors are a plausible explanation, but there was no multi-seed ensemble study. Three saved executions of the same blend gave the same result and are not counted as independent evidence. The implemented experiment is probability blending; a learned logistic stacking option exists in the code but has no reported experiment here.

The `blend` stage explicitly uses the reproduced CNN baseline and full HGB records. Its newly validation-selected weight can differ from the historical weight.

## 5. Measure CNN variability across seeds

**Question:** how representative is one good CNN run?

The chosen fixed CNN recipe was repeated with training seeds 42–46, keeping the saved data split unchanged. All five runs are included. Validation AP selected each checkpoint; validation F1 selected its threshold.

The original five-seed v0 mean test AP was **0.9105 ± 0.0115**, below the best earlier individual run. The SD is sample standard deviation across training seeds, not a confidence interval or uncertainty across datasets.

**Finding:** an attractive individual result is not a reliable summary of the model's typical performance. The multi-seed comparison provides a more defensible basis for evaluating the metadata extension.

Learning-curve training metrics are collected with changing weights and dropout during optimization; validation uses evaluation mode. Final saved train/validation/test metrics use the selected checkpoint. These quantities should not be confused when interpreting a train–validation gap.

## 6. Add auxiliary catalog metadata without changing the light curves

**Question:** does candidate context help beyond the existing transit representation?

The v1 builder preserves every v0 candidate, label, split, and base array. It adds 11 auxiliary inputs: five stellar measurements, two irradiation-related estimates, and four centroid measurements. Absolute sky coordinates were excluded by modeling choice. Feature definitions, units, transforms, fitted statistics, and source hashes are saved in `data/processed/kepler/v1/aux_preprocessing_v1.json`; field meanings follow the [NASA KOI column definitions](https://exoplanetarchive.ipac.caltech.edu/docs/API_kepcandidate_columns.html).

Fixed transformations are followed by median imputation and standardization fitted only on training rows. No candidate is dropped for missing auxiliary values: 412 have at least one missing selected value, and 31 have all selected values missing before imputation. The missingness mask is stored for auditing and is not appended to model inputs.

The CNN's optional auxiliary branch adds a 64-value embedding to the existing classifier inputs. With five matched training seeds:

| Historical CNN test metric | v0 | v1 + metadata |
| --- | ---: | ---: |
| Accuracy | 0.8893 ± 0.0165 | 0.9332 ± 0.0069 |
| F1 | 0.8548 ± 0.0161 | 0.9100 ± 0.0080 |
| AP | 0.9105 ± 0.0115 | 0.9628 ± 0.0027 |
| ROC-AUC | 0.9538 ± 0.0059 | 0.9810 ± 0.0008 |

All four metrics improved in all five original matched seeds.

**Finding:** the combined metadata-and-branch extension improved this classifier consistently. Stellar context and centroid diagnostics may help distinguish planet-like signals from false positives, but the experiment does not establish which feature group is responsible. Inputs and model capacity both changed. This is catalog-assisted candidate classification, not classification from light curves alone or blind planet discovery.

## 7. Investigate the transformer

A transformer is a model architecture; it is separate from transfer learning between Kepler and TESS. This repository's transformer classifies the same Kepler candidates using global/local sequences and scalar inputs.

The original single run had test AP **0.8364**. Inspection identified an initial `LayerNorm(3)` applied across flux, scatter, and validity-mask channels. Such normalization can make differently scaled input patterns nearly indistinguishable. The experiment bypassed only this initial normalization, preserving internal encoder normalization and the remaining shared settings.

| Historical validation-only screen | Original input normalization AP | Bypassed AP |
| --- | ---: | ---: |
| Seed 42 | 0.8536 | 0.9471 |
| Seed 43 | 0.8650 | 0.9509 |
| Mean | 0.8593 | 0.9490 |

**Finding:** bypassing the input normalization improved both screening seeds. Suppression of useful amplitude information is a plausible mechanism, supported by inspecting the transformation, but the precise cause is not fully isolated. This is a two-seed validation result, not a five-seed test comparison of normalization modes.

The chosen normalization mode was frozen before the final metadata comparison. Its two screening runs were reused, three further v0 seeds were trained, and v1 used all five seeds. Test evaluation was deferred until all 12 training runs were complete. All completed controlled runs used float32; they should not be treated as an isolated comparison with the older autocast run.

| Historical transformer test metric | Selected v0 | v1 + metadata |
| --- | ---: | ---: |
| Accuracy | 0.8758 ± 0.0158 | 0.9288 ± 0.0098 |
| F1 | 0.8345 ± 0.0168 | 0.9037 ± 0.0130 |
| AP | 0.8842 ± 0.0149 | 0.9600 ± 0.0015 |
| ROC-AUC | 0.9422 ± 0.0079 | 0.9779 ± 0.0010 |

All four metrics improved in every original matched seed.

The historical `attention_dropout` argument remains recorded-only; effective attention dropout follows `dropout` (0.15 in this study). Cloned encoder initialization was also retained. Neither was changed while testing input normalization and metadata, so this study makes no claim about their effects.

## 8. Historical conclusions and the earlier isolated reproduction

The original overall comparison includes tabular baselines, blending, the original transformer, and both five-seed model families. The strongest original mean AP is CNN v1 at 0.9628; transformer v1 is close at 0.9600. The CNN has about 0.82 million parameters with metadata, versus about 2.19 million for the transformer. The different architectures use different training recipes and precision modes, so their small score difference is descriptive rather than proof of architectural superiority.

The historical conclusions were:

1. Full transit inputs were more useful than the scalar-only HGB baseline in the recorded experiments.
2. CNN development produced useful positive and negative exploratory results, but individual reruns varied enough to justify five-seed reporting.
3. A validation-tuned blend improved the particular CNN/HGB pair studied.
4. Metadata improved both neural model families consistently across the original five seeds.
5. The transformer's input representation mattered substantially in the controlled validation screen; architectural complexity alone did not ensure a strong result.

The complete frozen workflow was previously rerun from an isolated checkout containing processed data only. Those reproduction results were archived separately from the original reference. Both HGB baselines reproduced their original scores. That reproduction's CNN baseline had AP 0.9262; its wide and regularized variants had AP 0.7800 and 0.9057. Its blend reached AP 0.9445.

| Five-seed test AP | Original reference | Isolated reproduction |
| --- | ---: | ---: |
| CNN v0 | 0.9105 ± 0.0115 | 0.9144 ± 0.0130 |
| CNN v1 + metadata | 0.9628 ± 0.0027 | 0.9612 ± 0.0033 |
| Transformer v0 | 0.8842 ± 0.0149 | 0.8820 ± 0.0141 |
| Transformer v1 + metadata | 0.9600 ± 0.0015 | 0.9604 ± 0.0024 |

The reproduction again improved accuracy, F1, AP, and ROC-AUC in every matched seed for both metadata extensions. Its normalization screen improved mean validation AP from 0.8601 to 0.9363 and again selected the bypass. These are repeated training experiments on the same split, not new independent test data.

Seeded GPU execution is not bit-for-bit deterministic across environments. Exact scores and stopping epochs varied, while the main pattern survived. No hyperparameters were retuned in response to the reproduction test scores. Model/training computations and processed-file contents were preserved during repository cleanup; path handling and execution/analysis entry points changed.

## 9. Latest completed reproduction and the practical conclusion

The published export contains all 26 final evaluated runs: two HGB baselines, three individual CNN configurations, one blend, and five seeds for each neural v0/v1 variant. The two additional legacy-normalization transformer runs remain validation-only evidence. The [comparison table](results/comparison/COMPARISON.md) reports all model families, including variants that performed worse.

Both [HGB baselines](results/tabular/README.md) reproduced their original scores. The latest individual CNN baseline reached test AP 0.9226, compared with 0.8014 for the wide branch and 0.9138 for additional regularization. These final-architecture experiments again favor the baseline; they do not reconstruct every earlier exploratory architecture.

| Latest five-seed test result | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| CNN v0 | 0.8926 ± 0.0115 | 0.8594 ± 0.0114 | 0.9139 ± 0.0138 | 0.9558 ± 0.0068 |
| CNN v1 + metadata | 0.9327 ± 0.0087 | 0.9082 ± 0.0104 | 0.9605 ± 0.0042 | 0.9802 ± 0.0015 |
| Transformer v0 | 0.8741 ± 0.0074 | 0.8386 ± 0.0078 | 0.8859 ± 0.0093 | 0.9436 ± 0.0046 |
| Transformer v1 + metadata | 0.9226 ± 0.0073 | 0.8962 ± 0.0087 | 0.9606 ± 0.0025 | 0.9785 ± 0.0016 |

Values are mean ± sample SD over seeds 42–46 on the same fixed split. In both the [CNN study](results/cnn/README.md) and [transformer study](results/transformer/README.md), metadata improved accuracy, F1, AP, and ROC-AUC in all five matched seeds. Mean AP increased by 4.66 percentage points for CNN and 7.47 points for the transformer. This repeats the strongest finding from the historical runs, while still comparing added inputs and branch capacity together.

The transformer's validation-only normalization screen again selected bypassing the initial `LayerNorm(3)`: mean validation AP increased from 0.8548 to 0.9445. The choice was frozen before test evaluation within this study. Its effect remains supported by two validation seeds, rather than a five-seed test comparison of normalization modes.

The latest [blend](results/blend/README.md) selected 0.52 CNN probability plus 0.48 HGB probability and a threshold of 0.51 on validation F1. Test AP improved to 0.9431 from the single CNN baseline's 0.9226 and HGB's 0.9225. Test F1, however, was 0.8754 versus the single CNN baseline's 0.8760. The blend found 281 of 296 planets with 65 false positives; the CNN found 265 with 44 false positives. The extra 16 detected planets came with 21 more false alarms. Validation F1 improvement therefore did not translate into test F1 improvement, even though ranking improved. This comparison uses the individual CNN component, not the five-seed CNN mean.

**CNN v1 is the main practical model.** Transformer v1 has the highest mean test AP at 0.960631 versus CNN v1's 0.960548, a difference of only 0.000083, far smaller than either model's observed seed SD. This does not establish a clear AP advantage. CNN v1 has higher mean accuracy, F1, and ROC-AUC and about 0.82 million parameters, compared with about 2.19 million for transformer v1. The comparison is descriptive because the model families use different training recipes and precision modes; the transformer remains a useful close competitor.

The published results come from repeated training on the same previously consulted holdout, not a new independent assessment. Further work can test feature groups, additional independent splits, or a new untouched dataset. TESS preparation and Kepler-to-TESS transfer are separate thesis extensions; the Kepler results above do not establish cross-mission performance.

## 10. Start the thesis extension with TESS acquisition

After the Kepler practical, the next step is to prepare TESS inputs for a future cross-mission comparison. The acquisition script saves the NASA TOI catalog and fetches native SPOC two-minute light curves through Sector 105 for stars with `CP`, `KP`, `FP`, or `FA` candidates. All catalog candidates on those stars are retained so that candidate-specific labels can be matched to transits during preprocessing. The [README](README.md#thesis-extension-fetch-tess-light-curves) is the command reference.

The first download plan included 95,414 files totaling about 783 GiB. Most were validation products: PDFs alone accounted for about 446 GiB, although the planned light-curve model does not read them. We narrowed acquisition to the catalog and light curves, about 29 GiB of light curves in that original plan. PDFs, validation time series, XML reports, and pixel files can be requested separately if a later experiment needs them. Using the light-curve URLs in archive observation records also avoids listing every validation product.

To reduce time spent waiting for individual requests, we added concurrent transfers and selected four workers for our server. In a small network test with the same eight light curves (14.80 MiB), sequential transfers took 5.9–6.5 seconds, while four workers took 2.3–2.4 seconds, about 2.6 times faster. Eight workers were less consistent. These measurements streamed files into memory and do not establish the speed of a full download to disk. Completed files have checksum receipts so interrupted runs can reuse them.

The replacement bulk download completed on **9 September 2026**. The saved `data/raw/tess/metadata/download_summary.json` records all **15,744 planned light-curve FITS files**, totaling **28.6 GiB**, with **zero failed downloads** using four workers.

TESS acquisition is complete. The preparation stage below converts these files into candidate-specific model inputs. The practical results above remain Kepler experiments.

## 11. Prepare TESS inputs and check a small batch

On **11 September 2026**, we implemented TESS candidate selection, light-curve preparation, and grouped splits. Applying the common period/duration limits and a conservative five-arcsecond exclusion around processed Kepler stars leaves **2,237 candidates on 2,129 TESS identifiers** before light-curve quality and coverage checks: **1,209 planet labels and 1,028 false-positive/false-alarm labels**. Sky proximity is used to prevent possible leakage; it does not establish a definitive cross-catalog identity. Nearby TESS identifiers are also grouped together.

The new inputs have the same global/local view shapes and seven feature definitions as Kepler v0. TESS times are aligned with catalog transit epochs, and known transit windows are protected during sector- and gap-local detrending. Companion transits are masked before folding each target. A candidate must retain at least two sufficiently sampled expected transit events. This criterion checks observation coverage, rather than whether a planet signal is actually detected. Missing companion ephemerides and failed quality/coverage checks are audited.

The balanced pilot completed with **24 of 24 candidates retained**, comprising **12 positive and 12 negative labels**. Its time-series and folded plots were inspected. Several planet-labelled examples show clear phase-zero dips; others are weak or noisy, including the high-scatter TOI-1690.01. False positives include both eclipse-like and noise-like curves. No labels were changed based on this visual inspection. All pilot groups are reserved for the full training split, and the pilot has no test split.

The artifact checker verified feature ordering, finite arrays, output hashes, and normalization reconstructed from the **3,853 original Kepler training rows**. Both existing neural architectures accepted a small pilot batch with finite forward outputs. These were interface checks with random model initialization, so they provide no classification score.

The full run completed with eight workers in `tmux` in **129.3 minutes**, retaining **2,208 candidates on 2,105 TESS identifiers**, grouped into **2,102 split groups**. Of the 29 exclusions, 15 lacked usable companion ephemerides and 14 had insufficient sampled transit events. The retained labels comprise **1,191 positives and 1,017 negatives**.

| Fixed seed-42 split | Candidates | Positive labels | Negative labels |
| --- | ---: | ---: | ---: |
| Training | 1,548 | 837 | 711 |
| Validation | 325 | 171 | 154 |
| Test | 335 | 183 | 152 |

All 24 inspected pilot groups belong to training. The completed dataset passed the artifact checker, including disjoint stars/groups, all nine output checksums, source normalization, and both model interfaces on training rows. All **81 repository tests** passed, and the seven published Kepler artifacts retained their recorded hashes. The exact Kepler BLS search is computed once per star, with completed star features cached for recovery. The [README](README.md#thesis-extension-prepare-tess-inputs) provides the reproducible commands.

The TESS quality filtering, transit protection, and companion masking differ from the preserved Kepler preprocessing and must be considered when interpreting transfer. Separate source-training normalization files prevent accidental fitting on the target test data. The first comparison below uses these verified inputs.

## 12. First CNN comparison on TESS

On **11 September 2026**, we compared the existing Kepler CNN v0 with the same architecture trained from scratch on TESS. Both models were evaluated on the same **335 TESS test candidates: 183 positive and 152 negative labels**. The data, source checkpoint, training recipe, and selection rules were recorded before training in `outputs/tess_baseline/seed42/protocol.json`. The [README](README.md#thesis-extension-compare-cnns-on-tess) provides the command.

The TESS model retained the source model's training recipe and seed 42. Training stopped after 50 epochs; TESS validation AP selected epoch 40, and validation F1 selected its threshold of **0.165**. The frozen Kepler model retained its original epoch-35 weights, Kepler training normalization, and Kepler validation threshold of **0.83**. This source evaluation is zero-shot transfer: it uses the trained Kepler model directly on TESS inputs.

| Single-seed TESS test result | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| TESS-trained CNN v0 | 0.7672 | 0.8020 | 0.8595 | 0.8401 |
| Frozen Kepler CNN v0 on TESS | 0.7254 | 0.7294 | 0.8021 | 0.7767 |

The TESS-trained model has higher AP by **5.74 percentage points** in this run. At their respective validation-selected thresholds, it recovered **158 of 183 positive labels with 53 false positives**, versus **124 positives with 33 false positives** for the frozen Kepler model. The extra 34 recovered positives came with 20 additional false positives. These threshold-based counts describe different operating points; AP compares their probability rankings without selecting a threshold.

The saved predictions reproduce all reported metrics, and all 14 recorded comparison artifacts passed checksum verification. The run's predictions, metrics, TESS-trained checkpoint, and completion record are under `outputs/tess_baseline/seed42/`. The protocol references the preserved Kepler checkpoint under `outputs/reproduce/cnn_baseline/`.

The available TESS data is sufficient for this initial supervised and cross-mission baseline. This is one seed on a curated labelled TOI subset, with different mission preprocessing and training cohorts. The result does not isolate the effect of the mission alone or establish performance on all TESS detections. Repeated seeds and later transfer experiments remain separate research steps.

Before the next experiment, we exported this completed comparison to [results/tess/cnn_baseline](results/tess/cnn_baseline/README.md). The export reconstructs metrics from saved predictions and includes confusion counts, preparation records, figures, protocols, and source hashes. The original checkpoints and predictions remain in local `outputs/`.

## 13. Evaluate the existing Kepler transformer on TESS

On **13 September 2026**, we applied the existing seed-42 Kepler transformer v0 to the same **335 TESS test candidates** used above. The source model was the Kepler-validation-selected input-normalization variant, which bypasses initial LayerNorm and has no auxiliary metadata branch. We retained its epoch-38 checkpoint, Kepler training normalization, and Kepler validation threshold of **0.725**. No model was trained or tuned on TESS for this step.

Before TESS inference, the evaluator checked source artifacts against the completed Kepler study and replayed all **836 Kepler validation predictions** on GPU 1 in float32. The maximum probability difference from the saved predictions was **zero**. It then saved the evaluation protocol and applied the checkpoint to the fixed TESS test rows. Source and prepared-data hashes remained unchanged, and the saved TESS predictions reproduced the metrics.

| Single-seed TESS test result | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| Frozen Kepler transformer v0 | 0.5761 | 0.4701 | 0.7146 | 0.7121 |
| Frozen Kepler CNN v0 | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| TESS-trained CNN v0 (reference) | 0.7672 | 0.8020 | 0.8595 | 0.8401 |

The transformer recovered **63 of 183 positive labels**, with **22 false positives**, **120 false negatives**, and **130 true negatives**. The frozen CNN recovered 124 positives with 33 false positives. These counts use different Kepler-validation thresholds. The transformer's AP was also lower by **8.76 percentage points**, so its weaker ranking cannot be explained only by the classification threshold. The exact validation replay supports correct checkpoint loading and source normalization; it does not establish the cause of poor transfer.

This is one seed on a previously consulted TESS benchmark. The architecture families have different training recipes, and mission preprocessing and cohorts differ. These results do not show that transformers generally transfer worse or predict how a combined CNN–transformer will perform. We preserved the source threshold and report the unsuccessful transfer result without retuning on TESS test labels.

The [README](README.md#thesis-extension-test-the-kepler-transformer-on-tess) provides evaluation and verification commands. Local evidence is in `outputs/tess_transformer/seed42/`; [results/tess/transformer_transfer](results/tess/transformer_transfer/README.md) contains the verified public comparison, figures, and provenance. All **84 repository tests** passed, including new checks for source-only normalization, fixed prediction order, and detection of changed inputs. Both TESS exports passed their source/output hash checks; existing Kepler numerical tables and figures remained unchanged. The CNN–transformer hybrid, repeated-seed transfer study, self-supervised pretraining, and habitability screening remain future work.

## 14. Audit input compatibility before adding model complexity

On **13 September 2026**, we compared **3,853 Kepler training candidates** with **1,548 TESS training candidates**, overall and separately by label. Shapes, feature order, finite values, source normalization, and recomputed engineered features passed. Median global/local coverage was 100% in both cohorts. We did not change data, models, or thresholds.

The strongest measured difference was the within-bin scatter channel: the global-view candidate-median scatter had KS distance **0.787 overall and 0.918 for planet labels**. The scaled local dip-strength median for planet-labelled examples was **0.625 in Kepler versus 1.323 in TESS**. Its ordering by class also reversed: Kepler negatives had larger median dip strength than positives, whereas TESS positives had larger median dip strength than negatives. BLS likelihood power showed a similar reversal. These are distributions of processed features, not physical transit depth or raw photometric noise; class/population differences and preprocessing remain confounded.

The legacy Kepler preprocessing clips five-sigma deviations without protecting transits. The TESS path protects known transit windows, uses sector/gap-local detrending, and masks companions. On one common synthetic two-minute curve with a 10,000 ppm injected transit, the legacy function removed the dip while TESS retained approximately 9,997 ppm. To avoid treating this demonstration as evidence of widespread damage, we also checked 48 randomly sampled Kepler training candidates (24 per label). Six had some transit-window samples flagged by the legacy clipping rule; none had a majority flagged. That check does not establish a clipping-caused loss in model accuracy.

The saved transformer's median probability for TESS positive labels was **0.178**, below its retained Kepler threshold of **0.725**; 120 of 183 positives were missed. Its lower AP also shows that changing the threshold alone would not remove the ranking gap. No new threshold or model was evaluated. The [audit report](results/tess/input_audit/README.md) contains tables, plots, synthetic and real-cache checks, and source hashes. The [README](README.md#thesis-extension-audit-kepler-and-tess-inputs) provides the command.

The audit supports investigating preprocessing and feature shift before a hybrid model. Its recommended next experiment was a small comparison on training stars using transit-preserving preprocessing for both missions; that experiment starts below. Existing datasets and predictions remain the reference.

## 15. Rebuild both missions with shared preprocessing

On **13 September 2026**, we implemented `shared_v1` and completed a training-only pilot in `tmux`. The full rebuild then started in `shared-preparation`, after repository tests and pilot verification passed. It completed and verified on **14 September 2026**; progress and completion are recorded under `outputs/shared_preparation/shared_v1/`.

The rebuild uses existing native Kepler long-cadence and TESS two-minute FITS files. Both readers apply quality filtering and align times to BJD TDB minus 2457000. The subsequent algorithm is shared: protect all catalog transit windows during a segment- and gap-local 1.5-day median detrend, mask companions before target folding, and calculate the same global/local views and seven features. BLS is computed once per star. The legacy names still apply: `bls_snr` is likelihood power and `feat_odd_even` compares alternating phase bins. Native cadences are retained, with cadence-aware sampling checks; this does not remove physical cadence, noise, or population differences.

The starting cohorts contain **5,518 Kepler and 2,208 TESS candidates**. Retained rows preserve their v0 labels and split membership. The full Kepler dataset retained **5,385** candidates and excluded 132 for insufficient sampled transit events and one for missing companion ephemeris. All **2,208 TESS candidates** were retained. The pilot selected four training candidates per label in each mission, plus any siblings on the selected stars. It retained **12 of 12 Kepler candidates (six per label) and eight of eight TESS candidates (four per label)**, with no exclusions.

We inspected plots comparing the old and rebuilt training views. Kepler transit dips remained visible, with changes to some baselines and scaled dip strengths. All global, local, and scalar arrays matched TESS v0 exactly on the eight TESS pilot candidates, as expected from reusing its transit-preserving algorithm. This check supports implementation consistency for that sample; it does not establish an accuracy improvement. No labels were changed or test examples inspected. The pilot verification and visual review are recorded in `outputs/shared_preparation/shared_v1/pilot_verification.json` and `pilot_review.json`.

New per-star artifacts go into `data/interim/{kepler,tess}/shared_v1/`, including `bls/`, `folded/`, and `views/`. Full datasets go into `data/processed/{kepler,tess}/shared_v1/`. Existing raw data, prepared versions, checkpoints, and reported results remain preserved. For subsequent source-to-target experiments, both missions use normalization fitted on the rebuilt Kepler training rows. Old checkpoints are not retrained or evaluated in this step.

We used four workers for the pilot and eight for the full preparation, with one numerical-library thread per worker. Per-star caching avoids repeating completed BLS searches on restart. All **94 repository tests passed**, including ten new checks for transit preservation at both cadences, time/quality interpretation, gaps, companion masking, sampling requirements, training-only pilot selection, original split membership, cache integrity, and legacy preview loading. Our queued wrapper required these tests to pass before the full command. The preparation command verifies dataset geometry, feature order, hashes, parent mappings, split separation, and source-training normalization before marking completion. The [README](README.md#thesis-extension-shared-kepler-and-tess-preprocessing) provides reproducible commands.

This is a controlled preprocessing experiment. The first CNN modelling comparison follows below. Old-versus-new comparisons use common retained test candidates where possible. Both benchmark test sets have already been consulted, so future scores retain that qualification.

## 16. Train a Kepler CNN on shared inputs and test TESS transfer

On **15 September 2026**, we trained the seed-42 v0 CNN recipe on the rebuilt Kepler inputs in `tmux`, selecting epoch 44 by Kepler validation AP and a **0.785** classification threshold by Kepler validation F1. The run used 3,759 training, 817 validation, and 809 test candidates. Source-only normalization matched the saved `shared_v1` statistics. Before TESS inference, the evaluator replayed all 817 shared-v1 and 836 v0 Kepler validation predictions with **zero maximum probability difference** and checked the frozen artifacts and fixed TESS test membership.

| Kepler-trained CNN on the same 335 TESS test candidates | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| Frozen v0 on shared_v1 TESS inputs | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| Frozen shared_v1 on shared_v1 TESS inputs | 0.7194 | 0.7099 | 0.7991 | 0.7828 |

The shared model recovered **115 of 183** positive TESS labels, with 26 false positives, 68 false negatives, and 126 true negatives. V0 recovered 124 positives, with 33 false positives, 59 false negatives, and 119 true negatives. The shared model's TESS AP was **0.0030 lower** and its F1 was **0.0195 lower**, while ROC-AUC was 0.0061 higher. This is no clear TESS transfer gain; threshold-based differences describe separate Kepler-validation operating points. The earlier TESS-trained CNN v0 remains a 0.8595-AP reference and was not retrained here.

On the **809 Kepler test candidates retained in both versions**, the shared model had AP **0.9422** versus **0.9239** for v0 and ROC-AUC **0.9674** versus **0.9606**. Its F1 was **0.8658** versus **0.8781**. The Kepler ranking gain therefore did not carry over to TESS. TESS retained the same split and labels; the rebuilt TESS views differ from v0 in four global-bin values on one candidate, and the v0 model's scores on the rebuilt test inputs match its earlier scores exactly.

The source training and validation cohorts differ because 133 Kepler candidates failed the new sampling checks, so the model comparison cannot identify preprocessing as the sole cause. This is one seed on previously consulted Kepler and TESS tests, with no seed uncertainty or independent cohort. [README](README.md#thesis-extension-first-cnn-result-on-shared-inputs) gives rerun and verification commands. Local checkpoints, predictions, and checksummed protocols are under `outputs/shared_cnn/`.

## 17. Train the selected transformer on shared inputs

On **15 September 2026**, we trained the seed-42 validation-selected `bypass_input_norm` transformer recipe in float32 on rebuilt Kepler data in `tmux`. The run selected epoch **53** by Kepler validation AP and threshold **0.745** by Kepler validation F1. It used 3,759 training and 817 validation candidates, reserving test inference until after selection. Its architecture and hyperparameters match the v0 reference; the source preparation and cohort changed. The evaluator replayed **all 817 shared-v1 and 836 v0 Kepler validation predictions exactly**, verified Kepler-training normalization and frozen artifacts, and applied both checkpoints to common test identities.

| Frozen Kepler transformer | Kepler AP, common 809 | TESS Accuracy | TESS F1 | TESS AP | TESS ROC-AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| v0 | 0.8911 | 0.5761 | 0.4701 | 0.7146 | 0.7121 |
| shared_v1 | 0.9068 | 0.6776 | 0.6842 | 0.7395 | 0.7432 |

Both TESS rows use the same **335 shared-v1 test inputs** and each source's unchanged Kepler training moments. The shared model recovered **117 of 183** positive labels, compared with 63 for v0, while false positives rose from 22 to 42. Its TESS AP increased by **0.0249** and ROC-AUC by **0.0311**; its F1 increased by **0.2141** at separate Kepler-validation thresholds. The AP gain shows some ranking improvement beyond a threshold shift, but its TESS AP of **0.7395** remains below the shared CNN's **0.7991**. On the common Kepler test set, transformer AP increased from **0.8911** to **0.9068** and F1 from **0.8411** to **0.8488**.

The 133 Kepler exclusions change source training and validation membership as well as preprocessing. This single-seed comparison on previously consulted Kepler and TESS benchmarks cannot assign the gain solely to preprocessing or establish seed uncertainty. CNN and transformer training recipes differ, so their cross-family gap is descriptive. The [README](README.md#thesis-extension-transformer-result-on-shared-inputs) has rerun and verification commands; `outputs/shared_transformer/tess_transfer/` holds checksummed protocols, predictions, and both matched comparisons. A hybrid model and repeated-seed transfer study remain future work.

## 18. Freeze Phase 1 before prospective discovery work

On **20 September 2026**, we closed the labelled-benchmark phase by verifying the full `shared_v1` preparation and reconstructing every saved CNN and transformer comparison metric from per-candidate predictions. The public milestone at [results/tess/shared_transfer](results/tess/shared_transfer/README.md) contains the common 809-candidate Kepler table, the common 335-candidate TESS table, figures, preparation summaries, protocols, and portable source hashes. No model was retrained for this export.

The audit found that the CNN evaluator source file had changed after its original TESS result recorded its code hash. Its saved inputs, result artifacts, and reconstructed metrics still passed. To restore an exact current-code chain, we repeated inference with the frozen checkpoints in `outputs/shared_cnn/tess_transfer_phase1/`. The comparison and both per-candidate prediction CSVs are byte-identical to the original; the old and new evaluator hashes and matching artifact hashes are preserved in `results/tess/shared_transfer/cnn_reevaluation.json`. The transformer protocol already matched its current code and passed directly.

This milestone does **not** claim a new architecture or a new planet discovery. It freezes what the existing labelled evidence supports: shared preprocessing improved the transformer in this single seed, did not improve CNN TESS AP, and did not remove the transfer gap. Both test sets were previously consulted, the source cohorts changed, and there is no seed uncertainty estimate. Future prospective screening should therefore start in a separate versioned area with unlabelled observations, locked thresholds, candidate identity checks, and human-vetting records rather than modifying this benchmark lineage.
