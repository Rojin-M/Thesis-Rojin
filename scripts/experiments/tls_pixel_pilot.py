#!/usr/bin/env python3
"""Run the frozen-cohort TLS, aperture-photometry and difference-image pilot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
import requests

from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.detection import SearchConfig, bounded_search
from scripts.research.lightcurves import read_lightcurves
from scripts.research.pixels import (MAX_TPF_BYTES, difference_image_diagnostics,
                                     read_target_pixels, target_pixel_product)
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from scripts.research.tls_search import ephemeris_agreement, search_tls

VERSION = "tls_pixel_prospective_pilot_v1"
FIELDS = {"schema_version", "cohort_manifest", "cohort_complete", "limit", "target_pixel_root",
          "receipt_root", "output", "max_product_bytes", "max_total_download_bytes",
          "period_min_days", "period_max_days", "bls_max_period_grid", "tls_oversampling_factor",
          "tls_duration_grid_step", "tls_use_threads"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("TLS/pixel pilot configuration fields differ from schema")
    if value["schema_version"] != 1 or type(value["limit"]) is not int or not 1 <= value["limit"] <= 100:
        raise ValueError("Invalid pilot size")
    if (type(value["max_product_bytes"]) is not int or not 1 <= value["max_product_bytes"] <= MAX_TPF_BYTES
            or type(value["max_total_download_bytes"]) is not int
            or not value["max_product_bytes"] <= value["max_total_download_bytes"] <= 32 * 1024 ** 3):
        raise ValueError("Invalid download bounds")
    if not .05 <= value["period_min_days"] < value["period_max_days"] <= 100:
        raise ValueError("Invalid period bounds")
    if type(value["bls_max_period_grid"]) is not int or not 100 <= value["bls_max_period_grid"] <= 20000:
        raise ValueError("Invalid BLS grid bound")
    if type(value["tls_oversampling_factor"]) is not int or not 1 <= value["tls_oversampling_factor"] <= 5:
        raise ValueError("Invalid TLS oversampling")
    if not 1.01 <= value["tls_duration_grid_step"] <= 1.5:
        raise ValueError("Invalid TLS duration grid")
    if type(value["tls_use_threads"]) is not int or not 1 <= value["tls_use_threads"] <= 8:
        raise ValueError("Invalid TLS thread count")
    for key in ("cohort_manifest", "cohort_complete", "target_pixel_root", "receipt_root", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Pilot paths must stay relative to the project root")
    return value


def _verify_cohort(config):
    manifest_path, complete_path = ROOT / config["cohort_manifest"], ROOT / config["cohort_complete"]
    complete = json.loads(complete_path.read_text())
    if complete.get("status") != "complete" or complete["files"].get(manifest_path.name) != file_sha256(manifest_path):
        raise ValueError("Frozen prospective cohort completion receipt is invalid")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "frozen_unscored" or len(manifest.get("targets", [])) < config["limit"]:
        raise ValueError("Prospective cohort is not a sufficiently large frozen-unscored cohort")
    return manifest


def _head(session, target, config):
    product = target_pixel_product(target["product_path"])
    if product["tic_id"] != str(target["target_id"]):
        raise ValueError("Frozen target differs from its light-curve filename")
    response = session.head(product["url"], timeout=(5, 20), allow_redirects=False,
                            headers={"Accept-Encoding": "identity"})
    if response.status_code != 200 or response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
        raise OSError(f"Public TPF HEAD failed with HTTP {response.status_code}")
    length = response.headers.get("Content-Length")
    if length is None or not length.isdigit() or not 0 < int(length) <= config["max_product_bytes"]:
        raise ValueError("Public TPF size is missing or outside the configured bound")
    return {**product, "size_bytes": int(length), "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified")}


def _download(session, plan, target, config):
    folder = ROOT / config["target_pixel_root"] / ("TIC" + str(target["target_id"]))
    receipts = ROOT / config["receipt_root"]
    folder.mkdir(parents=True, exist_ok=True); receipts.mkdir(parents=True, exist_ok=True)
    destination, receipt_path = folder / plan["filename"], receipts / (plan["filename"] + ".json")
    if destination.is_file() and receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if (destination.stat().st_size == plan["size_bytes"] == receipt.get("size_bytes")
                and file_sha256(destination) == receipt.get("sha256")
                and receipt.get("data_uri") == plan["data_uri"]):
            return destination, receipt, False
        raise ValueError("Existing target-pixel file or receipt does not match the archive plan")
    if destination.exists() or receipt_path.exists():
        raise ValueError("Incomplete target-pixel acquisition exists; preserve it and use a fresh path")
    temporary = destination.with_name(destination.name + ".part")
    if temporary.exists():
        raise ValueError("Prior partial target-pixel download exists")
    digest, count = hashlib.sha256(), 0
    began = time.monotonic()
    try:
        with session.get(plan["url"], timeout=(5, 60), allow_redirects=False, stream=True,
                         headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200 or response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise OSError(f"Public TPF download failed with HTTP {response.status_code}")
            if response.headers.get("Content-Length") != str(plan["size_bytes"]):
                raise ValueError("Target-pixel GET length differs from preflight HEAD")
            with temporary.open("xb") as stream:
                for block in response.iter_content(1024 * 1024):
                    if not block:
                        continue
                    count += len(block)
                    if count > plan["size_bytes"]:
                        raise ValueError("Target-pixel response exceeded its declared size")
                    stream.write(block); digest.update(block)
                stream.flush()
                __import__("os").fsync(stream.fileno())
        if count != plan["size_bytes"]:
            raise OSError("Target-pixel response was truncated")
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    receipt = {"schema_version": 1, "target_id": str(target["target_id"]), "sector": plan["sector"],
               "filename": plan["filename"], "data_uri": plan["data_uri"], "url": plan["url"],
               "size_bytes": count, "sha256": digest.hexdigest(), "etag": plan["etag"],
               "last_modified": plan["last_modified"], "downloaded_utc": utc_now(),
               "download_seconds": time.monotonic() - began}
    atomic_json(receipt_path, receipt)
    return destination, receipt, True


def _json_bls(result):
    return {key: result[key] for key in ("version", "config", "used_catalog_ephemeris", "proposals",
            "suppressed_harmonics", "search_grid", "score_semantics")}


def _split_maps(label, result, arrays):
    maps = result.pop("maps")
    arrays.update({f"{label}_{name}": value for name, value in maps.items()})
    return result


def _complete_target(folder, spec_sha):
    path = folder / "complete.json"
    if not path.is_file():
        return False
    receipt = json.loads(path.read_text())
    return (receipt.get("status") == "complete" and receipt.get("spec_sha256") == spec_sha
            and all((folder / name).is_file() and file_sha256(folder / name) == digest
                    for name, digest in receipt.get("files", {}).items()))


def _run_target(target, plan, config, session, output, spec_sha):
    target_id = str(target["target_id"])
    folder = output / ("TIC" + target_id)
    if folder.exists() and _complete_target(folder, spec_sha):
        return json.loads((folder / "target.json").read_text()), False
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"Incomplete output exists for TIC {target_id}; preserve it and use a new pilot output")
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    tpf_path, acquisition, downloaded = _download(session, plan, target, config)
    pixels = read_target_pixels(tpf_path, target_id)
    if pixels.sha256 != acquisition["sha256"] or pixels.sector != plan["sector"]:
        raise ValueError("Validated target pixels differ from the acquisition receipt")
    lightcurve_path = (ROOT / target["product_path"]).resolve()
    if file_sha256(lightcurve_path) != target["product_sha256"]:
        raise ValueError("Frozen light-curve bytes changed after cohort registration")
    curve = read_lightcurves([lightcurve_path], mission="TESS", target_id=target_id)
    # Use the same two-transit period support for both detectors so model
    # disagreement is not manufactured by unequal search domains.
    shared_period_max = min(config["period_max_days"], float(np.ptp(curve.time)) / 2)
    search_config = SearchConfig(period_min_days=config["period_min_days"],
        period_max_days=shared_period_max, max_period_grid=config["bls_max_period_grid"],
        max_signals=1, max_seconds=90)
    bls_full = bounded_search(curve, search_config)
    if not bls_full["proposals"]:
        raise ValueError("BLS returned no proposal for target-pixel diagnostics")
    tls = search_tls(bls_full["flat"], period_min_days=config["period_min_days"],
        period_max_days=shared_period_max, oversampling_factor=config["tls_oversampling_factor"],
        duration_grid_step=config["tls_duration_grid_step"], use_threads=config["tls_use_threads"])
    bls = _json_bls(bls_full)
    primary = bls["proposals"][0]
    arrays = {}
    pixel = {
        "bls": _split_maps("bls", difference_image_diagnostics(pixels, primary), arrays),
        "tls": _split_maps("tls", difference_image_diagnostics(pixels, tls), arrays),
    }
    maps_path = folder / "pixel_maps.npz"
    temporary = maps_path.with_name(maps_path.name + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(maps_path)
    record = {"status": "complete", "version": VERSION, "target_id": target_id,
              "completed_at": utc_now(), "runtime_seconds": time.monotonic() - started,
              "inputs": {"lightcurve_path": target["product_path"], "lightcurve_sha256": target["product_sha256"],
                         "target_pixel_path": str(tpf_path.relative_to(ROOT)), "target_pixel_sha256": pixels.sha256,
                         "new_download": downloaded, "download_receipt": acquisition},
              "bls": bls, "tls": tls, "behavior": {"bls_tls": ephemeris_agreement(primary, tls)},
              "pixel_diagnostics": pixel,
              "claims": {"candidate_confirmed": False, "calibrated_planet_probability": False,
                         "prospective_unseen_target": True}}
    atomic_json(folder / "target.json", record)
    files = {name: file_sha256(folder / name) for name in ("target.json", "pixel_maps.npz")}
    atomic_json(folder / "complete.json", {"status": "complete", "spec_sha256": spec_sha,
                                           "completed_at": utc_now(), "files": files})
    print(json.dumps({"target": target_id, "status": "complete", "seconds": record["runtime_seconds"],
                      "bls_period": primary["period_days"], "tls_period": tls["period_days"],
                      "agree": record["behavior"]["bls_tls"]["agrees_within_one_duration"]}), flush=True)
    return record, True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/tls_pixel_pilot_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    cohort = _verify_cohort(config)
    targets = cohort["targets"][:config["limit"]]
    output = ROOT / config["output"]
    output.mkdir(parents=True, exist_ok=True)
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "cohort_manifest_sha256": file_sha256(ROOT / config["cohort_manifest"]),
            "source_files": {name: file_sha256(ROOT / name) for name in
                ("scripts/experiments/tls_pixel_pilot.py", "scripts/research/tls_search.py",
                 "scripts/research/pixels.py", "scripts/research/detection.py")},
            "selected_targets": [str(row["target_id"]) for row in targets]}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Pilot output contains a different experiment specification")
    atomic_json(spec_path, spec)
    session = requests.Session()
    session.headers.update({"User-Agent": "Thesis-Rojin-TLS-pixel-pilot/1", "Accept-Encoding": "identity"})
    plans = [_head(session, target, config) for target in targets]
    total = sum(row["size_bytes"] for row in plans)
    if total > config["max_total_download_bytes"]:
        raise ValueError("Frozen pilot target pixels exceed the total download budget")
    atomic_json(output / "download_plan.json", {"created_at": utc_now(), "total_bytes": total, "products": plans})
    print(json.dumps({"status": "preflight_complete", "targets": len(targets), "total_bytes": total}), flush=True)
    completed, failures, new_downloads = [], [], 0
    for target, plan in zip(targets, plans):
        try:
            record, changed = _run_target(target, plan, config, session, output, spec_sha)
            completed.append(record); new_downloads += int(changed and record["inputs"]["new_download"])
        except Exception as exc:
            failure = {"target_id": str(target["target_id"]), "type": type(exc).__name__, "message": str(exc),
                       "failed_at": utc_now(), "traceback": traceback.format_exc(limit=8)}
            failures.append(failure); print(json.dumps({"status": "failed", **failure}), flush=True)
    summary = {"status": "complete" if not failures else "partial", "version": VERSION,
               "completed_at": utc_now(), "spec_sha256": spec_sha, "targets_requested": len(targets),
               "targets_completed": len(completed), "new_downloads": new_downloads,
               "planned_download_bytes": total, "failures": failures,
               "aggregate": {"bls_tls_agreements": sum(row["behavior"]["bls_tls"]["agrees_within_one_duration"] for row in completed),
                             "median_runtime_seconds": float(np.median([row["runtime_seconds"] for row in completed])) if completed else None},
               "claims": {"search_ready": False, "calibrated_pixel_expert": False,
                          "purpose": "feasibility_and_feature_generation_on_frozen_unscored_hosts"}}
    atomic_json(output / "summary.json", summary)
    if not failures:
        files = {name: file_sha256(output / name) for name in ("spec.json", "download_plan.json", "summary.json")}
        atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha,
                                               "completed_at": utc_now(), "files": files})
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
