"""Evaluate a calibrated neural/single-event hybrid on a newly frozen cohort.

No weights or thresholds are fitted on evaluation observations. Historical
benchmark artifacts remain sealed. Calibration must finish before evaluation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest
import torch

from scripts.experiments.ai_telescope_blind_scan import _checked_complete, _context, group_events, infer_target
from scripts.experiments.ai_telescope_continuous_validation import duration_compatible, exposure_days, inverted_residual_control
from scripts.experiments.ai_telescope_physical_benchmark import (
    checked_record, classical_searches, digest, matched_indices, physical_injection,
    schedule, summarize_rows, write_record,
)
from scripts.experiments.mission_adaptation import atomic_json
from scripts.experiments.transit_recovery import (
    aperture_samples, exact_score_threshold, select_count_threshold, single_event_search,
)
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_recovery_v1"
METHODS = ("v3_original", "v3_calibrated", "single_event", "hybrid", "bls_exact", "tls_exact")
STATE = {}


def validate_config(config):
    fields = {"schema_version", "baseline_run", "cohort_run", "output", "seed", "durations_hours",
              "minimum_score", "minimum_coverage", "control_budget_per_27_days",
              "calibration_budget_fraction", "hybrid_neural_budget_fraction", "workers"}
    if set(config) != fields or config["schema_version"] != 1:
        raise ValueError("Recovery config differs from schema")
    for key in ("baseline_run", "cohort_run", "output"):
        path = Path(config[key])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Paths must stay inside the repository")
    output = (ROOT / config["output"]).resolve()
    for key in ("baseline_run", "cohort_run"):
        source = (ROOT / config[key]).resolve()
        if output == source or output in source.parents or source in output.parents:
            raise ValueError("Recovery output overlaps an input")
    if not output.is_relative_to(ROOT.resolve()):
        raise ValueError("Recovery output escapes repository")
    if type(config["workers"]) is not int or not 1 <= config["workers"] <= 4:
        raise ValueError("Invalid worker budget")
    if type(config["seed"]) is not int or not 0 <= config["seed"] < 2**31:
        raise ValueError("Invalid seed")
    durations = config["durations_hours"]
    if (not isinstance(durations, list) or not durations or durations != sorted(set(durations))
            or any(not np.isfinite(d) or not .25 <= d <= 24 for d in durations)):
        raise ValueError("Invalid event durations")
    for key, lo, hi in (("minimum_score", 0, 20), ("minimum_coverage", .5, 1),
                        ("control_budget_per_27_days", .1, 2), ("calibration_budget_fraction", .1, 1),
                        ("hybrid_neural_budget_fraction", .1, .9)):
        if not np.isfinite(config[key]) or not lo <= config[key] <= hi:
            raise ValueError("Invalid " + key)
    return config


def prepare(config, config_path):
    baseline = ROOT / config["baseline_run"]
    _checked_complete(baseline)
    prior = json.loads((baseline / "spec.json").read_text())
    cohort_run = ROOT / config["cohort_run"]
    cohort_path = cohort_run / "manifest.json"
    if json.loads((cohort_run / "frozen.json").read_text())["manifest_sha256"] != file_sha256(cohort_path):
        raise ValueError("Fresh cohort receipt mismatch")
    cohort = json.loads(cohort_path.read_text())
    targets = cohort["targets"]
    ids = [t["target_id"] for t in targets]
    forbidden = {str(t) for t in cohort["exclusions"]["host_ids"]}
    forbidden.update(t["target_id"] for role in prior["targets"].values() for t in role)
    if len(ids) != len(set(ids)) or set(ids) & forbidden:
        raise ValueError("Fresh evaluation host overlap")
    physical_config = {**prior["config"], "seed": config["seed"]}
    sources = set(prior["source_files"]) | {
        "scripts/experiments/ai_telescope_recovery.py", "scripts/experiments/transit_recovery.py"}
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "sources": {name: file_sha256(ROOT / name) for name in sorted(sources)},
            "inputs": {"baseline_complete": file_sha256(baseline / "complete.json"),
                       "cohort_manifest": file_sha256(cohort_path)},
            "calibration_targets": prior["targets"]["calibration"], "evaluation_targets": targets,
            "model_run": prior["config"]["model_runs"]["v3"],
            "model_receipt_sha256": file_sha256(ROOT / prior["config"]["model_runs"]["v3"] / "complete.json"),
            "physical_config": physical_config, "schedule": schedule(ids, physical_config),
            "scan_config": prior["scan_config"], "neural_duration_bounds_hours": prior["duration_bounds_hours"],
            "original_neural_threshold": prior["neural_thresholds"]["v3"],
            "neural_threshold_grid": sorted(set([round(t, 6) for t in np.arange(.5, 1., .005)]
                                                  + [.999, .9999, 1.000001])),
            "protocol": {"weights_fitted": False, "threshold_role": "calibration_only",
                         "evaluation_before_calibration": False, "prior_90_hosts_reused": False,
                         "cross_mission_and_proximity_quarantine": True,
                         "new_search": "local sideband box significance with duration-specific robust noise inflation",
                         "hybrid": "union after assigning half the calibration budget to each branch",
                         "calibration_rule": "smallest boundary with max(Poisson95,host-bootstrap95) <= half budget; neural suffix must also pass",
                         "calibration_guarantee": "operational margin only; no distribution-shift or simultaneous coverage guarantee",
                         "classifier_validation": False, "deployment": False}}
    output = ROOT / config["output"]
    output.mkdir(parents=True, exist_ok=True)
    path = output / "spec.json"
    if path.exists() and json.loads(path.read_text()) != spec:
        raise ValueError("Frozen recovery specification changed; use a new experiment")
    atomic_json(path, spec)
    return spec, digest(spec), output


def initialize(spec, spec_sha, operating=None):
    torch.set_num_threads(1)
    run = ROOT / spec["model_run"]
    stats = json.loads((run / "context_stats.json").read_text())
    config = json.loads((run / "spec.json").read_text())["config"]
    model = ExtendedEventLocalizer(len(stats["features"]) * 2, config["embedding_dim"], config["instrument_channels"])
    checkpoint = torch.load(run / "ai_telescope_context.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["localizer"])
    model.eval()
    STATE.update(spec=spec, spec_sha=spec_sha, operating=operating, model=model, stats=stats)


def neural_events(scores, valid, time, threshold):
    spec = STATE["spec"]
    scan = spec["scan_config"]
    events = group_events(scores, valid, threshold, scan["merge_gap_cadences"], scan["minimum_event_cadences"])
    events = duration_compatible(events, time, spec["neural_duration_bounds_hours"])
    cadence = float(np.median(np.diff(time[np.isfinite(time)])))
    return [{"center_btjd": float(time[e["peak_index"]]), "score": float(e["max_probability"]),
             "duration_hours": float((time[e["end_index"]] - time[e["start_index"]] + cadence) * 24)} for e in events]


def searches(pixels):
    spec = STATE["spec"]
    time, flux = aperture_samples(pixels)
    # Preserve identical aperture photometry and exposure for all comparators.
    old_valid = (pixels.quality == 0) & np.isfinite(pixels.time)
    if len(time) != int(old_valid.sum()):
        raise ValueError("Incomplete aperture: cannot compare frozen neural photometry fairly")
    single = single_event_search(time, flux, spec["config"]["durations_hours"],
                                spec["config"]["minimum_score"], spec["config"]["minimum_coverage"])
    scores, valid, _ = infer_target(STATE["model"], pixels, _context(pixels.context, STATE["stats"]), spec["scan_config"])
    return single, scores, valid


def calibration_target(target):
    spec, spec_sha = STATE["spec"], STATE["spec_sha"]
    path = ROOT / spec["config"]["output"] / "calibration" / ("TIC" + target["target_id"] + ".json")
    if path.exists():
        return checked_record(path, spec_sha)
    pixels = read_target_pixels(ROOT / target["path"], target["target_id"])
    if pixels.sha256 != target["sha256"]:
        raise ValueError("Calibration source changed")
    single, scores, valid = searches(inverted_residual_control(pixels))
    baseline = ROOT / spec["config"]["baseline_run"]
    baseline_sha = digest(json.loads((baseline / "spec.json").read_text()))
    classical = checked_record(baseline / "calibration" / path.name, baseline_sha)["cases"]["inverted"]
    row = {"spec_sha256": spec_sha, "target_id": target["target_id"], "source_sha256": pixels.sha256,
           "exposure_days": exposure_days(pixels), "single_events": single,
           "neural_counts": [len(neural_events(scores, valid, pixels.time, t)) for t in spec["neural_threshold_grid"]],
           "classical": {k: classical[k] for k in ("bls", "tls")}}
    write_record(path, row)
    return row


def calibrate(rows, spec, spec_sha):
    config = spec["config"]
    exposure = [r["exposure_days"] for r in rows]
    budget, margin = config["control_budget_per_27_days"], config["calibration_budget_fraction"]
    fraction = config["hybrid_neural_budget_fraction"]
    counts = np.array([r["neural_counts"] for r in rows]).T
    result = {"spec_sha256": spec_sha, "frozen_at": utc_now(), "calibration_hosts": len(rows),
              "v3_calibrated": select_count_threshold(spec["neural_threshold_grid"], counts, exposure, budget, margin),
              "hybrid_neural": select_count_threshold(spec["neural_threshold_grid"], counts, exposure, budget * fraction, margin)}
    singles = [r["single_events"] for r in rows]
    result["single_event"] = exact_score_threshold(singles, exposure, budget, margin, config["minimum_score"])
    result["hybrid_single"] = exact_score_threshold(singles, exposure, budget * (1 - fraction), margin, config["minimum_score"])
    for method in ("bls", "tls"):
        events = [[{"score": r["classical"][method]["score"], "count": len(r["classical"][method]["centers_btjd"])}] for r in rows]
        result[method + "_exact"] = exact_score_threshold(events, exposure, budget, margin)
    return result


def evaluation_case(pixels):
    spec, operating = STATE["spec"], STATE["operating"]
    if operating is None or operating["spec_sha256"] != STATE["spec_sha"]:
        raise ValueError("Evaluation requires a frozen calibration operating point")
    single, scores, valid = searches(pixels)
    thresholds = {k: v["selected_threshold"] for k, v in operating.items() if isinstance(v, dict) and "selected_threshold" in v}
    calibrated = neural_events(scores, valid, pixels.time, thresholds["v3_calibrated"])
    neural_branch = neural_events(scores, valid, pixels.time, thresholds["hybrid_neural"])
    single_branch = [e for e in single if e["score"] >= thresholds["hybrid_single"]]
    # Cross-branch scores are not comparable. Keep neural centers first and add
    # only unmatched box centers; merging can never increase the sum of alerts.
    hybrid = list(neural_branch)
    for event in single_branch:
        if all(abs(event["center_btjd"] - e["center_btjd"]) > max(event["duration_hours"], e["duration_hours"]) / 48 for e in hybrid):
            hybrid.append(event)
    events = {"v3_original": neural_events(scores, valid, pixels.time, spec["original_neural_threshold"]),
              "v3_calibrated": calibrated, "single_event": [e for e in single if e["score"] >= thresholds["single_event"]],
              "hybrid": hybrid}
    result = {name: {"centers_btjd": [e["center_btjd"] for e in found], "events": found} for name, found in events.items()}
    classical = classical_searches(pixels, spec["physical_config"])
    for method in ("bls", "tls"):
        source = classical[method]
        result[method + "_exact"] = {**source, "centers_btjd": source["centers_btjd"] if source["score"] >= thresholds[method + "_exact"] else []}
    return result


def evaluation_target(target):
    spec, spec_sha = STATE["spec"], STATE["spec_sha"]
    output = ROOT / spec["config"]["output"] / "evaluation"
    path = output / ("TIC" + target["target_id"] + ".json")
    if path.exists():
        row = checked_record(path, spec_sha)
        if row["operating_sha256"] != digest(STATE["operating"]):
            raise ValueError("Evaluation cache operating point mismatch")
        return row
    pixels = read_target_pixels(ROOT / target["path"], target["target_id"])
    if pixels.sha256 != target["sha256"]:
        raise ValueError("Fresh target pixels changed")
    injected, truth = physical_injection(pixels, spec["schedule"][target["target_id"]], spec["physical_config"])
    cases = {}
    for name in ("original", "injected", "inverted"):
        case_path = output / ("TIC" + target["target_id"] + "-" + name + ".json")
        if case_path.exists():
            record = checked_record(case_path, spec_sha)
            if record["operating_sha256"] != digest(STATE["operating"]):
                raise ValueError("Case cache operating point mismatch")
            cases[name] = record["result"]
        else:
            current = injected if name == "injected" else inverted_residual_control(pixels) if name == "inverted" else pixels
            cases[name] = evaluation_case(current)
            write_record(case_path, {"spec_sha256": spec_sha, "operating_sha256": digest(STATE["operating"]), "result": cases[name]})
    row = {"spec_sha256": spec_sha, "operating_sha256": digest(STATE["operating"]), "target_id": target["target_id"],
           "source_sha256": pixels.sha256, "exposure_days": exposure_days(pixels), "truth": truth, "cases": cases}
    write_record(path, row)
    return row


def run_role(spec, spec_sha, role, targets, operating=None):
    output = ROOT / spec["config"]["output"] / role
    output.mkdir(exist_ok=True)
    worker = calibration_target if role == "calibration" else evaluation_target
    rows = []
    with ProcessPoolExecutor(max_workers=spec["config"]["workers"], mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize, initargs=(spec, spec_sha, operating)) as pool:
        futures = [pool.submit(worker, target) for target in targets]
        for future in as_completed(futures):
            rows.append(future.result())
            print(json.dumps({"stage": role, "completed": len(rows), "registered": len(targets)}), flush=True)
    return sorted(rows, key=lambda r: int(r["target_id"]))


def recovery_rows(results):
    rows = []
    for result in results:
        truth = result["truth"]
        centers, tolerance = truth["observed_centers_btjd"], truth["duration_hours"] / 48
        for method in METHODS:
            detected = result["cases"]["injected"][method]["centers_btjd"]
            original = result["cases"]["original"][method]["centers_btjd"]
            matches = set(matched_indices(detected, centers, tolerance))
            prior = set(matched_indices(original, centers, tolerance))
            incremental = matches - prior
            rows.append({"target_id": result["target_id"], "method": method, "mode": truth["mode"], "depth": truth["depth"],
                         "exposure_days": result["exposure_days"], "injected_events": len(centers),
                         "matched_events": len(matches), "original_matches": len(prior), "any_match": bool(matches),
                         "incremental_events": len(incremental), "incremental_recovery": bool(incremental),
                         "pattern_recovery": bool(len(centers) >= 2 and len(matches) >= max(2, np.ceil(len(centers) / 2))
                                             and len(matches) >= .5 * len(detected)),
                         "inverted_alerts": len(result["cases"]["inverted"][method]["centers_btjd"]),
                         "original_alerts": len(original)})
    return rows


def finish(results, spec, spec_sha, operating, output):
    rows = recovery_rows(results)
    pd.DataFrame(rows).to_csv(output / "host_recovery.csv", index=False)
    methods = {m: summarize_rows([r for r in rows if r["method"] == m]) for m in METHODS}
    summary = {"status": "complete", "version": VERSION, "spec_sha256": spec_sha, "completed_at": utc_now(),
               "registered_hosts": len(results), "observable_hosts": sum(bool(r["truth"]["observed_centers_btjd"]) for r in results),
               "methods": methods, "operating_sha256": digest(operating),
               "by_mode": {mode: {m: summarize_rows([r for r in rows if r["method"] == m and r["mode"] == mode])
                                    for m in METHODS} for mode in spec["physical_config"]["modes"]},
               "by_depth": {str(depth): {m: summarize_rows([r for r in rows if r["method"] == m and r["depth"] == depth])
                                    for m in METHODS} for depth in spec["physical_config"]["depths"]},
               "paired": {}, "claims": {"fresh_host_evaluation": True, "classifier_validation": False, "deployed": False,
                    "hybrid_within_control_budget": methods["hybrid"]["inverted_alerts_per_27_days"] <= spec["config"]["control_budget_per_27_days"]}}
    original = {r["target_id"]: r for r in rows if r["method"] == "v3_original"}
    for method in METHODS[1:]:
        other = [r for r in rows if r["method"] == method]
        wins = sum(r["incremental_recovery"] and not original[r["target_id"]]["incremental_recovery"] for r in other)
        losses = sum(original[r["target_id"]]["incremental_recovery"] and not r["incremental_recovery"] for r in other)
        summary["paired"][method] = {"new_only": wins, "original_only": losses,
            "mcnemar_exact_p": float(binomtest(wins, wins + losses).pvalue) if wins + losses else 1., "multiplicity_adjusted": False}
    atomic_json(output / "summary.json", summary)
    lines = ["# Fresh-host recovery experiment", "", f"{len(results)} registered hosts; {summary['observable_hosts']} with observable physical injections.",
             "All thresholds froze on 78 separate calibration hosts before evaluation. v3 weights are unchanged.",
             "The new hybrid supplements v3 with a duration-aware single-event search. It is an experimental detector, not a new trained neural model.", "",
             "| Method | Incremental hosts | Incremental events | Inverted alerts / 27 d |", "| --- | ---: | ---: | ---: |"]
    for method, row in methods.items():
        lines.append(f"| {method} | {row['incremental_hosts']}/{len(results)} | {row['incremental_events']}/{row['injected_events']} | {row['inverted_alerts_per_27_days']:.3f} |")
    lines += ["", "## Calibration", "", "| Search | Threshold | Calibration alerts / 27 d | Conservative upper estimate |", "| --- | ---: | ---: | ---: |"]
    for name, item in operating.items():
        if isinstance(item, dict) and "selected_threshold" in item:
            selected = item["selected"]
            lines.append(f"| {name} | {item['selected_threshold']:.8g} | {selected['events_per_27_days']:.3f} | {selected['conservative_upper']:.3f} |")
    for factor in ("by_mode", "by_depth"):
        lines += ["", f"## {factor.replace('_', ' ')}", "", "| Factor | " + " | ".join(METHODS) + " |", "| --- | " + " | ".join(["---:"] * len(METHODS)) + " |"]
        for value, data in summary[factor].items():
            lines.append("| " + value + " | " + " | ".join(f"{data[m]['incremental_hosts']}/{data[m]['registered_hosts']}" for m in METHODS) + " |")
    lines += ["", "The inverted-control rate is an alert diagnostic, not a survey false-positive rate. Calibration uses a 50% margin plus Poisson and host-bootstrap upper estimates; these do not guarantee performance under distribution shift.",
              "Physical injections retain the earlier circular-orbit, synthetic-density, fixed limb-darkening and empirical-PSF assumptions. No background-source or binary rejection is established.",
              "All registered hosts remain in denominators. Original-curve matches are subtracted before crediting one-to-one injection recovery.",
              "This experiment does not validate the candidate classifier or justify deployment. See summary.json for paired comparisons; p-values are unadjusted.", ""]
    (output / "report.md").write_text("\n".join(lines))
    files = {str(p.relative_to(output)): file_sha256(p) for p in output.rglob("*") if p.is_file() and p.name != "complete.json"}
    atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(), "files": files})
    print(json.dumps({"stage": "complete", "methods": methods}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_recovery_v1.json")
    parser.add_argument("--stage", choices=("prepare", "calibrate", "evaluate", "all"), default="all")
    args = parser.parse_args()
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    spec, spec_sha, output = prepare(config, config_path)
    if (output / "complete.json").exists():
        _checked_complete(output)
        print(json.dumps({"stage": "already_complete", "output": config["output"]}))
        return
    if args.stage == "prepare":
        print(json.dumps({"stage": "prepared", "spec_sha256": spec_sha}))
        return
    op_path = output / "operating_point.json"
    if op_path.exists():
        operating = checked_record(op_path, spec_sha)
    else:
        if args.stage == "evaluate":
            raise ValueError("Calibration has not completed")
        rows = run_role(spec, spec_sha, "calibration", spec["calibration_targets"])
        operating = calibrate(rows, spec, spec_sha)
        write_record(op_path, operating)
        print(json.dumps({"stage": "thresholds_frozen", "thresholds": {k: v["selected_threshold"] for k, v in operating.items() if isinstance(v, dict) and "selected_threshold" in v}}), flush=True)
    if args.stage == "calibrate":
        return
    acquired = json.loads((ROOT / config["cohort_run"] / "acquired.json").read_text())
    cohort = json.loads((ROOT / config["cohort_run"] / "manifest.json").read_text())
    if acquired["cohort_sha256"] != digest(cohort):
        raise ValueError("Acquisition is not bound to frozen cohort")
    targets = acquired["targets"]
    if sorted(t["target_id"] for t in targets) != sorted(t["target_id"] for t in spec["evaluation_targets"]):
        raise ValueError("Acquisition dropped or duplicated registered hosts")
    results = run_role(spec, spec_sha, "evaluation", targets, operating)
    finish(results, spec, spec_sha, operating, output)


if __name__ == "__main__":
    main()
