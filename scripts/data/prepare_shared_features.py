#!/usr/bin/env python3
"""Prepare both missions with common algorithms, retaining native cadence and v0 splits."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.data.shared_preprocessing import SharedConfig, VERSION, KEYS, prepare_shared_star
from scripts.data.tess_dataset import feature_names, fit_normalization, apply_normalization, validate_dataset
from scripts.data.tess_prepare_features import (
    KEPLER_NAME, digest, json_bytes, save_json, save_npz, save_csv, records, load_inputs,
)

MISSIONS = ("kepler", "tess")
SOURCES = ("shared_preprocessing.py", "prepare_shared_features.py", "tess_preprocessing.py",
           "tess_dataset.py", "tess_prepare_features.py", "kepler_pipeline_lib.py")


def read_npz(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def parent_paths(base, mission):
    folder = base / "data/processed" / mission / "v0"
    return [folder / f"manifest_{mission}_v0.csv", folder / f"splits_{mission}_v0_seed42.npz",
            folder / (KEPLER_NAME if mission == "kepler" else "dataset_tess_v0.npz")]


def load_parent(base, mission):
    manifest_path, split_path, _ = parent_paths(base, mission)
    frame = pd.read_csv(manifest_path, dtype={"candidate_id": str, "toi": str})
    frame["parent_row_index"] = np.arange(len(frame))
    frame["split"] = ""
    splits = read_npz(split_path)
    assigned = np.concatenate([splits[name + "_idx"] for name in ("train", "val", "test")])
    if not np.array_equal(np.sort(assigned), np.arange(len(frame))):
        raise ValueError("Parent splits do not partition the manifest")
    for name in ("train", "val", "test"):
        frame.loc[splits[name + "_idx"], "split"] = name
    if mission == "kepler":
        frame["star_id"] = frame.kepid
        frame["split_group"] = "KIC-" + frame.kepid.astype(str)
        frame["period"] = frame.koi_period
        frame["epoch_bjd"] = frame.koi_time0bk + 2454833.
        frame["duration_hours"] = frame.koi_duration
    else:
        frame["star_id"] = frame.tic_id
    for field in ("star_id", "split_group"):
        if (frame.groupby(field).split.nunique() > 1).any():
            raise ValueError(f"Parent {mission} has overlapping {field}")
    if not frame.candidate_id.is_unique:
        raise ValueError("Duplicate parent candidate IDs")
    return frame


def pilot_selection(parent):
    """Four training examples per label, plus siblings on their stars; seed frozen at 42."""
    selected = pd.concat([parent[(parent.split == "train") & (parent.y == label)]
                          .sample(n=4, random_state=42) for label in (0, 1)])
    result = parent[parent.star_id.isin(selected.star_id)].copy()
    if not result.split.eq("train").all():
        raise ValueError("Pilot contains non-training rows")
    return result


def build_inputs(base, cfg):
    parents = {m: load_parent(base, m) for m in MISSIONS}
    catalog_path = base / "data/raw/kepler/metadata/koi_cumulative.csv"
    full_tess, tess_products, kepler, _, hashes = load_inputs(
        base, catalog_path, parent_paths(base, "kepler")[0])
    kepler = kepler.rename(columns={"kepid": "star_id", "kepoi_name": "candidate_id",
                                   "koi_period": "period", "koi_duration": "duration_hours"})
    kepler["epoch_bjd"] = kepler.koi_time0bk + 2454833.
    tess = full_tess.rename(columns={"tid": "star_id", "pl_orbper": "period",
                                    "pl_tranmid": "epoch_bjd", "pl_trandurh": "duration_hours"})
    tess["candidate_id"] = "TOI-" + tess.toi.astype(str)
    columns = ["star_id", "candidate_id", "period", "epoch_bjd", "duration_hours"]
    companions = {m: {int(s): records(f[columns]) for s, f in catalog.groupby("star_id")}
                  for m, catalog in (("kepler", kepler), ("tess", tess))}
    inventory = []
    wanted = set(parents["kepler"].star_id)
    for path in sorted((base / "data/raw/kepler/lightcurves/mastDownload/Kepler").rglob("*_llc.fits")):
        match = re.fullmatch(r"kplr(\d{9})-\d+_llc\.fits", path.name)
        if match and int(match[1]) in wanted:
            inventory.append({"star_id": int(match[1]), "path": str(path.relative_to(base))})
    products = {"kepler": {}, "tess": {}}
    for row in inventory:
        products["kepler"].setdefault(row["star_id"], []).append(row)
    for row in tess_products.to_dict("records"):
        row["path"] = "data/raw/tess/" + row["relative_path"]
        products["tess"].setdefault(int(row["tic_id"]), []).append(row)
    for mission in MISSIONS:
        if set(parents[mission].star_id) - products[mission].keys():
            raise ValueError(f"Missing native products for selected {mission} stars")
    raw_stats = {}
    for mission in MISSIONS:
        for star in sorted(set(parents[mission].star_id)):
            for row in products[mission][star]:
                stat = (base / row["path"]).stat()
                raw_stats[row["path"]] = [stat.st_size, stat.st_mtime_ns]
                row["frozen_raw_stats"] = raw_stats[row["path"]]
    for mission in MISSIONS:
        for path in parent_paths(base, mission):
            hashes[str(path)] = digest(path)
    protocol = {
        "version": VERSION, "config": asdict(cfg), "inputs": hashes,
        "code": {str(ROOT / "scripts/data" / name): digest(ROOT / "scripts/data" / name) for name in SOURCES},
        "environment": {"python": platform.python_version(), **{p: importlib.metadata.version(p)
                         for p in ("numpy", "pandas", "astropy", "scipy", "lightkurve")}},
        "raw_inventory_sha256": hashlib.sha256(json_bytes(raw_stats)).hexdigest(),
        "policy": {"cohort": "v0 survivors only; retain parent labels and split membership",
                   "pilot": "seed42 four training rows per label per mission plus their siblings",
                   "cadence": "native long-cadence Kepler and 120-second TESS; no resampling",
                   "detrending": "native segment/gap-local 1.5-day median excluding all known transits; no sigma clipping",
                   "folding": "catalog ephemerides, companion masking, median/IQR scaling, common bins/features",
                   "normalization": "new Kepler training rows only; same moments used for TESS transfer",
                   "test_status": "previously consulted benchmark; no newly untouched test set"},
    }
    protocol["signature"] = hashlib.sha256(json_bytes(protocol)).hexdigest()
    return parents, products, companions, raw_stats, protocol


def assert_unchanged(protocol):
    for section in ("inputs", "code"):
        for path, expected in protocol[section].items():
            if path == "product_receipts":
                continue
            if digest(path) != expected:
                raise ValueError(f"Frozen input/code changed: {path}")


def cached_star(task):
    base, mission, star, products, candidates, companions, cfg, signature = task
    base = Path(base)
    cache = base / "data/interim" / mission / VERSION
    marker = cache / "stars" / f"{star}.json"
    fingerprint = hashlib.sha256(json_bytes({"signature": signature, "products": products,
                                  "candidates": candidates, "companions": companions})).hexdigest()
    stats = {p["path"]: [(base / p["path"]).stat().st_size,
                          (base / p["path"]).stat().st_mtime_ns] for p in products}
    for product in products:
        if stats[product["path"]] != product["frozen_raw_stats"]:
            raise ValueError(f"Raw input changed since inventory: {product['path']}")
    if marker.exists():
        saved = json.loads(marker.read_text())
        if saved["fingerprint"] != fingerprint or saved["raw_stats"] != stats:
            raise ValueError(f"Cached inputs changed: {mission}/{star}")
        for path, expected in saved["outputs"].items():
            if digest(cache / path) != expected:
                raise ValueError(f"Cached output changed: {path}")
        return saved["results"], True
    results, bls, product_diagnostics = prepare_shared_star(
        base, mission, star, products, candidates, companions, cfg)
    output_hashes = {}
    bls_path = cache / "bls" / f"{star}.json"
    save_json(bls_path, {"star_id": star, "scope": "star_level", "features": bls})
    output_hashes[str(bls_path.relative_to(cache))] = digest(bls_path)
    for result in results:
        identifier = result["candidate_id"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
            raise ValueError("Unsafe candidate ID")
        if result["status"] == "accepted":
            for folder, key in (("views", "arrays"), ("folded", "folded")):
                path = cache / folder / (identifier + ".npz")
                save_npz(path, result.pop(key))
                output_hashes[str(path.relative_to(cache))] = digest(path)
    for path, expected in stats.items():
        stat = (base / path).stat()
        if [stat.st_size, stat.st_mtime_ns] != expected:
            raise ValueError(f"Raw input changed during preparation: {path}")
    save_json(marker, {"fingerprint": fingerprint, "raw_stats": stats,
                      "outputs": output_hashes, "products": product_diagnostics, "results": results})
    return results, False


def validate(arrays, manifest, splits, parent):
    # Reuse the mission-neutral array/group checks with a temporary identifier
    # alias. No KIC identifier is written as a TIC identifier in saved artifacts.
    alias = manifest.copy()
    alias["tic_id"] = alias.star_id
    summary = validate_dataset(arrays, alias, splits)
    expected = parent.set_index("candidate_id").loc[manifest.candidate_id]
    for key in ("y", "star_id", "split_group", "parent_row_index", "split", "period", "epoch_bjd", "duration_hours"):
        if not np.array_equal(manifest[key].to_numpy(), expected[key].to_numpy()):
            raise ValueError(f"Parent mapping changed: {key}")
    if splits is not None:
        for name in ("train", "val", "test"):
            if not np.array_equal(splits[name + "_idx"], np.flatnonzero(manifest.split.eq(name))):
                raise ValueError("Split membership changed")
    elif not manifest.split.eq("train").all():
        raise ValueError("Pilot contains non-training rows")
    return summary


def plot_pilot(output, mission, manifest, arrays, base):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # Legacy Kepler metadata include object arrays. Read only the numerical
    # views needed for this plot, without enabling pickle deserialization.
    with np.load(parent_paths(base, mission)[2], allow_pickle=False) as archive:
        old = {key: archive[key] for key in ("X_global", "X_local")}
    fig, axes = plt.subplots(len(manifest), 2, figsize=(10, 2.1 * len(manifest)), squeeze=False)
    for i, row in enumerate(manifest.itertuples(index=False)):
        for axis, key, title in zip(axes[i], ("X_global", "X_local"), ("Global", "Local")):
            axis.plot(old[key][row.parent_row_index, :, 0], label="v0", alpha=.65)
            axis.plot(arrays[key][i, :, 0], label="shared_v1", alpha=.85)
            axis.set_title(f"{row.candidate_id}, label {row.y}: {title}", fontsize=9)
            axis.set_ylabel("Scaled flux")
        axes[i, 0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output / "training_preview.png", dpi=120)
    plt.close(fig)


def prepare_mission(base, mission, stage, workers, parent, products, companions, cfg, protocol):
    output = (base / "outputs/shared_preparation" / VERSION / "pilot" / mission if stage == "pilot"
              else base / "data/processed" / mission / VERSION)
    output.mkdir(parents=True, exist_ok=True)
    cache = base / "data/interim" / mission / VERSION
    for folder in ("stars", "bls", "folded", "views"):
        (cache / folder).mkdir(parents=True, exist_ok=True)
    selected = pilot_selection(parent) if stage == "pilot" else parent.copy()
    save_json(output / "provenance.json", protocol)
    save_csv(output / "selection.csv", selected)
    summary = {"status": "running", "stage": stage, "mission": mission,
               "started_utc": datetime.now(timezone.utc).isoformat(), "prepare_workers": workers,
               "selected_candidates": len(selected), "planned_stars": int(selected.star_id.nunique()),
               "completed_stars": 0, "cached_stars": 0}
    summary_path = output / "preparation_summary.json"
    save_json(summary_path, summary)
    tasks = [(base, mission, int(star), products[int(star)], records(frame), companions.get(int(star), []), cfg,
              protocol["signature"]) for star, frame in selected.groupby("star_id", sort=True)]
    results = []
    started = time.monotonic()
    print(f"{mission}: {len(selected)} candidates, {len(tasks)} stars, {workers} workers", flush=True)
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(cached_star, task) for task in tasks]
            for future in as_completed(futures):
                try:
                    part, cached = future.result()
                except BaseException:
                    for pending in futures:
                        pending.cancel()
                    raise
                results.extend(part)
                summary["completed_stars"] += 1
                summary["cached_stars"] += int(cached)
                summary["elapsed_minutes"] = (time.monotonic() - started) / 60
                summary["candidate_status_counts"] = dict(Counter(r["status"] for r in results))
                save_json(summary_path, summary)
                print(f"{mission} [{summary['completed_stars']}/{len(tasks)}] "
                      f"{summary['elapsed_minutes']:.1f} min; {summary['candidate_status_counts']}", flush=True)
        lookup = {r["candidate_id"]: r for r in results}
        if len(lookup) != len(selected) or set(lookup) != set(selected.candidate_id):
            raise ValueError("Missing or duplicate candidate processing results")
        accepted = selected[selected.candidate_id.map(lambda c: lookup[c]["status"] == "accepted")].copy()
        if not len(accepted):
            raise ValueError(f"No accepted {mission} candidates")
        for key in ("local_half_window", "n_target_usable_points", "n_covered_transit_events", "cadence_seconds", "duration_in_cadences"):
            accepted[key] = [lookup[c]["diagnostics"][key] for c in accepted.candidate_id]
        views = [read_npz(cache / "views" / (c + ".npz")) for c in accepted.candidate_id]
        arrays = {key: np.stack([view[key] for view in views]) for key in KEYS}
        arrays["y"] = accepted.y.to_numpy(dtype=np.int64)
        arrays["feature_names"], arrays["scalar_feature_names"] = feature_names()
        splits = {name + "_idx": np.flatnonzero(accepted.split.eq(name)) for name in ("train", "val", "test")}
        summary["validation"] = validate(arrays, accepted, None if stage == "pilot" else splits, parent)
        save_npz(output / f"dataset_{mission}_{VERSION}.npz", arrays)
        save_csv(output / f"manifest_{mission}_{VERSION}.csv", accepted)
        if stage == "full":
            save_npz(output / f"splits_{mission}_{VERSION}_seed42.npz", splits)
        if mission == "kepler":
            stats = fit_normalization(arrays, splits["train_idx"])
        else:
            source = (base / "outputs/shared_preparation" / VERSION / "pilot/kepler" if stage == "pilot"
                      else base / "data/processed/kepler" / VERSION)
            stats = read_npz(source / "kepler_train_normalization.npz")
        apply_normalization(arrays, stats)
        save_npz(output / "kepler_train_normalization.npz", stats)
        audit = pd.DataFrame([{**r, "diagnostics": json.dumps(r["diagnostics"], sort_keys=True)} for r in results])
        audit = selected[["candidate_id", "y", "split", "parent_row_index"]].merge(audit, on="candidate_id", validate="one_to_one")
        save_csv(output / "processing_audit.csv", audit)
        if stage == "pilot":
            plot_pilot(output, mission, accepted, arrays, base)
        assert_unchanged(protocol)
        summary.update(status="complete", retained_candidates=len(accepted),
                       rejection_reasons=dict(Counter(r["reason"] for r in results if r["status"] != "accepted")),
                       outputs={p.name: digest(p) for p in output.iterdir()
                                if p.is_file() and p.name != "preparation_summary.json"},
                       completed_utc=datetime.now(timezone.utc).isoformat())
        save_json(summary_path, summary)
        return summary
    except BaseException as exc:
        summary.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save_json(summary_path, summary)
        raise


def verify_outputs(base, stage, protocol):
    summaries, source_stats = {}, None
    assert_unchanged(protocol)
    for mission in MISSIONS:
        output = (base / "outputs/shared_preparation" / VERSION / "pilot" / mission if stage == "pilot"
                  else base / "data/processed" / mission / VERSION)
        summary = json.loads((output / "preparation_summary.json").read_text())
        if summary["status"] != "complete":
            raise ValueError(f"Incomplete {mission} output")
        for path, expected in summary["outputs"].items():
            if digest(output / path) != expected:
                raise ValueError(f"Output checksum mismatch: {output / path}")
        if json.loads((output / "provenance.json").read_text()) != protocol:
            raise ValueError("Mission provenance mismatch")
        arrays = read_npz(output / f"dataset_{mission}_{VERSION}.npz")
        manifest = pd.read_csv(output / f"manifest_{mission}_{VERSION}.csv", float_precision="round_trip")
        splits = read_npz(output / f"splits_{mission}_{VERSION}_seed42.npz") if stage == "full" else None
        validate(arrays, manifest, splits, load_parent(base, mission))
        stats = read_npz(output / "kepler_train_normalization.npz")
        if mission == "kepler":
            source_stats = fit_normalization(arrays, splits["train_idx"] if splits else np.arange(len(manifest)))
        if set(stats) != set(source_stats) or any(not np.array_equal(stats[k], source_stats[k]) for k in stats):
            raise ValueError("Normalization differs from new Kepler training rows")
        apply_normalization(arrays, stats)
        audit = pd.read_csv(output / "processing_audit.csv")
        selection = pilot_selection(load_parent(base, mission)) if stage == "pilot" else load_parent(base, mission)
        if not np.array_equal(audit.candidate_id.to_numpy(), selection.candidate_id.to_numpy()):
            raise ValueError("Audit does not cover the selected cohort")
        if set(audit.loc[audit.status == "accepted", "candidate_id"]) != set(manifest.candidate_id):
            raise ValueError("Accepted audit differs from the dataset")
        summaries[mission] = {"retained_candidates": len(manifest), "rejection_reasons": summary["rejection_reasons"]}
    return {"status": "verified", "stage": stage, "missions": summaries,
            "verified_utc": datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=("pilot", "full"), required=True)
    parser.add_argument("--prepare_workers", type=int, default=1)
    parser.add_argument("--verify_only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.prepare_workers <= 32:
        parser.error("--prepare_workers must be 1..32")
    base = args.base_dir.resolve()
    work = base / "outputs/shared_preparation" / VERSION
    work.mkdir(parents=True, exist_ok=True)
    with (work / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.verify_only:
            protocol = json.loads((work / "protocol.json").read_text())
            print(json.dumps(verify_outputs(base, args.stage, protocol), indent=2))
            return
        print("Validating catalogs, source artifacts, receipts and native FITS inventory...", flush=True)
        cfg = SharedConfig()
        parents, products, companions, raw_stats, protocol = build_inputs(base, cfg)
        protocol_path = work / "protocol.json"
        if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("Existing shared_v1 inputs/code/environment differ; do not mix versions")
        save_json(protocol_path, protocol)
        save_json(work / "raw_inventory.json", raw_stats)
        if args.stage == "full":
            verify_outputs(base, "pilot", protocol)
        status_path = work / (args.stage + "_status.json")
        status = {"status": "running", "stage": args.stage, "prepare_workers": args.prepare_workers,
                  "started_utc": datetime.now(timezone.utc).isoformat(), "missions": {}}
        save_json(status_path, status)
        try:
            for mission in MISSIONS:
                status["active_mission"] = mission
                save_json(status_path, status)
                summary = prepare_mission(base, mission, args.stage, args.prepare_workers, parents[mission],
                                          products[mission], companions[mission], cfg, protocol)
                status["missions"][mission] = {k: summary[k] for k in ("status", "retained_candidates", "rejection_reasons")}
                save_json(status_path, status)
            check = verify_outputs(base, args.stage, protocol)
            save_json(work / (args.stage + "_verification.json"), check)
            status.update(status="complete", completed_utc=datetime.now(timezone.utc).isoformat())
            save_json(status_path, status)
            print(json.dumps(check, indent=2), flush=True)
        except BaseException as exc:
            status.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            save_json(status_path, status)
            raise


if __name__ == "__main__":
    main()
