#!/usr/bin/env python3
"""Calibrate continuous AI-telescope alerts and audit synthetic transit recovery."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from scripts.experiments.ai_telescope_blind_scan import (
    _checked_complete, _context, group_events, infer_target,
    validate_config as validate_scan_config,
)
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.pixels import TargetPixels, read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_continuous_validation_v1"
FIELDS = {
    "schema_version", "model_run", "physical_run", "scan_config", "review_run",
    "output", "roles", "depths", "durations_hours", "event_modes",
    "nominal_period_days", "ttv_fraction_of_duration", "ingress_fraction",
    "threshold_grid", "target_control_events_per_27_days",
    "maximum_hosts_per_role", "seed", "cpu_threads",
}
ALLOWED_MODES = {"single", "periodic", "ttv"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema_version") != 1:
        raise ValueError("Continuous-validation config differs from schema")
    for key in ("model_run", "physical_run", "scan_config", "review_run", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Continuous-validation paths must stay inside the project")
    if value["roles"] != ["calibration", "audit"]:
        raise ValueError("Calibration must finish before the fixed audit role")
    if (not isinstance(value["event_modes"], list) or not value["event_modes"]
            or set(value["event_modes"]) - ALLOWED_MODES):
        raise ValueError("Invalid event modes")
    for key, low, high in (("depths", 1e-5, .1), ("durations_hours", .25, 24.),
                           ("threshold_grid", .5, 1.)):
        items = value[key]
        if (not isinstance(items, list) or not items or any(
                type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high
                for x in items) or len(set(items)) != len(items)):
            raise ValueError("Invalid " + key)
    if value["threshold_grid"] != sorted(value["threshold_grid"]):
        raise ValueError("Threshold grid must be increasing")
    for key, low, high in (("nominal_period_days", 1., 30.),
                           ("ttv_fraction_of_duration", 0., 3.),
                           ("ingress_fraction", .01, .49),
                           ("target_control_events_per_27_days", 0., 100.)):
        item = value[key]
        if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError("Invalid " + key)
    for key, low, high in (("maximum_hosts_per_role", 1, 1000),
                           ("seed", 0, 2**31 - 1), ("cpu_threads", 1, 8)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    return value


def aperture_mask(pixels: TargetPixels):
    mask = (pixels.aperture & 2) != 0
    if not mask.any():
        mask = pixels.aperture > 0
    if not mask.any():
        raise ValueError("Target has no usable aperture")
    return mask


def _valid(pixels):
    mask = aperture_mask(pixels)
    light = np.nansum(pixels.flux[:, mask], axis=1)
    return (pixels.quality == 0) & np.isfinite(pixels.time) & np.isfinite(light)


def exposure_days(pixels):
    valid = _valid(pixels)
    differences = np.diff(pixels.time[valid])
    cadence = float(np.median(differences[np.isfinite(differences) & (differences > 0)]))
    if not math.isfinite(cadence) or cadence <= 0:
        raise ValueError("Target cadence is undefined")
    return float(valid.sum() * cadence)


def inverted_residual_control(pixels: TargetPixels):
    """Invert real pixel residuals around a per-pixel robust center."""
    valid = _valid(pixels)
    with np.errstate(all="ignore"):
        reference = np.nanmedian(pixels.flux[valid], axis=0)
    if not np.isfinite(reference).any():
        raise ValueError("Pixel reference is undefined")
    cube = 2 * reference[None, :, :] - np.asarray(pixels.flux, dtype=np.float64)
    return replace(pixels, flux=cube)


def condition_schedule(target_ids, config, role):
    """Assign a balanced factorial before any model outputs are examined."""
    target_ids = sorted(map(str, target_ids), key=lambda x: int(x))
    grid = list(itertools.product(config["depths"], config["durations_hours"],
                                  config["event_modes"]))
    repeated = (grid * math.ceil(len(target_ids) / len(grid)))[:len(target_ids)]
    role_offset = 0 if role == "calibration" else 1
    rng = np.random.default_rng(np.random.SeedSequence([config["seed"], role_offset]))
    rng.shuffle(repeated)
    return {target: {"depth": float(condition[0]),
                     "duration_hours": float(condition[1]), "mode": condition[2]}
            for target, condition in zip(target_ids, repeated)}


def event_centers(pixels, condition, config, target_id):
    valid = _valid(pixels)
    time = pixels.time
    usable = time[valid]
    if len(usable) < 1024:
        raise ValueError("Target has insufficient valid cadences")
    duration_days = condition["duration_hours"] / 24.
    margin = max(duration_days * 2, .25)
    low, high = float(np.nanmin(usable) + margin), float(np.nanmax(usable) - margin)
    if low >= high:
        raise ValueError("Target baseline is too short for injection")
    seed = np.random.SeedSequence([config["seed"], int(target_id) % (2**32)])
    rng = np.random.default_rng(seed)
    candidates = usable[(usable >= low) & (usable <= high)]
    anchor = float(candidates[len(candidates) // 2])
    if condition["mode"] == "single":
        centers = [anchor]
    else:
        period = config["nominal_period_days"]
        first = anchor - math.floor((anchor - low) / period) * period
        centers = list(np.arange(first, high + period / 10, period, dtype=float))
        if condition["mode"] == "ttv":
            jitter = rng.uniform(-1, 1, len(centers)) * duration_days * config["ttv_fraction_of_duration"]
            centers = (np.asarray(centers) + jitter).tolist()
    kept = []
    for center in centers:
        inside = valid & (np.abs(time - center) <= duration_days / 2)
        if inside.sum() >= 2:
            kept.append(float(center))
    if not kept:
        raise ValueError("No injected event has enough valid cadences")
    return kept


def inject_transits(pixels: TargetPixels, condition, centers, ingress_fraction):
    """Inject a spatially coherent trapezoid through an estimated target PSF."""
    valid = _valid(pixels)
    aperture = aperture_mask(pixels)
    cube = np.asarray(pixels.flux, dtype=np.float64).copy()
    with np.errstate(all="ignore"):
        reference = np.nanmedian(cube[valid], axis=0)
    finite = reference[np.isfinite(reference)]
    floor = float(np.nanpercentile(finite, 20)) if len(finite) else 0.
    template = np.clip(reference - floor, 0, None)
    aperture_template = float(np.nansum(template[aperture]))
    aperture_baseline = float(np.nanmedian(np.nansum(cube[valid][:, aperture], axis=1)))
    if aperture_template <= 0 or not math.isfinite(aperture_baseline) or aperture_baseline <= 0:
        raise ValueError("Target PSF cannot be estimated")
    template *= aperture_baseline / aperture_template
    duration_days = condition["duration_hours"] / 24.
    half = duration_days / 2
    ingress = duration_days * ingress_fraction
    profile = np.zeros(len(pixels.time), dtype=np.float64)
    for center in centers:
        distance = np.abs(pixels.time - center)
        value = np.clip((half - distance) / ingress, 0, 1)
        profile = np.maximum(profile, value)
    profile[~valid] = 0
    cube -= condition["depth"] * profile[:, None, None] * template[None, :, :]
    realized = (condition["depth"] * float(np.nansum(template[aperture]))
                / aperture_baseline)
    return replace(pixels, flux=cube), profile, float(realized)


def duration_compatible(events, time, bounds):
    output = []
    for event in events:
        hours = float((time[event["end_index"]] - time[event["start_index"]]) * 24)
        if bounds[0] <= hours <= bounds[1]:
            output.append({**event, "duration_hours": hours})
    return output


def evaluate_scores(score, valid, time, centers, duration_hours, thresholds, scan, bounds):
    result = {}
    tolerance_days = duration_hours / 24.
    for threshold in thresholds:
        events = group_events(score, valid, threshold, scan["merge_gap_cadences"],
                              scan["minimum_event_cadences"])
        events = duration_compatible(events, time, bounds)
        matched_centers = set()
        matched_events = 0
        for event in events:
            matches = [i for i, center in enumerate(centers)
                       if abs(float(time[event["peak_index"]]) - center) <= tolerance_days]
            if matches:
                matched_events += 1
                matched_centers.update(matches)
        result[threshold_key(threshold)] = {
            "candidate_like_events": len(events),
            "matched_detection_events": matched_events,
            "unmatched_detection_events": len(events) - matched_events,
            "injected_events": len(centers),
            "recovered_injected_events": len(matched_centers),
            "system_recovered": bool(matched_centers),
        }
    return result


def threshold_key(value):
    return f"{float(value):.8f}"


def select_threshold(results, thresholds, target_rate):
    exposure = sum(row["exposure_days"] for row in results)
    if exposure <= 0:
        raise ValueError("Calibration exposure is empty")
    table = []
    for threshold in sorted(thresholds):
        events = sum(row["control"][threshold_key(threshold)]["candidate_like_events"]
                     for row in results)
        per_27 = float(events / exposure * 27)
        table.append({"threshold": float(threshold), "control_events": int(events),
                      "exposure_days": float(exposure), "events_per_27_days": per_27,
                      "meets_target": per_27 <= target_rate})
    eligible = [row for row in table if row["meets_target"]]
    selected = eligible[0] if eligible else table[-1]
    return {"selected_threshold": selected["threshold"], "target_events_per_27_days": target_rate,
            "target_met": bool(selected["meets_target"]), "selection_rule":
            "lowest_predeclared_threshold_meeting_the_calibration_control_alert_target",
            "calibration_table": table}


def _wilson(successes, total, z=1.959963984540054):
    if total <= 0:
        return [None, None]
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0., center-half), min(1., center+half)]


def recovery_summary(results, threshold):
    key = threshold_key(threshold)
    events = sum(x["injection"][key]["injected_events"] for x in results)
    recovered_events = sum(x["injection"][key]["recovered_injected_events"] for x in results)
    systems = len(results)
    recovered_systems = sum(bool(x["injection"][key]["system_recovered"]) for x in results)
    unmatched = sum(x["injection"][key]["unmatched_detection_events"] for x in results)
    return {"hosts": systems, "systems_recovered": recovered_systems,
            "system_recovery": recovered_systems/systems if systems else None,
            "system_recovery_wilson_95": _wilson(recovered_systems, systems),
            "injected_events": events, "events_recovered": recovered_events,
            "event_recovery": recovered_events/events if events else None,
            "event_recovery_wilson_95": _wilson(recovered_events, events),
            "unmatched_detection_events": unmatched}


def control_summary(results, threshold):
    key = threshold_key(threshold)
    exposure = sum(x["exposure_days"] for x in results)
    events = sum(x["control"][key]["candidate_like_events"] for x in results)
    return {"hosts": len(results), "exposure_days": exposure, "candidate_like_events": events,
            "events_per_27_days": events/exposure*27 if exposure else None}


def stratified(results, threshold):
    output = {}
    for field in ("depth", "duration_hours", "mode"):
        values = sorted({row["condition"][field] for row in results}, key=str)
        output[field] = {str(value): recovery_summary(
            [row for row in results if row["condition"][field] == value], threshold)
                         for value in values}
    return output


def scan_one(model, pixels, context_stats, condition, config, scan, thresholds, bounds):
    centers = event_centers(pixels, condition, config, pixels.target_id)
    injected, profile, realized = inject_transits(
        pixels, condition, centers, config["ingress_fraction"])
    control = inverted_residual_control(pixels)
    context = _context(pixels.context, context_stats)
    control_score, control_valid, control_starts = infer_target(model, control, context, scan)
    injection_score, injection_valid, injection_starts = infer_target(model, injected, context, scan)
    if control_starts != injection_starts or not np.array_equal(control_valid, injection_valid):
        raise ValueError("Synthetic variants changed the scan geometry")
    return {
        "status": "complete", "version": VERSION, "target_id": pixels.target_id,
        "sector": int(pixels.sector), "source_sha256": pixels.sha256,
        "exposure_days": exposure_days(pixels), "windows_scanned_per_variant": len(control_starts),
        "condition": {**condition, "centers_btjd": centers,
                      "injected_events": len(centers),
                      "injected_cadences": int(np.sum(profile > 0)),
                      "realized_aperture_depth": realized,
                      "shape": "trapezoid", "ingress_fraction": config["ingress_fraction"]},
        "control_transformation": "per_pixel_residual_sign_inversion",
        "control": evaluate_scores(control_score, control_valid, pixels.time, [],
                                   condition["duration_hours"], thresholds, scan, bounds),
        "injection": evaluate_scores(injection_score, injection_valid, pixels.time, centers,
                                     condition["duration_hours"], thresholds, scan, bounds),
        "score_diagnostics": {
            "control_max": float(np.nanmax(control_score)),
            "injection_max": float(np.nanmax(injection_score)),
        },
    }


def _write_csv(path, rows):
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows).to_csv(temporary, index=False)
    temporary.replace(path)


def write_report(path, summary):
    selected = summary["operating_point"]["selected_threshold"]
    frozen = summary["frozen_threshold"]
    audit = summary["audit"]
    lines = [
        "# Continuous-scan injection and control validation", "",
        "The frozen v2 localizer was evaluated end to end on complete TESS sectors. The operating "
        "threshold was selected on calibration hosts before audit aggregation.", "",
        f"- Calibration hosts: **{summary['scope']['calibration_hosts']}**",
        f"- Audit hosts: **{summary['scope']['audit_hosts']}**",
        f"- Frozen threshold: **{frozen:.6f}**",
        f"- Continuous-scan threshold: **{selected:.6f}**",
        f"- Calibration control target met: **{summary['operating_point']['target_met']}**", "",
        "| Audit operating point | System recovery | Event recovery | Control events / 27 d |", "|---|---:|---:|---:|",
    ]
    for name in ("frozen", "selected"):
        row = audit[name]
        lines.append(f"| {name} | {row['recovery']['system_recovery']:.1%} "
                     f"({row['recovery']['systems_recovered']}/{row['recovery']['hosts']}) | "
                     f"{row['recovery']['event_recovery']:.1%} "
                     f"({row['recovery']['events_recovered']}/{row['recovery']['injected_events']}) | "
                     f"{row['control']['events_per_27_days']:.3f} |")
    lines += ["", "## Interpretation", "",
              "The control rate is an empirical alert rate on sign-inverted real pixel residuals. "
              "It is useful for choosing an overlap-aware operating point, but it is not a survey-wide "
              "astrophysical false-positive rate.", "",
              "Recovery uses synthetic trapezoidal, spatially coherent target injections. It does not "
              "yet cover limb-darkening, eclipsing binaries, background-source injections, every TESS "
              "sector, or independently labelled prospective hosts."]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_continuous_validation_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    torch.set_num_threads(config["cpu_threads"])
    model_run, physical, review = (ROOT / config[x] for x in
                                   ("model_run", "physical_run", "review_run"))
    model_complete = _checked_complete(model_run)
    physical_complete = _checked_complete(physical)
    review_complete = _checked_complete(review)
    scan = validate_scan_config(json.loads((ROOT / config["scan_config"]).read_text()))
    model_spec = json.loads((model_run / "spec.json").read_text())
    checkpoint = torch.load(model_run / "ai_telescope_context.pt", map_location="cpu", weights_only=True)
    frozen_threshold = float(checkpoint["threshold"]["threshold"])
    thresholds = sorted(set([frozen_threshold] + [float(x) for x in config["threshold_grid"]
                                                  if x >= frozen_threshold]))
    duration = json.loads((review / "summary.json").read_text())["duration_prior"]
    bounds = (float(duration["lower_hours"]), float(duration["upper_hours"]))
    with np.load(model_run / "dataset.npz", allow_pickle=False) as saved:
        ids, roles = saved["target_id"].astype(str), saved["role"].astype(str)
    role_by_id = {}
    for target, role in zip(ids, roles):
        if target in role_by_id and role_by_id[target] != role:
            raise ValueError("Target crosses roles")
        role_by_id[target] = role
    cohort = json.loads((physical / "cohort.json").read_text())
    targets = {str(x["target_id"]): x for x in cohort["targets"] if str(x["target_id"]) in role_by_id}
    plan = json.loads((physical / "download_plan.json").read_text())
    products = {str(x["target_id"]): x for x in plan["products"]}
    source_hashes = {}
    for path in (model_run / "auxiliary").glob("TIC*.json"):
        receipt = json.loads(path.read_text())
        source_hashes[str(receipt["target_id"])] = receipt["source_sha256"]
    selected = {}
    schedules = {}
    for role in config["roles"]:
        members = sorted((x for x in role_by_id if role_by_id[x] == role), key=int)
        members = members[:config["maximum_hosts_per_role"]]
        if not members:
            raise ValueError("Empty role: " + role)
        selected[role] = members
        schedules[role] = condition_schedule(members, config, role)
    sources = ("scripts/experiments/ai_telescope_continuous_validation.py",
               "scripts/experiments/ai_telescope_blind_scan.py", "scripts/research/pixels.py",
               "training/ai_telescope.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "input_receipts": {"model": file_sha256(model_run / "complete.json"),
                               "physical": file_sha256(physical / "complete.json"),
                               "review": file_sha256(review / "complete.json")},
            "input_spec_sha256": {"model": model_complete["spec_sha256"],
                                  "physical": physical_complete["spec_sha256"],
                                  "review": review_complete["spec_sha256"]},
            "scan_config": scan, "frozen_threshold": frozen_threshold,
            "evaluated_thresholds": thresholds, "duration_bounds_hours": list(bounds),
            "selected_target_ids": selected, "condition_schedule": schedules,
            "source_files": {name: file_sha256(ROOT / name) for name in sources},
            "protocol": {"threshold_selection_role": "calibration",
                         "final_evaluation_role": "audit",
                         "prospective_90_host_cohort_used": False,
                         "audit_aggregation_after_operating_point_freeze": True}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    output = ROOT / config["output"]
    output.mkdir(parents=True, exist_ok=True)
    spec_path = output / "spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing output has a different specification")
    if (output / "complete.json").exists():
        _checked_complete(output)
        print(json.dumps({"status": "already_complete", "output": config["output"]}))
        return
    atomic_json(spec_path, spec)
    stats = json.loads((model_run / "context_stats.json").read_text())
    model_config = model_spec["config"]
    model = ExtendedEventLocalizer(len(stats["features"])*2, model_config["embedding_dim"],
                                   model_config["instrument_channels"])
    model.load_state_dict(checkpoint["localizer"])
    model.eval()
    cache = output / "targets"
    cache.mkdir(exist_ok=True)

    all_results = {}
    for role in config["roles"]:
        role_results = []
        for number, target_id in enumerate(selected[role], 1):
            result_path = cache / ("TIC" + target_id + ".json")
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if (result.get("status") != "complete" or result.get("spec_sha256") != spec_sha
                        or result.get("role") != role
                        or result.get("source_sha256") != source_hashes.get(target_id)):
                    raise ValueError("Cached target receipt mismatch: " + target_id)
            else:
                product = products[target_id]
                tpf = ROOT / "data/raw/tess/target_pixels" / ("TIC" + target_id) / product["filename"]
                pixels = read_target_pixels(tpf, target_id)
                if pixels.sha256 != source_hashes.get(target_id):
                    raise ValueError("TPF changed since model extraction: " + target_id)
                result = scan_one(model, pixels, stats, schedules[role][target_id], config,
                                  scan, thresholds, bounds)
                result.update(role=role, spec_sha256=spec_sha, completed_at=utc_now())
                atomic_json(result_path, result)
            role_results.append(result)
            if number % 5 == 0 or number == len(selected[role]):
                print(json.dumps({"stage": role, "processed": number,
                                  "hosts": len(selected[role])}), flush=True)
        all_results[role] = role_results
        if role == "calibration":
            operating = select_threshold(role_results, thresholds,
                                         config["target_control_events_per_27_days"])
            operating.update(status="frozen_before_audit_aggregation", frozen_at=utc_now(),
                             spec_sha256=spec_sha)
            operating_path = output / "operating_point.json"
            if operating_path.exists() and json.loads(operating_path.read_text()) != operating:
                existing = json.loads(operating_path.read_text())
                comparable = {k: v for k, v in operating.items() if k != "frozen_at"}
                old_comparable = {k: v for k, v in existing.items() if k != "frozen_at"}
                if comparable != old_comparable:
                    raise ValueError("Frozen operating point changed")
                operating = existing
            else:
                atomic_json(operating_path, operating)

    selected_threshold = float(operating["selected_threshold"])
    rows = []
    for role, role_results in all_results.items():
        for result in role_results:
            for name, threshold in (("frozen", frozen_threshold), ("selected", selected_threshold)):
                item = result["injection"][threshold_key(threshold)]
                rows.append({"target_id": result["target_id"], "role": role,
                             "operating_point": name, "threshold": threshold,
                             **{key: result["condition"][key] for key in
                                ("depth", "duration_hours", "mode", "injected_events",
                                 "realized_aperture_depth")},
                             "recovered_injected_events": item["recovered_injected_events"],
                             "system_recovered": item["system_recovered"],
                             "unmatched_detection_events": item["unmatched_detection_events"]})
    _write_csv(output / "host_recovery.csv", rows)
    audit_results = all_results["audit"]
    summary = {"status": "complete", "version": VERSION, "completed_at": utc_now(),
               "spec_sha256": spec_sha, "frozen_threshold": frozen_threshold,
               "operating_point": operating,
               "scope": {"calibration_hosts": len(all_results["calibration"]),
                         "audit_hosts": len(audit_results),
                         "calibration_exposure_days": sum(x["exposure_days"] for x in all_results["calibration"]),
                         "audit_exposure_days": sum(x["exposure_days"] for x in audit_results),
                         "model_inferences": 2 * sum(len(x) for x in all_results.values())},
               "audit": {},
               "claims": {"continuous_overlap_aware_threshold_calibrated": True,
                          "audit_used_for_threshold_selection": False,
                          "prospective_cohort_used": False,
                          "survey_false_alarm_rate": False,
                          "planet_recall": False,
                          "watcher_deployed": False},
               "limitations": [
                   "The null control inverts real per-pixel residuals and is not a complete astrophysical background population",
                   "The injections use a trapezoid and estimated target PSF rather than a limb-darkened physical transit model",
                   "The development audit was used by prior experiments and is not a pristine external test",
                   "One cached SPOC sector per host and a candidate-enriched cohort limit survey generalization",
               ]}
    for name, threshold in (("frozen", frozen_threshold), ("selected", selected_threshold)):
        summary["audit"][name] = {"threshold": threshold,
                                  "recovery": recovery_summary(audit_results, threshold),
                                  "control": control_summary(audit_results, threshold),
                                  "recovery_by_factor": stratified(audit_results, threshold)}
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "operating_point.json", "summary.json", "report.md", "host_recovery.csv")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files,
                                            "target_receipts": {str(path.relative_to(ROOT)): file_sha256(path)
                                                                for path in cache.glob("TIC*.json")}})
    print(json.dumps({"status": "complete", "operating_point": operating,
                      "audit": summary["audit"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
