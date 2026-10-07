#!/usr/bin/env python3
"""Build labelled TLS, aperture-photometry and difference-image experts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
import torch

from scripts.experiments.adaptation_data import make_roles
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.experiments.tls_pixel_pilot import _download, _head
from scripts.research.detection import phase_distance
from scripts.research.lightcurves import LightCurve, detrend, read_lightcurves
from scripts.research.pixels import difference_image_diagnostics, read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from scripts.research.tls_search import ephemeris_agreement, search_tls

VERSION = "labelled_physical_experts_v1"
KINDS = ("tls", "aperture_photometry", "difference_image")
TLS_FEATURES = ("tls_sde", "tls_snr", "tls_period_match", "tls_period_fractional_error",
                "tls_epoch_error_durations", "tls_sampling_gate", "tls_distinct_transits",
                "tls_odd_even_sigma", "tls_odd_even_available")
APERTURE_FEATURES = ("ap_pipeline_depth_snr", "ap_core_depth_snr", "ap_expanded_depth_snr",
                     "ap_background_depth_snr", "ap_background_available", "ap_depth_cv",
                     "ap_core_pipeline_ratio", "ap_expanded_pipeline_ratio")
DIFFERENCE_FEATURES = ("diff_offset_pixels", "diff_offset_sigma", "diff_offset_sigma_available",
                       "diff_peak_snr", "diff_concentration")
FEATURES = {"tls": TLS_FEATURES, "aperture_photometry": APERTURE_FEATURES,
            "difference_image": DIFFERENCE_FEATURES}
FIELDS = {"schema_version", "adaptation_config", "prepared_manifest", "raw_manifest",
          "target_pixel_root", "receipt_root", "output", "max_product_bytes",
          "max_total_download_bytes", "period_min_days", "period_max_days",
          "tls_oversampling_factor", "tls_duration_grid_step", "tls_use_threads",
          "archive_attempts", "c_grid", "max_iterations", "minimum_pixel_coverage"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("Physical-expert configuration differs from schema")
    adaptation = ROOT / value["adaptation_config"]
    validate_adaptation_config(json.loads(adaptation.read_text()))
    for key in ("adaptation_config", "prepared_manifest", "raw_manifest", "target_pixel_root", "receipt_root", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Physical-expert paths must stay inside the project")
    if (type(value["max_product_bytes"]) is not int or not 1 <= value["max_product_bytes"] <= 320 * 1024 ** 2
            or type(value["max_total_download_bytes"]) is not int
            or not value["max_product_bytes"] <= value["max_total_download_bytes"] <= 256 * 1024 ** 3):
        raise ValueError("Invalid acquisition bounds")
    for key, low, high in (("tls_oversampling_factor", 1, 5), ("tls_use_threads", 1, 8),
                           ("archive_attempts", 1, 5), ("max_iterations", 100, 10000)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    if not .05 <= value["period_min_days"] < value["period_max_days"] <= 100:
        raise ValueError("Invalid period bounds")
    if not 1.01 <= value["tls_duration_grid_step"] <= 1.5:
        raise ValueError("Invalid duration grid")
    if not .5 <= value["minimum_pixel_coverage"] <= 1:
        raise ValueError("Invalid minimum pixel coverage")
    if (not isinstance(value["c_grid"], list) or not value["c_grid"]
            or sorted(set(value["c_grid"])) != value["c_grid"]
            or any(type(x) not in (int, float) or not 1e-4 <= x <= 100 for x in value["c_grid"])):
        raise ValueError("Invalid regularization grid")
    return value


def _num(value, default=0.):
    try:
        result = float(value)
        return result if math.isfinite(result) else float(default)
    except (TypeError, ValueError):
        return float(default)


def freeze_cohort(config):
    prepared_path, raw_path = ROOT / config["prepared_manifest"], ROOT / config["raw_manifest"]
    prepared = pd.read_csv(prepared_path, dtype={"candidate_id": str, "tic_id": str, "star_id": str})
    adaptation = validate_adaptation_config(json.loads((ROOT / config["adaptation_config"]).read_text()))
    roles = make_roles(prepared, adaptation["partition_seed"], adaptation["max_train_groups"])
    role_by_index = {int(index): role for role, indices in roles.items() for index in indices}
    chosen = prepared.iloc[sorted(role_by_index)].copy()
    chosen["role"] = [role_by_index[int(index)] for index in chosen.index]
    raw = pd.read_csv(raw_path, dtype={"tic_id": str})
    raw = raw[raw.tic_id.isin(set(chosen.tic_id))].sort_values(["tic_id", "filename"])
    raw = raw.drop_duplicates("tic_id", keep="first").set_index("tic_id")
    if set(chosen.tic_id) - set(raw.index):
        raise ValueError("A labelled physical-expert host lacks a cached light curve")
    targets = []
    for tic, group in chosen.groupby("tic_id", sort=True):
        source = raw.loc[tic]
        path = ROOT / "data/raw/tess" / source.relative_path
        if not path.is_file():
            raise ValueError("Frozen light-curve source is absent: " + str(path))
        candidates = []
        for index, row in group.sort_values("candidate_id").iterrows():
            candidates.append({"row_index": int(index), "candidate_id": str(row.candidate_id),
                "role": str(row.role), "label": int(row.y), "period_days": float(row.period),
                "epoch_bjd_tdb": float(row.epoch_bjd), "duration_hours": float(row.duration_hours),
                "split_group": str(row.split_group)})
        targets.append({"target_id": str(tic), "lightcurve_path": str(path.relative_to(ROOT)),
                        "lightcurve_sha256": file_sha256(path), "sector": int(source.sector),
                        "cadence_seconds": int(source.cadence_seconds), "candidates": candidates})
    counts = {role: int(sum(c["role"] == role for t in targets for c in t["candidates"])) for role in roles}
    cohort = {"status": "frozen_before_pixel_feature_inspection", "version": VERSION,
              "frozen_at": utc_now(), "selection_policy": "first_lexical_cached_120s_SPOC_LC_per_role_host_label_blind",
              "prepared_manifest_sha256": file_sha256(prepared_path), "raw_manifest_sha256": file_sha256(raw_path),
              "roles": counts, "target_count": len(targets),
              "candidate_count": sum(len(t["candidates"]) for t in targets), "targets": targets,
              "original_test_policy": "excluded_without_inference"}
    return cohort


def _retry(function, attempts, label):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except Exception as exc:
            errors.append({"attempt": attempt, "type": type(exc).__name__, "message": str(exc)})
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise OSError(label + " failed after retries: " + json.dumps(errors))


def archive_plan(session, cohort, config, output):
    path = output / "download_plan.json"
    if path.is_file():
        plan = json.loads(path.read_text())
        if plan.get("target_ids") != [t["target_id"] for t in cohort["targets"]]:
            raise ValueError("Existing archive plan differs from frozen cohort")
        return plan
    products, failures = [], []
    for number, target in enumerate(cohort["targets"], 1):
        adapter = {"target_id": target["target_id"], "product_path": target["lightcurve_path"]}
        try:
            product = _retry(lambda: _head(session, adapter, config), config["archive_attempts"],
                             "TPF preflight for TIC " + target["target_id"])
            products.append({"target_id": target["target_id"], **product})
        except Exception as exc:
            failures.append({"target_id": target["target_id"], "type": type(exc).__name__, "message": str(exc)})
        if number % 25 == 0 or number == len(cohort["targets"]):
            print(json.dumps({"stage": "archive_preflight", "checked": number, "total": len(cohort["targets"]),
                              "available": len(products), "failures": len(failures)}), flush=True)
    total = sum(p["size_bytes"] for p in products)
    if total > config["max_total_download_bytes"]:
        raise ValueError(f"Archive plan requires {total} bytes, beyond configured total cap")
    plan = {"created_at": utc_now(), "target_ids": [t["target_id"] for t in cohort["targets"]],
            "total_bytes": total, "products": products, "failures": failures}
    atomic_json(path, plan)
    return plan


def _masked_for_siblings(flat, candidate, siblings):
    keep = np.ones(len(flat.time), dtype=bool)
    for other in siblings:
        if other["candidate_id"] == candidate["candidate_id"]:
            continue
        epoch = other["epoch_bjd_tdb"] - 2457000.
        duration = other["duration_hours"] / 24
        keep &= np.abs(phase_distance(flat.time, other["period_days"], epoch)) > 0.75 * duration
    if keep.sum() < 200:
        return flat
    return LightCurve(flat.time[keep], flat.flux[keep], flat.error[keep], flat.segment[keep],
                      flat.sources, {**flat.metadata, "sibling_catalog_masks": len(siblings) - 1})


def _tls_features(result, candidate):
    catalog = {"period_days": candidate["period_days"], "epoch_btjd": candidate["epoch_bjd_tdb"] - 2457000.,
               "duration_hours": candidate["duration_hours"]}
    agreement = ephemeris_agreement(catalog, result)
    duration_days = candidate["duration_hours"] / 24
    odd = result.get("odd_even_mismatch_sigma")
    return {"tls_available": True, "tls_sde": _num(result["sde"]), "tls_snr": _num(result["snr_white"]),
            "tls_period_match": float(agreement["agrees_within_one_duration"]),
            "tls_period_fractional_error": min(_num(agreement["fractional_period_difference"], 1), 2),
            "tls_epoch_error_durations": min(_num(agreement["epoch_phase_difference_days"]) / max(duration_days, 1e-6), 50),
            "tls_sampling_gate": float(result["diagnostics"]["sampling_gate_passed"]),
            "tls_distinct_transits": min(_num(result["distinct_transit_count"]), 30),
            "tls_odd_even_sigma": min(abs(_num(odd)), 50), "tls_odd_even_available": float(odd is not None)}


def _pixel_features(result):
    ap = result["aperture_photometry"]
    def snr(name): return _num(ap.get(name, {}).get("depth_snr"))
    def depth(name): return _num(ap.get(name, {}).get("depth_relative_flux"))
    pipe = depth("pipeline")
    source = result["source_localization"]
    sigma = source.get("offset_sigma_approximate")
    background = ap.get("background", {}).get("depth_snr")
    values = {"pixel_available": True, "ap_pipeline_depth_snr": snr("pipeline"),
        "ap_core_depth_snr": snr("core_3x3"), "ap_expanded_depth_snr": snr("expanded"),
        "ap_background_depth_snr": _num(background), "ap_background_available": float(background is not None),
        "ap_depth_cv": min(_num(result.get("aperture_depth_coefficient_of_variation")), 20),
        "ap_core_pipeline_ratio": np.clip(depth("core_3x3") / pipe, -20, 20) if abs(pipe) > 1e-12 else 0.,
        "ap_expanded_pipeline_ratio": np.clip(depth("expanded") / pipe, -20, 20) if abs(pipe) > 1e-12 else 0.,
        "diff_offset_pixels": min(_num(source.get("offset_pixels")), 20),
        "diff_offset_sigma": min(abs(_num(sigma)), 100), "diff_offset_sigma_available": float(sigma is not None),
        "diff_peak_snr": np.clip(_num(source.get("peak_difference_snr")), -100, 100),
        "diff_concentration": np.clip(_num(source.get("positive_flux_concentration")), 0, 1)}
    return {key: float(value) for key, value in values.items()}


def _empty_features(candidate, error=None):
    row = {"candidate_id": candidate["candidate_id"], "target_id": None, "role": candidate["role"],
           "label": candidate["label"], "tls_available": False, "pixel_available": False,
           "tls_error": error, "pixel_error": error}
    for names in FEATURES.values():
        for name in names: row[name] = 0.
    return row


def run_target(target, product, config, session, output, spec_sha):
    folder = output / "targets" / ("TIC" + target["target_id"])
    complete_path = folder / "complete.json"
    if complete_path.is_file():
        receipt = json.loads(complete_path.read_text())
        feature_path = folder / "features.json"
        if (receipt.get("spec_sha256") == spec_sha and feature_path.is_file()
                and receipt.get("features_sha256") == file_sha256(feature_path)):
            return json.loads(feature_path.read_text()), False
        raise ValueError("Existing target result differs from the active physical-expert specification")
    folder.mkdir(parents=True, exist_ok=True)
    lightcurve_path = ROOT / target["lightcurve_path"]
    if file_sha256(lightcurve_path) != target["lightcurve_sha256"]:
        raise ValueError("Frozen labelled light curve changed")
    curve = read_lightcurves([lightcurve_path], mission="TESS", target_id=target["target_id"])
    flat, _ = detrend(curve)
    pixels, pixel_acquisition_error, downloaded = None, None, False
    if product is not None:
        adapter = {"target_id": target["target_id"], "product_path": target["lightcurve_path"]}
        try:
            path, receipt, downloaded = _retry(lambda: _download(session, product, adapter, config),
                config["archive_attempts"], "TPF acquisition for TIC " + target["target_id"])
            pixels = read_target_pixels(path, target["target_id"])
            if pixels.sha256 != receipt["sha256"]:
                raise ValueError("Target-pixel receipt hash mismatch")
        except Exception as exc:
            pixel_acquisition_error = type(exc).__name__ + ": " + str(exc)
    rows = []
    for candidate in target["candidates"]:
        row = _empty_features(candidate)
        row["target_id"] = target["target_id"]
        candidate_flat = _masked_for_siblings(flat, candidate, target["candidates"])
        try:
            upper = min(config["period_max_days"], float(np.ptp(candidate_flat.time)) / 2)
            tls = search_tls(candidate_flat, period_min_days=config["period_min_days"], period_max_days=upper,
                oversampling_factor=config["tls_oversampling_factor"], duration_grid_step=config["tls_duration_grid_step"],
                use_threads=config["tls_use_threads"])
            row.update(_tls_features(tls, candidate)); row["tls_error"] = None
        except Exception as exc:
            row["tls_error"] = type(exc).__name__ + ": " + str(exc)
        if pixels is not None:
            ephemeris = {"period_days": candidate["period_days"],
                         "epoch_btjd": candidate["epoch_bjd_tdb"] - 2457000.,
                         "duration_hours": candidate["duration_hours"]}
            try:
                diagnostic = difference_image_diagnostics(pixels, ephemeris)
                row.update(_pixel_features(diagnostic)); row["pixel_error"] = None
            except Exception as exc:
                row["pixel_error"] = type(exc).__name__ + ": " + str(exc)
        else:
            row["pixel_error"] = pixel_acquisition_error or "archive_product_unavailable"
        rows.append(row)
    atomic_json(folder / "features.json", rows)
    atomic_json(complete_path, {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(),
        "features_sha256": file_sha256(folder / "features.json"), "new_download": downloaded,
        "pixel_acquisition_error": pixel_acquisition_error})
    return rows, downloaded


def fit_expert(kind, frame, config):
    columns = list(FEATURES[kind]); availability_column = "tls_available" if kind == "tls" else "pixel_available"
    raw = frame[columns].to_numpy(dtype=np.float64)
    available = frame[availability_column].astype(bool).to_numpy()
    train = frame.role.eq("train").to_numpy() & available
    selection = frame.role.eq("selection").to_numpy() & available
    calibration = frame.role.eq("calibration").to_numpy() & available
    audit = frame.role.eq("audit").to_numpy() & available
    if min(train.sum(), selection.sum(), calibration.sum(), audit.sum()) < 10:
        raise ValueError(kind + " lacks sufficient available examples in an experiment role")
    mean, scale = raw[train].mean(axis=0), raw[train].std(axis=0); scale[scale < 1e-6] = 1
    z = (raw - mean) / scale
    candidates = []
    for c in config["c_grid"]:
        model = LogisticRegression(C=c, max_iter=config["max_iterations"], solver="liblinear",
            random_state=1701, class_weight="balanced").fit(z[train], frame.label.to_numpy()[train])
        logits = model.decision_function(z)
        score = metrics(frame.label.to_numpy()[selection], logits[selection])["average_precision"]
        candidates.append((score, c, model))
    _, selected_c, model = max(candidates, key=lambda row: (row[0], -row[1]))
    logits = model.decision_function(z)
    temperature = fit_temperature(frame.label.to_numpy()[calibration], logits[calibration])
    return {"kind": kind, "features": columns, "availability_column": availability_column,
            "mean": mean.tolist(), "scale": scale.tolist(), "coefficient": model.coef_[0].tolist(),
            "intercept": float(model.intercept_[0]), "selected_c": selected_c,
            "selection_ap_by_c": {str(c): score for score, c, _ in candidates},
            "temperature": temperature, "logits": logits, "available": available,
            "audit_available": int(audit.sum()), "audit": metrics(frame.label.to_numpy()[audit], logits[audit]),
            "audit_calibrated": metrics(frame.label.to_numpy()[audit], logits[audit], temperature["temperature"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/physical_experts_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    cohort_path = output / "cohort.json"
    cohort = json.loads(cohort_path.read_text()) if cohort_path.is_file() else freeze_cohort(config)
    if not cohort_path.exists(): atomic_json(cohort_path, cohort)
    source_names = ("scripts/experiments/physical_experts.py", "scripts/experiments/tls_pixel_pilot.py",
                    "scripts/research/tls_search.py", "scripts/research/pixels.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "cohort_sha256": file_sha256(cohort_path),
            "source_files": {name: file_sha256(ROOT / name) for name in source_names}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.is_file() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing physical-expert run has a different specification")
    atomic_json(spec_path, spec)
    session = requests.Session(); session.headers.update({"User-Agent": "Thesis-Rojin-physical-experts/1",
                                                           "Accept-Encoding": "identity"})
    plan = archive_plan(session, cohort, config, output)
    products = {row["target_id"]: row for row in plan["products"]}
    all_rows, failures, downloads = [], [], 0
    for number, target in enumerate(cohort["targets"], 1):
        try:
            rows, downloaded = run_target(target, products.get(target["target_id"]), config, session, output, spec_sha)
            all_rows.extend(rows); downloads += int(downloaded)
        except Exception as exc:
            failures.append({"target_id": target["target_id"], "type": type(exc).__name__, "message": str(exc),
                             "traceback": traceback.format_exc(limit=8)})
        if number % 10 == 0 or number == len(cohort["targets"]):
            print(json.dumps({"stage": "feature_extraction", "targets": number, "total": len(cohort["targets"]),
                              "candidate_rows": len(all_rows), "failures": len(failures), "new_downloads": downloads}), flush=True)
    if failures:
        atomic_json(output / "failures.json", failures)
        raise RuntimeError(f"{len(failures)} target-level failures remain; rerun after correction")
    frame = pd.DataFrame(all_rows).sort_values(["role", "target_id", "candidate_id"]).reset_index(drop=True)
    if len(frame) != cohort["candidate_count"] or frame.candidate_id.nunique() != len(frame):
        raise ValueError("Feature rows differ from frozen candidate cohort")
    pixel_coverage = float(frame.pixel_available.mean())
    if pixel_coverage < config["minimum_pixel_coverage"]:
        raise ValueError(f"Pixel feature coverage {pixel_coverage:.3f} is below the frozen minimum")
    frame.to_csv(output / "features.csv", index=False)
    experts = {kind: fit_expert(kind, frame, config) for kind in KINDS}
    prediction = frame[["candidate_id", "target_id", "role", "label"]].copy()
    artifact = {"version": VERSION, "spec_sha256": spec_sha, "experts": {}}
    summary_experts = {}
    for kind, result in experts.items():
        prediction[kind + "_logit"] = result.pop("logits")
        prediction[kind + "_available"] = result.pop("available")
        artifact["experts"][kind] = {key: result[key] for key in
            ("features", "availability_column", "mean", "scale", "coefficient", "intercept", "temperature")}
        summary_experts[kind] = result
    prediction.to_csv(output / "predictions.csv", index=False)
    torch.save(artifact, output / "physical_experts.pt")
    summary = {"status": "complete", "version": VERSION, "completed_at": utc_now(), "spec_sha256": spec_sha,
        "targets": len(cohort["targets"]), "candidates": len(frame), "new_downloads": downloads,
        "planned_download_bytes": plan["total_bytes"], "archive_preflight_failures": plan["failures"],
        "coverage": {"tls": float(frame.tls_available.mean()), "pixel": pixel_coverage},
        "experts": summary_experts,
        "claims": {"original_test_evaluated": False, "search_ready": False,
                   "calibrated_planet_probability": False, "prospective_cohort_evaluated": False}}
    atomic_json(output / "summary.json", summary)
    files = {name: file_sha256(output / name) for name in
             ("cohort.json", "spec.json", "download_plan.json", "features.csv", "predictions.csv",
              "physical_experts.pt", "summary.json")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                           "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "coverage": summary["coverage"],
                      "audit": {k: v["audit"] for k, v in summary_experts.items()}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
