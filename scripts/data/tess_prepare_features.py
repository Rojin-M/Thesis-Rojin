#!/usr/bin/env python3
"""Prepare auditable TESS light-curve inputs without altering raw or Kepler data."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import platform
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.data.tess_dataset import feature_names, fit_normalization, validate_dataset
from scripts.data.tess_preprocessing import TessPrepConfig, prepare_star, PREPROCESS_VERSION
from scripts.data.tess_selection import choose_pilot, grouped_splits, select_candidates

LOG = logging.getLogger("tess_prepare_features")
KEYS = ("X_global", "X_local", "X_scalar", "X")
KEPLER_NAME = "dataset_kepler_v0_target10000_g200_l100_gw0.5_lwm4.0_bls1_seed42.npz"
FATAL_REASONS = {"invalid_raw_product", "preprocessing_error", "mixed_star_candidates", "product_tic_mismatch"}
CLI_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def atomic_bytes(path, content):
    path = Path(path)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def save_json(path, value):
    atomic_bytes(path, json_bytes(value))


def save_npz(path, arrays):
    temporary = path.with_name(path.name + ".part")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(path)


def save_csv(path, frame):
    atomic_bytes(path, frame.to_csv(index=False).encode())


def records(frame):
    # JSON converts pandas missing values to null and numpy scalars to Python values.
    return json.loads(frame.to_json(orient="records", double_precision=15))


def cached_star(task):
    raw_root, cache_dir, signature, products, candidates, companions, cfg = task
    cache_dir = Path(cache_dir)
    tic = int(candidates[0]["tic_id"])
    signature = hashlib.sha256(json_bytes({"science": signature, "products": products,
                                          "candidates": candidates, "companions": companions})).hexdigest()
    array_path = cache_dir / f"TIC{tic}_{signature[:16]}.npz"
    record_path = cache_dir / f"TIC{tic}_{signature[:16]}.json"
    if record_path.exists():
        saved = json.loads(record_path.read_text())
        if saved["signature"] != signature or digest(array_path) != saved["arrays_sha256"]:
            raise ValueError(f"Cached star TIC{tic} differs from its recorded inputs or checksum")
        # Cached results remain bound to the same immutable raw receipts. Check file
        # stats on resume; raw hashes were verified when these features were built.
        for product in products:
            stat = (Path(raw_root) / product["relative_path"]).stat()
            original = saved["raw_stats"][product["relative_path"]]
            if [stat.st_size, stat.st_mtime_ns] != original:
                if digest(Path(raw_root) / product["relative_path"]) != product["sha256"]:
                    raise ValueError(f"Raw product changed: {product['relative_path']}")
        with np.load(array_path, allow_pickle=False) as data:
            results = saved["results"]
            for i, result in enumerate(results):
                for key in saved["array_keys"][i]:
                    result[key] = data[f"r{i}_{key}"]
        return results, True
    raw_stats = {}
    for product in products:
        stat = (Path(raw_root) / product["relative_path"]).stat()
        raw_stats[product["relative_path"]] = [stat.st_size, stat.st_mtime_ns]
    results = prepare_star(Path(raw_root), products, candidates, companions, cfg)
    if any(result["reason"] in FATAL_REASONS for result in results):
        return results, False
    arrays, array_keys, metadata = {}, [], []
    for i, result in enumerate(results):
        keys = [key for key, value in result.items() if isinstance(value, np.ndarray)]
        array_keys.append(keys)
        arrays.update({f"r{i}_{key}": result[key] for key in keys})
        metadata.append({key: value for key, value in result.items() if key not in keys})
    save_npz(array_path, arrays)
    for product in products:
        stat = (Path(raw_root) / product["relative_path"]).stat()
        if raw_stats[product["relative_path"]] != [stat.st_size, stat.st_mtime_ns]:
            raise ValueError(f"Raw input changed during preparation: {product['relative_path']}")
    save_json(record_path, {"signature": signature, "arrays_sha256": digest(array_path),
                           "raw_stats": raw_stats, "results": metadata, "array_keys": array_keys})
    return results, False


def load_inputs(base, kepler_catalog, kepler_manifest):
    meta = base / "data/raw/tess/metadata"
    provenance = json.loads((meta / "provenance.json").read_text())
    acquisition = json.loads((meta / "download_summary.json").read_text())
    if acquisition["status"] != "complete" or acquisition["failed_files"]:
        raise ValueError("Finish the TESS download before preparing this frozen dataset")
    for name, key in [("toi.csv", "catalog_sha256"), ("manifest.csv", "manifest_sha256")]:
        if digest(meta / name) != provenance[key]:
            raise ValueError(f"Acquisition checksum mismatch: {name}")
    catalog = pd.read_csv(meta / "candidates.csv", dtype={"toi": str, "tid": np.int64})
    full_catalog = pd.read_csv(meta / "toi.csv", dtype={"toi": str, "tid": np.int64})
    original = full_catalog[full_catalog.tid.isin(catalog.tid)].set_index("toi").sort_index()
    retained = catalog.set_index("toi").sort_index()
    pd.testing.assert_frame_equal(original, retained[original.columns], check_dtype=False,
                                  check_exact=False, rtol=1e-12, atol=1e-12)
    products = pd.read_csv(meta / "manifest.csv")
    if len(products) != acquisition["completed_files"] or products.relative_path.duplicated().any():
        raise ValueError("Product manifest does not match the completed acquisition")
    def attach_receipt(row):
        receipt = json.loads((meta / "receipts" / (row["filename"] + ".json")).read_text())
        if receipt["data_uri"] != row["data_uri"] or receipt["relative_path"] != row["relative_path"]:
            raise ValueError(f"Receipt identity differs: {row['filename']}")
        return {**row, "sha256": receipt["sha256"], "size_bytes": receipt["size_bytes"]}
    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(attach_receipt, products.to_dict("records")))
    products = pd.DataFrame(receipts)
    source_hashes = {str(path): digest(path) for path in [meta / "toi.csv", meta / "candidates.csv",
                    meta / "manifest.csv", kepler_catalog, kepler_manifest]}
    source_hashes["product_receipts"] = hashlib.sha256(json_bytes(receipts)).hexdigest()
    return full_catalog, products, pd.read_csv(kepler_catalog), pd.read_csv(kepler_manifest), source_hashes


def plot_pilot(output, selected, results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    accepted = [row for row in results if row["status"] == "accepted"]
    lookup = selected.set_index("candidate_id")
    figure_dir = output / "figures"
    figure_dir.mkdir(exist_ok=True)
    for offset in range(0, len(accepted), 6):
        page = accepted[offset:offset + 6]
        fig, axes = plt.subplots(len(page), 3, figsize=(15, 2.6 * len(page)), squeeze=False)
        for result, axis in zip(page, axes):
            row = lookup.loc[result["candidate_id"]]
            diagnostics = result["diagnostics"]
            t = result["preview_time_btjd"]
            f = result["preview_time_flux"]
            axis[0].scatter(t, f, s=1, alpha=.45)
            epoch = float(row.epoch_bjd) - 2457000.0
            cycles = np.arange(np.floor((t.min() - epoch) / row.period), np.ceil((t.max() - epoch) / row.period) + 1)
            axis[0].vlines(epoch + cycles * row.period, 0, 1, transform=axis[0].get_xaxis_transform(),
                          color="tab:red", alpha=.1, linewidth=.5)
            axis[0].set(xlabel="Time (BJD − 2457000)", ylabel="Detrended flux")
            phase, flux = result["preview_phase"], result["preview_flux"]
            axis[1].scatter(phase, flux, s=2, alpha=.4)
            window = diagnostics["local_half_window"]
            inside = abs(phase) <= window
            axis[2].scatter(phase[inside], flux[inside], s=4, alpha=.5)
            for ax in axis[1:]:
                ax.axvline(0, color="tab:red", linewidth=.8)
                ax.set(xlabel="Orbital phase", ylabel="Detrended flux")
            axis[0].set_title(f"{row.name} · {row.tfopwg_disp} · P={row.period:.4g} d", fontsize=9)
            axis[1].set_title("Global fold (preview samples)", fontsize=9)
            axis[2].set_title(f"Local fold · {diagnostics['n_covered_transit_events']} sampled events", fontsize=9)
        fig.tight_layout()
        fig.savefig(figure_dir / f"pilot_{offset // 6 + 1:02d}.png", dpi=120)
        plt.close(fig)


def run(args, output):
    base = args.base_dir.resolve()
    kepler = base / "data/processed/kepler/v0"
    catalog_path = (args.kepler_catalog or base / "data/raw/kepler/metadata/koi_cumulative.csv").resolve()
    manifest_path = kepler / "manifest_kepler_v0.csv"
    source_dataset, source_splits = kepler / KEPLER_NAME, kepler / "splits_kepler_v0_seed42.npz"
    cfg = TessPrepConfig(preview_points=4000 if args.pilot_candidates else 0)
    LOG.info("Checking acquisition records and selecting candidates")
    catalog, products, koi, source_manifest, hashes = load_inputs(base, catalog_path, manifest_path)
    hashes.update({str(p): digest(p) for p in (source_dataset, source_splits)})
    selected, audit, overlap = select_candidates(catalog, products, koi, source_manifest)
    full_selected_count = len(selected)
    pilot_groups, pilot_provenance = [], None
    if args.pilot_dir:
        pilot_dir = args.pilot_dir.resolve()
        pilot_provenance = json.loads((pilot_dir / "provenance.json").read_text())
        if pilot_provenance["inputs"] != hashes:
            raise ValueError("Pilot and full preparation must use the same frozen raw/source inputs")
        pilot_summary = json.loads((pilot_dir / "preparation_summary.json").read_text())
        if pilot_summary["status"] != "complete":
            raise ValueError("Pilot preparation must finish before its groups can be reserved")
        if digest(pilot_dir / "selection.csv") != pilot_summary["outputs"]["selection.csv"]:
            raise ValueError("Pilot selection changed after its recorded inspection batch")
        pilot_selected = pd.read_csv(pilot_dir / "selection.csv")
        pilot_groups = sorted(set(pilot_selected.split_group))
    if args.pilot_candidates:
        selected = choose_pilot(selected, args.pilot_candidates, args.seed)
    science = {"version": PREPROCESS_VERSION, "config": asdict(cfg), "seed": args.seed,
               "pilot_candidates": args.pilot_candidates, "train_only_groups": pilot_groups,
               "selection": {"period_days": [.5, 30.], "duration_hours": [.1, 20.],
                             "overlap_arcsec": 5., "positive": ["CP", "KP"], "negative": ["FP", "FA"]}}
    code_hashes = {path.name: digest(path) for path in [Path(__file__),
        ROOT / "scripts/data/tess_selection.py", ROOT / "scripts/data/tess_preprocessing.py",
        ROOT / "scripts/data/tess_dataset.py", ROOT / "scripts/data/kepler_pipeline_lib.py"]}
    if code_hashes[Path(__file__).name] != CLI_SOURCE_SHA256:
        raise ValueError("Preparation script changed after launch; rerun the current script")
    if pilot_provenance is not None:
        pilot_cfg = {key: value for key, value in pilot_provenance["science"]["config"].items() if key != "preview_points"}
        full_cfg = {key: value for key, value in asdict(cfg).items() if key != "preview_points"}
        if (pilot_cfg != full_cfg or pilot_provenance["science"]["selection"] != science["selection"]
                or any(pilot_provenance["code"][name] != sha for name, sha in code_hashes.items()
                       if name != Path(__file__).name)):
            raise ValueError("Scientific preprocessing changed since the pilot; prepare and inspect a new pilot")
    environment = {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                   for name in ["numpy", "pandas", "astropy", "scipy", "scikit-learn", "lightkurve"]}}
    provenance = {"inputs": hashes, "science": science, "code": code_hashes, "environment": environment}
    signature = hashlib.sha256(json_bytes(provenance)).hexdigest()
    provenance["signature"] = signature
    provenance_path = output / "provenance.json"
    if provenance_path.exists():
        if json.loads(provenance_path.read_text()) != provenance:
            raise ValueError("Existing preparation has different inputs/code/configuration; use a new --output_dir")
    elif any(p.name not in {"prepare.lock", "prepare.log"} for p in output.iterdir()):
        raise ValueError("Output directory must be new or contain this pipeline's matching provenance")
    save_json(provenance_path, provenance)
    save_csv(output / "selection.csv", selected)
    save_csv(output / "catalog_audit.csv", audit)
    save_csv(output / "kepler_overlap.csv", overlap)
    companions = catalog.rename(columns={"tid": "tic_id", "pl_orbper": "period",
                    "pl_tranmid": "epoch_bjd", "pl_trandurh": "duration_hours"}).copy()
    companions["candidate_id"] = "TOI-" + companions.toi.astype(str)
    by_star = {int(tic): records(frame) for tic, frame in companions.groupby("tic_id")}
    by_product = {int(tic): frame.to_dict("records") for tic, frame in products.groupby("tic_id")}
    # Scientific star caches can be reused in a new output directory after a
    # reporting/CLI fix, but never across changed data or feature calculations.
    cache_signature = hashlib.sha256(json_bytes({"inputs": hashes, "config": asdict(cfg),
        "selection": science["selection"], "environment": environment,
        "code": {key: value for key, value in code_hashes.items()
                 if key in {"tess_preprocessing.py", "kepler_pipeline_lib.py"}}})).hexdigest()
    cache = base / "data/interim/tess/tess_v0" / cache_signature
    cache.mkdir(parents=True, exist_ok=True)
    tasks = [(base / "data/raw/tess", cache, cache_signature, by_product[int(tic)], records(frame),
              by_star[int(tic)], cfg) for tic, frame in selected.groupby("tic_id", sort=True)]
    LOG.info("Selected %d candidates on %d stars (%d candidates eligible before pilot selection)",
             len(selected), len(tasks), full_selected_count)
    summary_path = output / "preparation_summary.json"
    summary = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
               "selected_candidates": len(selected), "planned_stars": len(tasks),
               "completed_stars": 0, "prepare_workers": args.prepare_workers, "cached_stars": 0}
    save_json(summary_path, summary)
    results, began = [], time.monotonic()
    executor = ProcessPoolExecutor(max_workers=args.prepare_workers)
    try:
        futures = [executor.submit(cached_star, task) for task in tasks]
        for future in as_completed(futures):
            part, cached = future.result()
            results.extend(part)
            summary["completed_stars"] += 1
            summary["cached_stars"] += int(cached)
            fatal = [r for r in part if r["reason"] in FATAL_REASONS]
            if fatal:
                save_json(output / "processing_error.json", fatal)
                raise RuntimeError(f"Input/processing error for {fatal[0]['candidate_id']}; see processing_error.json")
            save_json(summary_path, summary)
            LOG.info("[%d/%d stars] %s; accepted=%d rejected=%d elapsed=%.1f min", summary["completed_stars"],
                     len(tasks), "cached" if cached else "prepared", sum(r["status"] == "accepted" for r in results),
                     sum(r["status"] != "accepted" for r in results), (time.monotonic() - began) / 60)
    except BaseException as exc:
        summary.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "incomplete", error=str(exc))
        save_json(summary_path, summary)
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    lookup = {r["candidate_id"]: r for r in results}
    if len(lookup) != len(selected) or set(lookup) != set(selected.candidate_id):
        raise ValueError("Processing results do not cover selected candidates exactly once")
    accepted = [lookup[cid] for cid in selected.candidate_id if lookup[cid]["status"] == "accepted"]
    processing_audit = [{"candidate_id": r["candidate_id"], "status": r["status"], "reason": r["reason"],
                         **{key: value for key, value in r["diagnostics"].items()
                            if isinstance(value, (str, int, float, bool))}} for r in results]
    save_csv(output / "processing_audit.csv", pd.DataFrame(processing_audit))
    if not accepted:
        raise ValueError("No candidates passed preprocessing; inspect processing_audit.csv")
    columns = ["candidate_id", "toi", "tic_id", "y", "tfopwg_disp", "period", "epoch_bjd",
               "duration_hours", "ra", "dec", "split_group"]
    manifest = selected.set_index("candidate_id", drop=False).loc[[r["candidate_id"] for r in accepted], columns].reset_index(drop=True)
    for key in ["local_half_window", "n_target_usable_points", "n_covered_transit_events"]:
        manifest[key] = [r["diagnostics"][key] for r in accepted]
    arrays = {key: np.stack([r[key] for r in accepted]).astype(np.float32) for key in KEYS}
    names, scalar_names = feature_names()
    arrays.update(y=manifest.y.to_numpy(dtype=np.int64), feature_names=np.asarray(names, dtype=str),
                  scalar_feature_names=np.asarray(scalar_names, dtype=str),
                  preprocessing_version=np.array(PREPROCESS_VERSION))
    retained_groups = sorted(set(pilot_groups) & set(manifest.split_group))
    splits = None if args.pilot_candidates else grouped_splits(manifest, seed=args.seed, train_only_groups=retained_groups)
    verified = validate_dataset(arrays, manifest, splits, forbidden_tic_ids=overlap.tic_id.unique(), train_only_groups=retained_groups)
    for name, expected in hashes.items():
        if name != "product_receipts" and digest(Path(name)) != expected:
            raise ValueError(f"Frozen source input changed during preparation: {name}")
    for name, expected in code_hashes.items():
        if digest(ROOT / "scripts/data" / name) != expected:
            raise ValueError(f"Preparation code changed during the run: {name}")
    with np.load(source_dataset, allow_pickle=True) as source, np.load(source_splits) as source_split:
        if not np.array_equal(source["feature_names"].astype(str), names) or not np.array_equal(source["scalar_feature_names"].astype(str), scalar_names):
            raise ValueError("Feature order differs from the frozen Kepler dataset")
        normalization = fit_normalization({key: source[key].astype(np.float32) for key in KEYS}, source_split["train_idx"])
    save_npz(output / "kepler_train_normalization.npz", normalization)
    save_npz(output / "dataset_tess_v0.npz", arrays)
    save_csv(output / "manifest_tess_v0.csv", manifest)
    if splits is not None:
        save_npz(output / f"splits_tess_v0_seed{args.seed}.npz", splits)
        save_npz(output / "tess_train_normalization.npz", fit_normalization(arrays, splits["train_idx"]))
    if args.pilot_candidates:
        plot_pilot(output, selected, accepted)
    summary.update(status="complete", finished_utc=datetime.now(timezone.utc).isoformat(),
                   elapsed_seconds=time.monotonic() - began, cache_dir=str(cache), accepted_candidates=len(accepted),
                   rejected_candidates=len(results) - len(accepted),
                   rejection_reasons=dict(Counter(r["reason"] for r in results if r["status"] != "accepted")),
                   validation=verified, pilot_groups_reserved_for_training=retained_groups,
                   outputs={p.name: digest(p) for p in output.iterdir() if p.suffix in {".csv", ".npz"}})
    save_json(summary_path, summary)
    LOG.info("Preparation complete: %d candidates; artifacts in %s", len(accepted), output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path)
    parser.add_argument("--kepler_catalog", type=Path, help="Frozen KOI catalog with kepid, ra, dec; defaults to existing Kepler raw metadata")
    parser.add_argument("--prepare_workers", type=int, default=1)
    parser.add_argument("--pilot_candidates", type=int, default=0, help="Balanced small batch; no test split, with diagnostic plots")
    parser.add_argument("--pilot_dir", type=Path, help="Completed pilot whose inspected star groups must stay in full training")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.prepare_workers < 1 or args.pilot_candidates < 0 or (args.pilot_candidates and args.pilot_dir):
        parser.error("Use positive workers, nonnegative pilot count, and only one pilot mode")
    if not args.pilot_candidates and not args.pilot_dir:
        parser.error("Complete a --pilot_candidates batch first, then supply --pilot_dir for the full dataset")
    default = "outputs/tess_preparation/pilot" if args.pilot_candidates else "data/processed/tess/v0"
    output = (args.output_dir or args.base_dir / default).resolve()
    protected = [args.base_dir.resolve() / "data/raw", args.base_dir.resolve() / "data/processed/kepler"]
    if any(output == p or p in output.parents or output in p.parents for p in protected):
        parser.error("Output must be separate from raw inputs and the preserved Kepler artifacts")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            handlers=[logging.StreamHandler(), logging.FileHandler(output / "prepare.log")])
        try:
            run(args, output)
        except Exception as exc:
            summary_path = output / "preparation_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())
                if summary.get("status") == "running":
                    summary.update(status="incomplete", error=str(exc))
                    save_json(summary_path, summary)
            LOG.exception("TESS preparation failed; completed star caches remain available")
            raise


if __name__ == "__main__":
    main()
