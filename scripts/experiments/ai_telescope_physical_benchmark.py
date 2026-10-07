"""Frozen physical-injection comparison on the 90 development-disjoint hosts.

No fitting, catalog queries, label access, or tuning on prospective hosts.
Calibration controls finish and thresholds freeze before prospective inference.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
import multiprocessing
from pathlib import Path
import signal
import time
import warnings

import batman
import numpy as np
import pandas as pd
import torch
from astropy.constants import G, M_sun, R_sun
from astropy.timeseries import BoxLeastSquares
from scipy.optimize import brentq, linear_sum_assignment
from scipy.stats import binomtest
from transitleastsquares import transitleastsquares

from scripts.experiments.ai_telescope_blind_scan import (
    _checked_complete, _context, group_events, infer_target,
)
from scripts.experiments.ai_telescope_continuous_validation import (
    aperture_mask, duration_compatible, exposure_days, inverted_residual_control, _wilson,
)
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.lightcurves import LightCurve, detrend
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_physical_benchmark_v1"
METHODS = ("v2", "v3", "bls", "tls")
_STATE = {}


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def valid_pixels(pixels):
    # Preserve the frozen neural photometry/quality policy; no truth masking.
    flux = np.nansum(pixels.flux[:, aperture_mask(pixels)], axis=1)
    return (pixels.quality == 0) & np.isfinite(pixels.time) & np.isfinite(flux)


def schedule(ids, config):
    """Balance depth and mode marginal counts before observing any scores."""
    ids = sorted(map(str, ids), key=int)
    rng = np.random.default_rng(config["seed"])
    depths = np.resize(config["depths"], len(ids)); rng.shuffle(depths)
    modes = np.resize(config["modes"], len(ids)); rng.shuffle(modes)
    return {tic: {"depth": float(depth), "mode": str(mode),
                  "period_days": float(config["single_period_days"] if mode == "single"
                                       else rng.choice(config["periods_days"])),
                  "stellar_density_solar": float(rng.choice(config["stellar_density_solar"])),
                  "impact_parameter": float(rng.choice(config["impact_parameters"]))}
            for tic, depth, mode in zip(ids, depths, modes)}


def transit_parameters(condition, config):
    p = batman.TransitParams()
    p.t0 = 0.; p.per = condition["period_days"]
    p.a = float((G.value * M_sun.value * condition["stellar_density_solar"]
                 * (p.per * 86400)**2 / (4 * np.pi**2))**(1/3) / R_sun.value)
    p.inc = float(np.degrees(np.arccos(condition["impact_parameter"] / p.a)))
    p.ecc = 0.; p.w = 90.; p.limb_dark = "quadratic"
    p.u = config["limb_darkening"]
    def central_depth(rp):
        p.rp = rp
        return 1 - batman.TransitModel(p, np.array([0.])).light_curve(p)[0]
    p.rp = float(brentq(lambda rp: central_depth(rp) - condition["depth"], .001, .3))
    b = condition["impact_parameter"]
    duration = p.per / np.pi * np.arcsin(np.sqrt((1+p.rp)**2-b*b)
                                         / np.sqrt(p.a*p.a-b*b))
    return p, float(duration)


def physical_injection(pixels, condition, config):
    """Exposure-integrated circular limb-darkened shape in the real pixel cube.

    Density and limb darkening are synthetic assumptions, not measured stellar
    parameters. The PSF is an empirical median image, not a deblended TESS PRF.
    """
    p, duration = transit_parameters(condition, config)
    valid = valid_pixels(pixels); usable = pixels.time[valid]
    cadence = float(np.median(np.diff(usable)))
    rng = np.random.default_rng(np.random.SeedSequence([config["seed"], int(pixels.target_id)]))
    margin = max(.5, duration)
    lo, hi = float(usable.min()+margin), float(usable.max()-margin)
    anchor = float(rng.uniform(lo, hi))
    if condition["mode"] == "single":
        planned = np.array([anchor])
    else:
        first = anchor - math.floor((anchor-lo)/p.per)*p.per
        planned = np.arange(first, hi, p.per)
        if condition["mode"] == "ttv":
            planned += rng.uniform(-1, 1, len(planned))*duration*config["ttv_fraction_of_duration"]
    loss = np.zeros(len(pixels.time))
    observed, coverage = [], []
    for center in planned:
        # Evaluate only this transit, including integrations at contact edges.
        near = np.isfinite(pixels.time) & (np.abs(pixels.time-center) <= duration+cadence)
        local_time = np.ascontiguousarray(pixels.time[near]-center)
        loss[near] += 1 - batman.TransitModel(
            p, local_time, supersample_factor=config["supersample_factor"],
            exp_time=cadence).light_curve(p)
        count = int(np.count_nonzero(valid & (np.abs(pixels.time-center) <= duration/2)))
        fraction = min(1., count*cadence/duration)
        coverage.append({"center_btjd": float(center), "samples": count, "fraction": fraction})
        if count >= 2 and fraction >= config["minimum_event_coverage"]:
            observed.append(float(center))
    aperture = aperture_mask(pixels)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        reference = np.nanmedian(pixels.flux[valid], axis=0)
    floor = float(np.nanpercentile(reference, 20))
    template = np.nan_to_num(np.maximum(reference-floor, 0), nan=0.)
    baseline = float(np.median(np.nansum(pixels.flux[valid][:, aperture], axis=1)))
    if baseline <= 0 or template[aperture].sum() <= 0:
        raise ValueError("Cannot estimate an aperture PSF")
    template *= baseline/template[aperture].sum()
    cube = pixels.flux - loss[:, None, None]*template[None, :, :]
    truth = {**condition, "duration_hours": duration*24, "radius_ratio": p.rp,
             "a_over_rstar": p.a, "inclination_degrees": p.inc,
             "limb_darkening": p.u, "cadence_days": cadence,
             "planned_centers_btjd": planned.tolist(), "observed_centers_btjd": observed,
             "event_coverage": coverage, "realized_max_aperture_depth": float(loss[valid].max()),
             "profile_sha256": hashlib.sha256(loss.astype('<f8').tobytes()).hexdigest()}
    return replace(pixels, flux=cube), truth


def aperture_curve(pixels, config):
    valid = valid_pixels(pixels)
    time = pixels.time[valid]
    flux = np.nansum(pixels.flux[:, aperture_mask(pixels)], axis=1)[valid]
    # The same raw aperture sum goes to the neural light input. Classical
    # searches apply their declared blind detrending; no catalog masks/clipping.
    curve = LightCurve(time, flux, np.full(len(time), 1e-10),
                       np.zeros(len(time), dtype=int), [], {})
    return detrend(curve, config["detrend_window_days"])[0]


def sampled_centers(time, period, epoch, duration):
    centers = epoch + np.arange(math.floor((time.min()-epoch)/period),
                                math.ceil((time.max()-epoch)/period)+1)*period
    cadence = float(np.median(np.diff(time)))
    return [float(c) for c in centers if
            np.count_nonzero(np.abs(time-c) <= duration/2) >= max(2, .5*duration/cadence)]


def _deadline(signum, frame):
    raise TimeoutError("Frozen per-case search deadline exceeded")


def classical_searches(pixels, config):
    flat = aperture_curve(pixels, config)
    upper = min(config["period_max_days"], float(np.ptp(flat.time))/2)
    # TLS returns the exact period grid; BLS searches those same trial periods.
    began = time.monotonic()
    previous = signal.signal(signal.SIGALRM, _deadline)
    signal.alarm(config["search_timeout_seconds"])
    try:
        tls = transitleastsquares(flat.time, flat.flux, flat.error, verbose=False).power(
            period_min=config["period_min_days"], period_max=upper, n_transits_min=2,
            oversampling_factor=config["oversampling_factor"],
            duration_grid_step=config["duration_grid_step"],
            use_threads=1, show_progress_bar=False)
        tls_seconds = time.monotonic()-began
        durations = np.array(config["bls_durations_hours"])/24
        bls = BoxLeastSquares(flat.time, flat.flux, flat.error).power(
            np.sort(tls.periods), durations, objective="likelihood", method="fast", oversample=10)
        idx = int(np.nanargmax(bls.power))
        output = {}
        for name, period, epoch, duration, score in (
                ("tls", tls.period, tls.T0, tls.duration, tls.SDE),
                ("bls", bls.period[idx], bls.transit_time[idx], bls.duration[idx], bls.depth_snr[idx])):
            if not np.isfinite([period, epoch, duration, score]).all() or duration <= 0:
                raise ValueError("Nonfinite " + name + " solution")
            centers = sampled_centers(flat.time, period, epoch, duration)
            output[name] = {"score": float(score), "period_days": float(period),
                            "epoch_btjd": float(epoch), "duration_hours": float(duration*24),
                            "centers_btjd": centers if len(centers) >= 2 else [],
                            "actual_period_min_days": float(np.min(tls.periods)),
                            "actual_period_max_days": float(np.max(tls.periods)),
                            "periods_evaluated": len(tls.periods), "samples": len(flat.time)}
        output["runtime"] = {"tls_seconds": tls_seconds,
                             "bls_seconds": time.monotonic()-began-tls_seconds}
        return output
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)


def matched_indices(detected, truth, tolerance):
    """One-to-one matching; duplicate detections cannot inflate event recovery."""
    if not detected or not truth:
        return []
    costs = np.abs(np.asarray(detected)[:, None]-np.asarray(truth)[None, :])
    # Large penalties first maximize the number of in-tolerance matches.
    rows, cols = linear_sum_assignment(np.where(costs <= tolerance, costs, 1e6))
    return sorted(int(j) for i, j in zip(rows, cols) if costs[i, j] <= tolerance)


def accepted_centers(case, method, thresholds):
    item = case[method]
    if method in ("bls", "tls") and item["score"] < thresholds[method]:
        return []
    return item["centers_btjd"]


def choose_thresholds(rows, config):
    exposure = sum(r["exposure_days"] for r in rows)
    result = {}
    for method in ("bls", "tls"):
        table = []
        for threshold in config[method+"_thresholds"]:
            count = sum(len(r["cases"]["inverted"][method]["centers_btjd"])
                        for r in rows if r["cases"]["inverted"][method]["score"] >= threshold)
            table.append({"threshold": float(threshold), "events": count,
                          "events_per_27_days": count/exposure*27})
        eligible = [r for r in table if r["events_per_27_days"] <= config["target_control_events_per_27_days"]]
        if not eligible:
            raise ValueError("No predeclared threshold satisfies the " + method + " control budget")
        result[method] = {"selected_threshold": eligible[0]["threshold"], "table": table}
    return result


def validate_config(config):
    expected = {"schema_version", "model_runs", "validation_runs", "prospective_run", "physical_run",
                "output", "seed", "depths", "modes", "periods_days", "single_period_days",
                "stellar_density_solar", "impact_parameters", "limb_darkening", "supersample_factor",
                "ttv_fraction_of_duration", "minimum_event_coverage", "detrend_window_days",
                "period_min_days", "period_max_days", "oversampling_factor", "duration_grid_step",
                "bls_durations_hours", "bls_thresholds", "tls_thresholds",
                "target_control_events_per_27_days", "workers", "search_timeout_seconds"}
    if set(config) != expected or config["schema_version"] != 1:
        raise ValueError("Benchmark config differs from schema")
    paths = [config[k] for k in ("prospective_run", "physical_run", "output")]
    for key in ("model_runs", "validation_runs"):
        if set(config[key]) != {"v2", "v3"}:
            raise ValueError("Both frozen model versions are required")
        paths.extend(config[key].values())
    if any(not isinstance(p, str) or not p or Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
        raise ValueError("Paths must stay inside project")
    for key, low, high in (("depths", 1e-5, .03), ("periods_days", .6, 10),
                           ("stellar_density_solar", .1, 20), ("impact_parameters", 0, .9),
                           ("bls_durations_hours", .25, 10), ("bls_thresholds", 0, 1e4),
                           ("tls_thresholds", 0, 1e4)):
        vals = config[key]
        if not isinstance(vals, list) or not vals or any(type(v) not in (int, float)
                or not math.isfinite(v) or not low <= v <= high for v in vals):
            raise ValueError("Invalid " + key)
        if len(set(vals)) != len(vals):
            raise ValueError("Duplicate " + key)
    for key in ("bls_thresholds", "tls_thresholds"):
        if config[key] != sorted(config[key]):
            raise ValueError("Thresholds must be increasing")
    if config["modes"] != ["single", "periodic", "ttv"]:
        raise ValueError("All three declared event modes are required")
    for key, lo, hi in (("workers", 1, 4), ("supersample_factor", 1, 15),
                        ("oversampling_factor", 1, 5), ("seed", 0, 2**31-1),
                        ("search_timeout_seconds", 10, 600)):
        if type(config[key]) is not int or not lo <= config[key] <= hi:
            raise ValueError("Invalid " + key)
    for key, lo, hi in (("single_period_days", 50, 200), ("ttv_fraction_of_duration", 0, 2),
                        ("minimum_event_coverage", .5, 1), ("detrend_window_days", .9, 5),
                        ("period_min_days", .5, 2), ("period_max_days", 3, 20),
                        ("duration_grid_step", 1.01, 1.5), ("target_control_events_per_27_days", .01, 2)):
        if type(config[key]) not in (int, float) or not math.isfinite(config[key]) or not lo <= config[key] <= hi:
            raise ValueError("Invalid " + key)
    if (max(config["bls_durations_hours"])/24 >= config["period_min_days"]
            or not config["period_min_days"] <= min(config["periods_days"])
            or max(config["periods_days"]) > config["period_max_days"]):
        raise ValueError("Incompatible search/injection bounds")
    u = config["limb_darkening"]
    if not isinstance(u, list) or len(u) != 2 or any(not math.isfinite(x) or x < 0 for x in u) or sum(u) >= 1:
        raise ValueError("Invalid quadratic limb darkening")
    return config


def checked_record(path, spec_sha):
    record = json.loads(path.read_text())
    checksum = record.pop("record_sha256")
    if checksum != digest(record) or record["spec_sha256"] != spec_sha:
        raise ValueError("Cached record mismatch: " + str(path))
    return record


def write_record(path, record):
    atomic_json(path, {**record, "record_sha256": digest(record)})


def prepare(config, config_path):
    receipts = {}
    for name, path in {**config["model_runs"], **{k+"_validation": v for k, v in config["validation_runs"].items()},
                       "prospective": config["prospective_run"], "physical": config["physical_run"]}.items():
        _checked_complete(ROOT/path)
        receipts[name] = file_sha256(ROOT/path/"complete.json")
    prospective = ROOT/config["prospective_run"]
    prior_spec = json.loads((prospective/"spec.json").read_text())
    ids = [str(t["target_id"]) for t in prior_spec["selected_targets"]]
    if len(ids) != 90 or len(set(ids)) != 90:
        raise ValueError("Expected the exact registered 90-host cohort")
    development = {str(t["target_id"]) for t in json.loads((ROOT/config["physical_run"]/"cohort.json").read_text())["targets"]}
    for path in config["model_runs"].values():
        with np.load(ROOT/path/"dataset.npz", allow_pickle=False) as data:
            development.update(data["target_id"].astype(str))
    if set(ids) & development:
        raise ValueError("Prospective hosts overlap development")
    validations = {k: json.loads((ROOT/v/"spec.json").read_text()) for k, v in config["validation_runs"].items()}
    calibration = validations["v3"]["selected_target_ids"]["calibration"]
    if calibration != validations["v2"]["selected_target_ids"]["calibration"] or set(calibration) & set(ids):
        raise ValueError("Calibration identity mismatch or evaluation leakage")
    physical_products = {str(t["target_id"]): t for t in json.loads((ROOT/config["physical_run"]/"download_plan.json").read_text())["products"]}
    prospect_products = {str(t["target_id"]): t for t in json.loads((prospective/"download_plan.json").read_text())["products"]}
    targets = {}
    for role, members, products in (("calibration", calibration, physical_products), ("evaluation", ids, prospect_products)):
        targets[role] = []
        for tic in members:
            upstream = (ROOT/config["validation_runs"]["v3"] if role == "calibration" else prospective)/"targets"/("TIC"+tic+".json")
            receipt = json.loads(upstream.read_text())
            if receipt["status"] != "complete":
                raise ValueError("Incomplete source target")
            if role == "calibration":
                complete = json.loads((ROOT/config["validation_runs"]["v3"]/"complete.json").read_text())
                if complete["target_receipts"][str(upstream.relative_to(ROOT))] != file_sha256(upstream):
                    raise ValueError("Calibration target receipt checksum mismatch")
            targets[role].append({"target_id": tic,
                "path": str(Path("data/raw/tess/target_pixels")/("TIC"+tic)/products[tic]["filename"]),
                "sha256": receipt["source_sha256"], "upstream_receipt_sha256": file_sha256(upstream)})
    thresholds = {k: float(json.loads((ROOT/v/"operating_point.json").read_text())["selected_threshold"])
                  for k, v in config["validation_runs"].items()}
    sources = ["scripts/experiments/ai_telescope_physical_benchmark.py", "scripts/experiments/ai_telescope.py",
               "scripts/experiments/ai_telescope_v2.py", "scripts/experiments/ai_telescope_blind_scan.py",
               "scripts/experiments/ai_telescope_continuous_validation.py", "scripts/research/pixels.py",
               "scripts/research/lightcurves.py", "training/ai_telescope.py"]
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "input_receipts": receipts, "source_files": {p: file_sha256(ROOT/p) for p in sources},
            "packages": {p: importlib.metadata.version(p) for p in
                         ("numpy", "scipy", "pandas", "torch", "batman-package", "transitleastsquares", "astropy")},
            "targets": targets, "schedule": schedule(ids, config), "neural_thresholds": thresholds,
            "scan_config": validations["v3"]["scan_config"],
            "duration_bounds_hours": validations["v3"]["duration_bounds_hours"],
            "protocol": {"training": False, "development_overlap": 0,
                "calibration_before_evaluation": True, "catalog_access": False,
                "case_order": ["original", "injected", "inverted"],
                "event_matching": "one_to_one_within_half_true_duration",
                "primary_recovery": "injected_events_matched_but_not_matched_on_original_curve",
                "classical_search": "one_best_periodic_hypothesis_on_identical_TLS_period_grid",
                "classical_scores": {"bls": "depth_snr", "tls": "SDE"},
                "comparison_scope": "event_localization_at_same_calibration_alert_budget_not_planet_classification",
                "prior_exposure": "90 hosts previously scanned by frozen v2; excluded from training and calibration",
                "synthetic_assumptions": "circular orbits; synthetic density/limb darkening; static empirical PSF; no added photon noise",
                "not_covered": ["background_source_injections", "eclipsing_binaries", "multi_sector", "catalog_dispositions"]}}
    output = ROOT/config["output"]; output.mkdir(parents=True, exist_ok=True)
    spec_path = output/"spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Frozen benchmark specification changed; use a new output for a new protocol")
    atomic_json(spec_path, spec)
    return spec, digest(spec), output


def initialize_worker(spec, spec_sha):
    torch.set_num_threads(1)
    _STATE.update(spec=spec, spec_sha=spec_sha, models={})


def neural_searches(pixels):
    spec = _STATE["spec"]; config = spec["config"]; scan = spec["scan_config"]
    result = {}
    for name, path in config["model_runs"].items():
        if name not in _STATE["models"]:
            run = ROOT/path
            stats = json.loads((run/"context_stats.json").read_text())
            model_config = json.loads((run/"spec.json").read_text())["config"]
            model = ExtendedEventLocalizer(len(stats["features"])*2, model_config["embedding_dim"], model_config["instrument_channels"])
            checkpoint = torch.load(run/"ai_telescope_context.pt", map_location="cpu", weights_only=True)
            model.load_state_dict(checkpoint["localizer"]); model.eval()
            _STATE["models"][name] = model, stats
        model, stats = _STATE["models"][name]
        began = time.monotonic()
        scores, valid, _ = infer_target(model, pixels, _context(pixels.context, stats), scan)
        events = group_events(scores, valid, spec["neural_thresholds"][name],
                              scan["merge_gap_cadences"], scan["minimum_event_cadences"])
        events = duration_compatible(events, pixels.time, spec["duration_bounds_hours"])
        result[name] = {"centers_btjd": [float(pixels.time[e["peak_index"]]) for e in events],
                        "events": events, "seconds": time.monotonic()-began}
    return result


def run_target(target, role):
    spec = _STATE["spec"]; spec_sha = _STATE["spec_sha"]; config = spec["config"]
    output = ROOT/config["output"]; tic = target["target_id"]
    cache = output/role; cache.mkdir(exist_ok=True)
    path = cache/("TIC"+tic+".json")
    if path.exists():
        return checked_record(path, spec_sha)
    pixels = read_target_pixels(ROOT/target["path"], tic)
    if pixels.sha256 != target["sha256"]:
        raise ValueError("Changed TPF for TIC"+tic)
    truth = None
    if role == "evaluation":
        injected, truth = physical_injection(pixels, spec["schedule"][tic], config)
    cases = {}
    for name in (["inverted"] if role == "calibration" else spec["protocol"]["case_order"]):
        case_path = cache/("TIC"+tic+"-"+name+".json")
        if case_path.exists():
            cases[name] = checked_record(case_path, spec_sha)["result"]
            continue
        current = injected if name == "injected" else inverted_residual_control(pixels) if name == "inverted" else pixels
        result = classical_searches(current, config)
        if role == "evaluation":
            result.update(neural_searches(current))
        write_record(case_path, {"spec_sha256": spec_sha, "target_id": tic, "case": name, "result": result})
        cases[name] = result
    row = {"spec_sha256": spec_sha, "target_id": tic, "role": role, "source_sha256": pixels.sha256,
           "exposure_days": exposure_days(pixels), "truth": truth, "cases": cases, "completed_at": utc_now()}
    write_record(path, row)
    return row


def run_role(spec, spec_sha, role):
    rows = []
    with ProcessPoolExecutor(max_workers=spec["config"]["workers"],
                             mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_worker, initargs=(spec, spec_sha)) as pool:
        futures = {pool.submit(run_target, target, role): target for target in spec["targets"][role]}
        for future in as_completed(futures):
            row = future.result()  # A failed host blocks completion, never drops from denominator.
            rows.append(row)
            print(json.dumps({"stage": role, "completed": len(rows), "registered": len(futures),
                              "target_id": row["target_id"]}), flush=True)
    return sorted(rows, key=lambda r: int(r["target_id"]))


def recovery_rows(results, thresholds):
    rows = []
    for result in results:
        truth = result["truth"]; centers = truth["observed_centers_btjd"]
        tolerance = truth["duration_hours"]/48
        for method in METHODS:
            detected = accepted_centers(result["cases"]["injected"], method, thresholds)
            original = accepted_centers(result["cases"]["original"], method, thresholds)
            matches = set(matched_indices(detected, centers, tolerance))
            prior = set(matched_indices(original, centers, tolerance))
            added = matches-prior
            rows.append({"target_id": result["target_id"], "method": method,
                         "mode": truth["mode"], "depth": truth["depth"],
                         "duration_hours": truth["duration_hours"], "injected_events": len(centers),
                         "matched_events": len(matches), "original_matches": len(prior),
                         "incremental_events": len(added), "any_match": bool(matches),
                         "incremental_recovery": bool(added),
                         "pattern_recovery": bool(len(centers) >= 2 and len(matches) >= max(2, math.ceil(len(centers)/2))
                                                  and len(matches) >= .5*len(detected)),
                         "inverted_alerts": len(accepted_centers(result["cases"]["inverted"], method, thresholds)),
                         "original_alerts": len(original), "exposure_days": result["exposure_days"]})
    return rows


def summarize_rows(rows):
    hosts = len(rows); events = sum(r["injected_events"] for r in rows)
    added_hosts = sum(r["incremental_recovery"] for r in rows)
    return {"registered_hosts": hosts, "hosts_with_observable_injection": sum(r["injected_events"] > 0 for r in rows),
            "any_matched_hosts": sum(r["any_match"] for r in rows), "incremental_hosts": added_hosts,
            "incremental_host_recovery": added_hosts/hosts if hosts else None,
            "host_wilson_95": _wilson(added_hosts, hosts), "injected_events": events,
            "matched_events": sum(r["matched_events"] for r in rows),
            "original_matches": sum(r["original_matches"] for r in rows),
            "incremental_events": sum(r["incremental_events"] for r in rows),
            "incremental_event_recovery": sum(r["incremental_events"] for r in rows)/events if events else None,
            "pattern_recovered_hosts": sum(r["pattern_recovery"] for r in rows),
            "pattern_eligible_hosts": sum(r["injected_events"] >= 2 for r in rows),
            "inverted_alerts": sum(r["inverted_alerts"] for r in rows),
            "inverted_alerts_per_27_days": sum(r["inverted_alerts"] for r in rows)/sum(r["exposure_days"] for r in rows)*27,
            "original_alerts_per_27_days": sum(r["original_alerts"] for r in rows)/sum(r["exposure_days"] for r in rows)*27}


def finish(results, spec, spec_sha, operating, output):
    thresholds = {**spec["neural_thresholds"], **{k: operating["classical"][k]["selected_threshold"] for k in ("bls", "tls")}}
    rows = recovery_rows(results, thresholds)
    pd.DataFrame(rows).to_csv(output/"host_recovery.csv", index=False)
    summary = {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(),
               "registered_hosts": len(results), "thresholds": thresholds,
               "methods": {m: summarize_rows([r for r in rows if r["method"] == m]) for m in METHODS},
               "by_mode": {mode: {m: summarize_rows([r for r in rows if r["method"] == m and r["mode"] == mode])
                                  for m in METHODS} for mode in spec["config"]["modes"]},
               "by_depth": {str(depth): {m: summarize_rows([r for r in rows if r["method"] == m and r["depth"] == depth])
                                         for m in METHODS} for depth in spec["config"]["depths"]},
               "paired_incremental_recovery": {},
               "claims": {"model_training_or_tuning_on_evaluation": False, "planet_classification": False,
                          "survey_false_positive_rate": False, "watcher_deployed": False}}
    neural = {r["target_id"]: r for r in rows if r["method"] == "v3"}
    for m in ("v2", "bls", "tls"):
        others = [r for r in rows if r["method"] == m]
        wins = sum(neural[r["target_id"]]["incremental_recovery"] and not r["incremental_recovery"] for r in others)
        losses = sum(r["incremental_recovery"] and not neural[r["target_id"]]["incremental_recovery"] for r in others)
        summary["paired_incremental_recovery"]["v3_vs_"+m] = {"v3_only": wins, "other_only": losses,
            "mcnemar_exact_two_sided_p": float(binomtest(wins, wins+losses).pvalue) if wins+losses else 1.,
            "multiplicity_adjusted": False}
    atomic_json(output/"summary.json", summary)
    lines = ["# Frozen physical-injection benchmark", "",
             f"Completed all {len(results)} development-disjoint hosts after classical-search calibration on 78 separate hosts.",
             "v2/v3 weights and their existing thresholds were frozen before this run. BLS/TLS thresholds were selected only on calibration controls.", "",
             "| Method | Threshold | Incremental host recovery | Incremental event recovery | Inverted alerts / 27 days |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for m, row in summary["methods"].items():
        lines.append(f"| {m} | {thresholds[m]:g} | {row['incremental_hosts']}/{row['registered_hosts']} ({row['incremental_host_recovery']:.1%}) | "
                     f"{row['incremental_events']}/{row['injected_events']} ({row['incremental_event_recovery']:.1%}) | {row['inverted_alerts_per_27_days']:.3f} |")
    lines += ["", "Recovery requires a detected event within half an injected transit duration and one-to-one matching. "
              "Incremental recovery counts matches absent in the original, uninjected observation; it reduces chance-match credit. "
              "All 90 hosts remain in the denominator, including any without sufficiently observed injections.", "",
              "## Recovery by event mode", "", "| Mode | Hosts | v2 | v3 | BLS | TLS |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for mode, data in summary["by_mode"].items():
        lines.append(f"| {mode} | {data['v3']['registered_hosts']} | " + " | ".join(str(data[m]["incremental_hosts"]) for m in METHODS) + " |")
    lines += ["", "## Paired host comparisons", ""]
    for label, row in summary["paired_incremental_recovery"].items():
        lines.append(f"- {label}: v3-only {row['v3_only']}, other-only {row['other_only']}; exact two-sided McNemar p={row['mcnemar_exact_two_sided_p']:.4g} (unadjusted).")
    lines += ["", "## Scope and limitations", "",
              "This compares event localization, not confirmed planets or classifier accuracy. BLS/TLS receive the exact aperture sums from the injected pixel cubes "
              "and share a blind trial-period grid, while applying their declared 1.5-day median detrending. They retain one strongest periodic hypothesis; "
              "the neural models retain all duration-compatible events. Single transits and TTVs therefore test different algorithmic capabilities. "
              "The same calibration alert budget does not guarantee identical realized evaluation alert rates. One failed search would block completion rather than silently remove its host.", "",
              "Physical circular-orbit transit shapes use quadratic limb darkening and seven sub-exposure samples via "
              "[batman](https://lkreidberg.github.io/batman/docs/html/tutorial.html). Stellar density and limb darkening are synthetic assumptions. "
              "The empirical static pixel template is not a deblended PRF, and no new photon noise is drawn. TTV shifts are synthetic rather than an N-body solution. "
              "[Astropy BLS](https://docs.astropy.org/en/stable/timeseries/bls.html) and "
              "[TLS](https://transitleastsquares.readthedocs.io/en/latest/Python%20interface.html) are bounded search baselines, not exhaustive optimizations.", "",
              "The 90 hosts were previously scanned by frozen v2 but never used for training or threshold selection. This is one archival sector per host. "
              "Sign-inverted controls are an empirical null, not a complete astrophysical false-positive population. "
              "Background sources, eclipsing binaries, catalog reconciliation, repeated training seeds, and multi-sector evidence remain outstanding. "
              "This run does not deploy either model to production.", "",
              "[Frozen protocol](spec.json) · [Calibration](operating_point.json) · [Summary](summary.json) · [Host results](host_recovery.csv)"]
    (output/"report.md").write_text("\n".join(lines)+"\n")
    files = {str(p.relative_to(output)): file_sha256(p) for p in output.rglob("*.json") if p.name != "complete.json"}
    files.update({p: file_sha256(output/p) for p in ("report.md", "host_recovery.csv")})
    atomic_json(output/"complete.json", {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(), "files": files})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_physical_benchmark_v1.json")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    path = ROOT/args.config
    config = validate_config(json.loads(path.read_text()))
    spec, spec_sha, output = prepare(config, path)
    print(json.dumps({"stage": "frozen", "spec_sha256": spec_sha, "evaluation_hosts": len(spec["targets"]["evaluation"])}), flush=True)
    if (output/"complete.json").exists():
        _checked_complete(output); print('{"status":"already_complete"}', flush=True); return
    if args.prepare_only:
        return
    calibration = run_role(spec, spec_sha, "calibration")
    operating = {"spec_sha256": spec_sha, "neural": spec["neural_thresholds"],
                 "classical": choose_thresholds(calibration, config),
                 "calibration_hosts": len(calibration), "frozen_before_evaluation": True}
    op_path = output/"operating_point.json"
    if op_path.exists():
        old = json.loads(op_path.read_text())
        if {k: v for k, v in old.items() if k != "frozen_at"} != operating:
            raise ValueError("Frozen operating point changed")
        operating = old
    else:
        operating["frozen_at"] = utc_now(); atomic_json(op_path, operating)
    print(json.dumps({"stage": "operating_point_frozen", "thresholds": {k: v["selected_threshold"] for k, v in operating["classical"].items()}}), flush=True)
    results = run_role(spec, spec_sha, "evaluation")
    summary = finish(results, spec, spec_sha, operating, output)
    print(json.dumps({"status": "complete", "methods": summary["methods"]}), flush=True)


if __name__ == "__main__":
    main()
