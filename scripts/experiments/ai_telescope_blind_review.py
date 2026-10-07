#!/usr/bin/env python3
"""Triage blind-scan events with duration, common-mode and known-secondary checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.detection import phase_distance
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "ai_telescope_blind_review_v1"
FIELDS = {"schema_version", "scan_run", "physical_run", "output",
          "duration_lower_quantile", "duration_upper_quantile",
          "common_mode_window_days", "maximum_common_mode_targets", "top_events"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("Blind-review configuration differs from schema")
    for key in ("scan_run", "physical_run", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Blind-review paths must remain inside the project")
    for key in ("duration_lower_quantile", "duration_upper_quantile",
                "common_mode_window_days"):
        item = value[key]
        if type(item) not in (int, float) or not math.isfinite(item):
            raise ValueError("Invalid " + key)
    if not 0 <= value["duration_lower_quantile"] < value["duration_upper_quantile"] <= 1:
        raise ValueError("Invalid duration quantiles")
    if not 0 < value["common_mode_window_days"] <= 1:
        raise ValueError("Invalid common-mode window")
    for key, low, high in (("maximum_common_mode_targets", 1, 100), ("top_events", 1, 10000)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    return value


def common_mode_counts(sector, time, window_days):
    sector, time = np.asarray(sector), np.asarray(time, dtype=float)
    output = np.ones(len(time), dtype=np.int32)
    for value in np.unique(sector):
        indices = np.flatnonzero(sector == value)
        order = indices[np.argsort(time[indices])]
        ordered_time = time[order]
        left = np.searchsorted(ordered_time, ordered_time - window_days, side="left")
        right = np.searchsorted(ordered_time, ordered_time + window_days, side="right")
        output[order] = right - left
    return output


def known_secondary(event_time, candidates):
    matches = []
    for candidate in candidates:
        period = float(candidate["period_days"])
        epoch = float(candidate["epoch_bjd_tdb"]) - 2457000.
        duration = float(candidate["duration_hours"]) / 24
        distance = abs(float(phase_distance(np.asarray([event_time]), period, epoch)[0]))
        if abs(distance - period / 2) <= duration:
            matches.append(candidate["candidate_id"])
    return matches


def duration_prior(values, training_durations, lower_quantile, upper_quantile):
    training = np.asarray(training_durations, dtype=float)
    lower, upper = np.quantile(training, [lower_quantile, upper_quantile])
    logged = np.log(training)
    center = float(np.median(logged))
    scale = 1.4826 * float(np.median(np.abs(logged - center)))
    scale = max(scale, 1e-6)
    values = np.asarray(values, dtype=float)
    score = np.exp(-.5 * ((np.log(np.maximum(values, 1e-6)) - center) / scale) ** 2)
    return score, float(lower), float(upper), center, scale


def _complete(path):
    receipt = json.loads((path / "complete.json").read_text())
    if receipt.get("status") != "complete":
        raise ValueError("Incomplete source run: " + str(path))
    for name, checksum in receipt["files"].items():
        if file_sha256(path / name) != checksum:
            raise ValueError("Source checksum mismatch: " + name)
    return receipt


def write_report(path, summary):
    counts = summary["counts"]
    lines = ["# Blind-event scientific review queue", "",
             "This post-inference triage removes implausibly long/short segments, known secondary "
             "eclipses and events shared by several targets at the same spacecraft time.", "",
             f"- Unmatched scan events: **{counts['unmatched_input']}**",
             f"- Transit-duration events: **{counts['transit_duration']}**",
             f"- After secondary/common-mode checks: **{counts['reviewable']}**",
             f"- Audit-host review queue: **{counts['audit_review_queue']}**",
             "", "These are review targets, not planet candidates or probabilities.", "",
             "## Boundaries", "", *["- " + x for x in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_blind_review_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    scan, physical = ROOT / config["scan_run"], ROOT / config["physical_run"]
    scan_complete, physical_complete = _complete(scan), _complete(physical)
    cohort = json.loads((physical / "cohort.json").read_text())
    cohort_by_id = {str(x["target_id"]): x for x in cohort["targets"]}
    events = pd.read_csv(scan / "events.csv")
    if not {"target_id", "sector", "role", "peak_btjd", "start_btjd", "end_btjd",
            "max_probability", "mean_probability", "matched"}.issubset(events.columns):
        raise ValueError("Blind-scan event table changed schema")
    events["target_id"] = events["target_id"].astype(str)
    unmatched = events[~events["matched"].astype(bool)].copy()
    unmatched["duration_hours"] = (unmatched["end_btjd"] - unmatched["start_btjd"]) * 24
    training_durations = [float(candidate["duration_hours"])
                          for target in cohort["targets"] for candidate in target["candidates"]
                          if candidate["role"] == "train"]
    prior, lower, upper, log_center, log_scale = duration_prior(
        unmatched["duration_hours"], training_durations,
        config["duration_lower_quantile"], config["duration_upper_quantile"])
    unmatched["duration_prior"] = prior
    unmatched["common_mode_target_count"] = common_mode_counts(
        unmatched["sector"].to_numpy(), unmatched["peak_btjd"].to_numpy(),
        config["common_mode_window_days"])
    unmatched["known_secondary_ids"] = [known_secondary(
        row.peak_btjd, cohort_by_id[str(row.target_id)]["candidates"])
        for row in unmatched.itertuples()]
    unmatched["known_secondary"] = unmatched["known_secondary_ids"].map(bool)
    unmatched["target_detected_event_count"] = unmatched.groupby("target_id")["target_id"].transform("size")
    unmatched["scientific_review_score"] = (
        unmatched["max_probability"] * unmatched["mean_probability"]
        * unmatched["duration_prior"] / np.sqrt(unmatched["common_mode_target_count"]))
    duration_use = unmatched["duration_hours"].between(lower, upper, inclusive="both")
    common_use = unmatched["common_mode_target_count"] <= config["maximum_common_mode_targets"]
    reviewable = unmatched[duration_use & common_use & ~unmatched["known_secondary"]].copy()
    reviewable.sort_values("scientific_review_score", ascending=False, inplace=True)
    overall_queue = reviewable.head(config["top_events"])
    audit_queue = reviewable[reviewable["role"] == "audit"].head(config["top_events"])
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/ai_telescope_blind_review.py",)
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "scan_spec_sha256": scan_complete["spec_sha256"],
            "physical_spec_sha256": physical_complete["spec_sha256"],
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    if (output / "complete.json").is_file():
        raise ValueError("Blind-event review is already complete")
    for name, frame in (("transit_like_review_queue.csv", overall_queue),
                        ("audit_review_queue.csv", audit_queue),
                        ("reviewed_unmatched_events.csv", unmatched)):
        frame.to_csv(output / name, index=False)
    summary = {"status": "complete", "version": VERSION, "completed_at": utc_now(),
               "spec_sha256": spec_sha,
               "duration_prior": {"fit_scope": "train_role_catalog_durations_only",
                                  "lower_hours": lower, "upper_hours": upper,
                                  "log_center": log_center, "log_robust_scale": log_scale},
               "common_mode": {"window_days": config["common_mode_window_days"],
                               "maximum_targets": config["maximum_common_mode_targets"]},
               "counts": {"unmatched_input": int(len(unmatched)),
                          "transit_duration": int(duration_use.sum()),
                          "known_secondary": int(unmatched["known_secondary"].sum()),
                          "common_mode_rejected": int((~common_use).sum()),
                          "reviewable": int(len(reviewable)),
                          "overall_review_queue": int(len(overall_queue)),
                          "audit_review_queue": int(len(audit_queue))},
               "top_overall": overall_queue.head(20).to_dict("records"),
               "top_audit": audit_queue.head(20).to_dict("records"),
               "claims": {"planet_probability": False, "planet_candidate": False,
                          "prospective_confirmation": False, "deployed_to_watcher": False},
               "limitations": [
                   "The input cohort is candidate-enriched and validation-derived",
                   "The duration prior is learned from catalog signals and can down-rank unusual planets",
                   "Common-mode rejection uses only targets present in this cohort, not the full TESS field",
                   "Known-primary matching inherits the scan tolerance and ephemeris quality",
                   "Every queued event still requires pixel, catalog, variability and registry vetting",
               ]}
    atomic_json(output / "spec.json", spec); atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "transit_like_review_queue.csv",
              "audit_review_queue.csv", "reviewed_unmatched_events.csv")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "counts": summary["counts"],
                      "top_audit": summary["top_audit"][:5]}, indent=2))


if __name__ == "__main__":
    main()
