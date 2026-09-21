#!/usr/bin/env python3
"""Describe Kepler/TESS input differences without changing data or running models."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from scripts.data.check_tess_prepared import check_prepared
from scripts.data.kepler_pipeline_lib import PrepConfig, engineered_features, sigma_clip_and_detrend
from scripts.data.tess_dataset import apply_normalization, feature_names
from scripts.data.tess_preprocessing import TessPrepConfig, detrend_sector, transit_mask
from scripts.experiments.run_tess_baseline import _checked_predictions, _npz, _sha, _verify_files


def summarize(a, b):
    qa, qb = np.quantile(a, [.05, .5, .95]), np.quantile(b, [.05, .5, .95])
    return {"kepler_n": len(a), "tess_n": len(b),
            **{f"{mission}_{stat}": float(value) for mission, quantiles in (("kepler", qa), ("tess", qb))
               for stat, value in zip(("q05", "median", "q95"), quantiles)},
            "ks_distance": float(ks_2samp(a, b).statistic)}


def clipping_demonstration():
    """Same synthetic 2-minute series for both functions; not a Kepler population test."""
    rng = np.random.default_rng(42)
    time = np.arange(7 * 720, dtype=np.float64) / 720
    ephemeris = (2., 1., .125)
    inside = transit_mask(time, ephemeris)
    flux = 1 + rng.normal(0, .0001, len(time)) - .01 * inside
    kt, kf = sigma_clip_and_detrend(time, flux, PrepConfig(base_dir="."))
    tt, tf, _ = detrend_sector(time, flux, [ephemeris], TessPrepConfig())
    rows = []
    for name, t, f in (("input", time, flux), ("legacy_kepler_function", kt, kf), ("tess_function", tt, tf)):
        mask = transit_mask(t, ephemeris)
        rows.append({"series": name, "depth_ppm": float(1e6 * (np.median(f[~mask]) - np.median(f[mask])))})
    return pd.DataFrame(rows), (time, flux, kt, kf, tt, tf)


def raw_clipping_sample(base, manifest, indices, hashes):
    """Inspect 24 training candidates per label; do not rewrite any cached light curves."""
    training = manifest.iloc[indices]
    rows = []
    for label in (0, 1):
        cohort = training[training.y == label]
        for _, candidate in cohort.sample(n=min(24, len(cohort)), random_state=42).iterrows():
            path = base / "data/raw/kepler/lightcurves" / f"{int(candidate.kepid)}.npz"
            row = {"candidate_id": candidate.candidate_id, "y": label, "cache_available": path.is_file(),
                   "fraction_in_transit_flagged": np.nan}
            if path.is_file():
                hashes[str(path)] = _sha(path)
                with np.load(path, allow_pickle=False) as saved:
                    time, flux = saved["time"], saved["flux"]
                finite = np.isfinite(time) & np.isfinite(flux)
                time, flux = time[finite], flux[finite]
                median = np.median(flux)
                sigma = max(1.4826 * np.median(abs(flux - median)), 1e-6)
                clipped = abs(flux - median) > 5 * sigma
                if len(flux) < 200 or (~clipped).sum() < 50:
                    clipped[:] = False
                in_transit = transit_mask(time, (candidate.koi_period, candidate.koi_time0bk,
                                                candidate.koi_duration / 24))
                row.update(n_in_transit=int(in_transit.sum()), n_flagged_in_transit=int((clipped & in_transit).sum()),
                           fraction_in_transit_flagged=float(clipped[in_transit].mean()) if in_transit.any() else None)
            rows.append(row)
    return pd.DataFrame(rows)


def audit(base, output):
    base, output = base.resolve(), output.resolve()
    for protected in (base / "data", base / "outputs/reproduce", base / "outputs/tess_baseline"):
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError("Audit output must be separate from data and model runs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Audit output must be new or empty")
    prepared = base / "data/processed/tess/v0"
    checked = check_prepared(prepared)
    if checked["mode"] != "full":
        raise ValueError("Audit requires full TESS preparation")
    provenance = json.loads((prepared / "provenance.json").read_text())
    source_paths = {prefix: next(Path(p) for p in provenance["inputs"] if Path(p).name.startswith(prefix))
                    for prefix in ("dataset_kepler", "splits_kepler", "manifest_kepler")}
    paths = list(source_paths.values()) + [prepared / n for n in (
        "provenance.json", "preparation_summary.json", "dataset_tess_v0.npz", "manifest_tess_v0.csv",
        "splits_tess_v0_seed42.npz", "kepler_train_normalization.npz")]
    paths += [ROOT / p for p in ("scripts/data/kepler_pipeline_lib.py", "scripts/data/tess_preprocessing.py",
                                "scripts/data/tess_dataset.py", "training/cnn/train_kepler_cnn.py")]
    hashes = {str(p): _sha(p) for p in paths}
    with np.load(source_paths["dataset_kepler"], allow_pickle=True) as saved:
        kepler = {key: saved[key] for key in saved.files}
    tess = _npz(prepared / "dataset_tess_v0.npz")
    ks = _npz(source_paths["splits_kepler"])
    ts = _npz(prepared / "splits_tess_v0_seed42.npz")
    km = pd.read_csv(source_paths["manifest_kepler"], dtype={"candidate_id": str})
    tm = pd.read_csv(prepared / "manifest_tess_v0.csv", dtype={"candidate_id": str})
    stats = _npz(prepared / "kepler_train_normalization.npz")
    ki, ti = ks["train_idx"], ts["train_idx"]
    for dataset, manifest in ((kepler, km), (tess, tm)):
        np.testing.assert_array_equal(dataset["y"], manifest.y)
        flat_names, scalar_names = feature_names()
        np.testing.assert_array_equal(dataset["feature_names"].astype(str), flat_names)
        np.testing.assert_array_equal(dataset["scalar_feature_names"].astype(str), scalar_names)
        for key in ("X_global", "X_local", "X_scalar", "X"):
            if not np.isfinite(dataset[key]).all():
                raise ValueError(f"Nonfinite input: {key}")
        recomputed = np.stack([engineered_features(g[:, 0], l[:, 0])
                              for g, l in zip(dataset["X_global"], dataset["X_local"])])
        np.testing.assert_allclose(recomputed, dataset["X_scalar"][:, :3], rtol=1e-6, atol=1e-6)
        flattened = np.concatenate([dataset[key][:, :, channel] for key in ("X_global", "X_local")
                                    for channel in range(3)] + [dataset["X_scalar"]], axis=1)
        np.testing.assert_array_equal(dataset["X"], flattened)
    normalized = [apply_normalization({key: data[key][idx] for key in ("X_global", "X_local", "X_scalar", "X")}, stats)
                  for data, idx in ((kepler, ki), (tess, ti))]
    features = []
    for data, manifest in ((kepler, km), (tess, tm)):
        values = {str(name): data["X_scalar"][:, j] for j, name in enumerate(scalar_names)}
        values["catalog_period_days"] = manifest["koi_period" if "koi_period" in manifest else "period"].to_numpy()
        values["catalog_duration_hours"] = manifest["koi_duration" if "koi_duration" in manifest else "duration_hours"].to_numpy()
        for key in ("X_global", "X_local"):
            values[key + "_coverage"] = data[key][:, :, 2].mean(axis=1)
            values[key + "_median_scatter"] = np.median(data[key][:, :, 1], axis=1)
        features.append(values)
    rows = []
    for label in ("all", "0", "1"):
        ka = ki if label == "all" else ki[kepler["y"][ki] == int(label)]
        ta = ti if label == "all" else ti[tess["y"][ti] == int(label)]
        for name in features[0]:
            rows.append({"feature": name, "class": label,
                         **summarize(features[0][name][ka], features[1][name][ta])})
    distributions = pd.DataFrame(rows)
    outliers = pd.DataFrame([{"feature": str(name), "mission": mission,
                              "fraction_abs_source_z_gt3": float((abs(data["x_scalar"][:, j]) > 3).mean())}
                             for mission, data in zip(("Kepler train", "TESS train"), normalized)
                             for j, name in enumerate(scalar_names)])
    prediction_rows = []
    for directory in (base / "outputs/tess_baseline/seed42",):
        completion = json.loads((directory / "completion.json").read_text())
        _verify_files(directory, completion["artifacts"])
        for path in [directory / "completion.json"] + [directory / n for n in completion["artifacts"]]:
            hashes[str(path)] = _sha(path)
        for arm, record in completion["arms"].items():
            frame = pd.read_csv(directory / f"{arm}_predictions.csv", dtype={"candidate_id": str})
            metrics = _checked_predictions(frame, tm, ts["test_idx"], record["threshold"])
            for key, value in metrics.items():
                np.testing.assert_allclose(value, record["metrics"][key], rtol=0, atol=1e-12)
            for label in (0, 1):
                selected = frame[frame.y == label]
                prediction_rows.append({"model": record["name"], "class": label, "n": len(selected),
                    "threshold": record["threshold"], "predicted_positive": int(selected.prediction.sum()),
                    "median_probability": float(selected.probability.median())})
    demonstration, curves = clipping_demonstration()
    raw_sample = raw_clipping_sample(base, km, ki, hashes)
    report = {"status": "passed", "scope": "Training-only distribution audit plus descriptive reuse of saved test predictions",
              "schema_and_order_match": True, "engineered_features_recomputed": True,
              "source_normalization_verified": checked["source_normalization"],
              "kepler_train_candidates": len(ki), "tess_train_candidates": len(ti),
              "kepler_train_positive_fraction": float(kepler["y"][ki].mean()),
              "tess_train_positive_fraction": float(tess["y"][ti].mean()),
              "raw_clipping_sample": {"selection": "24 random training candidates per class, seed 42",
                                      "available": int(raw_sample.cache_available.sum()),
                                      "with_any_flagged_transit_samples": int((raw_sample.fraction_in_transit_flagged > 0).sum()),
                                      "with_majority_transit_samples_flagged": int((raw_sample.fraction_in_transit_flagged > .5).sum()),
                                      "limitation": "Legacy clipping rule on existing raw caches; not a measured effect on model accuracy"},
              "synthetic_demo": {"seed": 42, "cadence_seconds": 120, "days": 7, "period_days": 2,
                                 "duration_hours": 3, "injected_depth_ppm": 10000, "noise_sigma_ppm": 100,
                                 "limitation": "One artificial curve, not a measurement of damage in the real Kepler dataset"},
              "no_training_or_threshold_search": True}
    output.mkdir(parents=True, exist_ok=True)
    distributions.to_csv(output / "feature_distributions.csv", index=False)
    outliers.to_csv(output / "normalization_outliers.csv", index=False)
    pd.DataFrame(prediction_rows).to_csv(output / "prediction_summary.csv", index=False)
    demonstration.to_csv(output / "synthetic_clipping.csv", index=False)
    raw_sample.to_csv(output / "kepler_raw_clipping_sample.csv", index=False)
    report["source_normalization_verified"] = {k: v for k, v in checked["source_normalization"].items()
                                               if not k.endswith("path")}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    axes = axes.ravel()
    titles = ("Scaled dip strength", "BLS likelihood power", "BLS best-search period (days)",
              "Global view: median within-bin scatter")
    for ax, name, title in zip(axes, ("feat_depth", "bls_snr", "bls_period", "X_global_median_scatter"), titles):
        for values, idx, labels, color in ((features[0], ki, kepler["y"], "#0072B2"),
                                           (features[1], ti, tess["y"], "#D55E00")):
            mission = "Kepler" if color == "#0072B2" else "TESS"
            for label, style in ((0, "--"), (1, "-")):
                x = np.sort(values[name][idx[labels[idx] == label]])
                ax.step(x, np.arange(1, len(x) + 1) / len(x), color=color, linestyle=style,
                        label=f"{mission} {'planet' if label else 'negative'}", where="post")
        ax.set(title=title, ylabel="Fraction of training candidates", ylim=(0, 1))
        if name == "bls_snr":
            ax.set_xscale("symlog", linthresh=10)
        ax.set_xlim(left=0)
        ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("Training distributions by mission and label (no model fitting)")
    fig.tight_layout()
    fig.savefig(output / "distributions.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.5))
    for (time, flux), name in zip(zip(curves[::2], curves[1::2]), ("Input", "Legacy Kepler function", "TESS function")):
        keep = (time > .8) & (time < 1.2)
        ax.plot(time[keep], flux[keep], label=name, alpha=.8)
    ax.set(xlabel="Time (days)", ylabel="Relative flux", title="Same synthetic transit, two preprocessing functions")
    ax.legend(); fig.tight_layout()
    fig.savefig(output / "clipping_demonstration.png", dpi=180)
    plt.close(fig)
    for name, digest in hashes.items():
        if _sha(Path(name)) != digest:
            raise ValueError(f"Audit source changed: {name}")
    def portable(name):
        path = Path(name)
        return str(path.relative_to(base)) if path.is_relative_to(base) else str(path)
    audit_provenance = {"inputs_unchanged": True, "source_sha256": {portable(k): v for k, v in hashes.items()},
                        "audit_code_sha256": _sha(Path(__file__)),
                        "output_sha256": {p.name: _sha(p) for p in output.iterdir() if p.is_file()}}
    (output / "provenance.json").write_text(json.dumps(audit_provenance, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(distributions[distributions['class'] == 'all'][['feature', 'kepler_median', 'tess_median', 'ks_distance']].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    audit(args.base_dir, args.output_dir)
