#!/usr/bin/env python3
"""Blindly slide the four-view event localizer over the cached TESS cohort."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import torch

from scripts.experiments.ai_telescope import center_crop_or_pad, normalize_target
from scripts.experiments.ai_telescope_v2 import (CONTEXT_FEATURES, context_vector,
                                                 normalize_instrument)
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.detection import phase_distance
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_blind_sliding_scan_v1"
FIELDS = {"schema_version", "model_run", "physical_run", "output", "window_length",
          "pixel_frames", "spatial_size", "stride", "batch_size",
          "maximum_events_per_target", "top_unmatched", "merge_gap_cadences",
          "minimum_event_cadences", "cpu_threads"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("Blind-scan configuration differs from schema")
    for key in ("model_run", "physical_run", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Blind-scan paths must remain inside the project")
    for key, low, high in (
        ("window_length", 64, 2048), ("pixel_frames", 8, 128),
        ("spatial_size", 7, 31), ("stride", 16, 2048), ("batch_size", 1, 128),
        ("maximum_events_per_target", 1, 100), ("top_unmatched", 1, 10000),
        ("merge_gap_cadences", 0, 16), ("minimum_event_cadences", 1, 32),
        ("cpu_threads", 1, 8)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    if value["window_length"] % value["pixel_frames"] or value["spatial_size"] % 2 != 1:
        raise ValueError("Window length must divide into pixel frames and spatial size must be odd")
    if value["stride"] > value["window_length"]:
        raise ValueError("Blind-scan stride cannot leave cadence gaps")
    return value


def scan_starts(length, window_length, stride):
    if length < window_length:
        return []
    starts = list(range(0, length - window_length + 1, stride))
    final = length - window_length
    if starts[-1] != final:
        starts.append(final)
    return starts


def group_events(score, valid, threshold, merge_gap, minimum_cadences):
    selected = np.flatnonzero(valid & np.isfinite(score) & (score >= threshold))
    if not len(selected):
        return []
    blocks = np.split(selected, np.flatnonzero(np.diff(selected) > merge_gap + 1) + 1)
    output = []
    for block in blocks:
        above = block[score[block] >= threshold]
        if len(above) < minimum_cadences:
            continue
        peak = int(above[np.argmax(score[above])])
        output.append({"start_index": int(block[0]), "end_index": int(block[-1]),
                       "peak_index": peak, "cadences_above_threshold": int(len(above)),
                       "max_probability": float(score[peak]),
                       "mean_probability": float(np.mean(score[above]))})
    return output


def _checked_complete(path):
    receipt = json.loads((path / "complete.json").read_text())
    if receipt.get("status") != "complete":
        raise ValueError("Incomplete source run: " + str(path))
    for name, checksum in receipt["files"].items():
        if file_sha256(path / name) != checksum:
            raise ValueError("Source-run checksum mismatch: " + str(path / name))
    return receipt


def _context(context, stats):
    raw = context_vector(context)
    center = np.asarray(stats["center"], dtype=np.float32)
    scale = np.asarray(stats["scale"], dtype=np.float32)
    if raw.shape != center.shape or list(stats["features"]) != list(CONTEXT_FEATURES):
        raise ValueError("Context normalization contract changed")
    available = np.isfinite(raw)
    standardized = np.clip((raw - center) / scale, -10, 10)
    standardized[~available] = 0
    return np.concatenate([standardized, available.astype(np.float32)]).astype(np.float32)


def _pixel_window(cube, valid, start, config):
    stop = start + config["window_length"]
    stride = config["window_length"] // config["pixel_frames"]
    chosen = start + np.arange(config["pixel_frames"]) * stride + stride // 2
    frames = cube[chosen]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        reference = np.nanmedian(cube[start:stop][valid[start:stop]], axis=0)
    finite_reference = np.abs(reference[np.isfinite(reference)])
    floor = float(np.median(finite_reference)) * 1e-3 + 1e-6 if len(finite_reference) else 1.
    denominator = np.maximum(np.abs(reference), floor)
    residual = np.clip((frames - reference) / denominator, -.25, .25) / .05
    residual[~np.isfinite(residual)] = 0
    return center_crop_or_pad(residual.astype(np.float32), config["spatial_size"])


def infer_target(model, pixels, context, config):
    cube, light, valid, _ = normalize_target(pixels, [])
    instrument = normalize_instrument(pixels)
    starts = scan_starts(len(light), config["window_length"], config["stride"])
    probability_sum = np.zeros(len(light), dtype=np.float64)
    prediction_count = np.zeros(len(light), dtype=np.int32)
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(starts), config["batch_size"]):
            batch_starts = starts[offset:offset + config["batch_size"]]
            flux_batch = np.stack([light[x:x + config["window_length"]] for x in batch_starts])
            valid_batch = np.stack([valid[x:x + config["window_length"]] for x in batch_starts])
            pixel_batch = np.stack([_pixel_window(cube, valid, x, config) for x in batch_starts])
            instrument_batch = np.stack([
                instrument[:, x:x + config["window_length"]] for x in batch_starts])
            context_batch = np.repeat(context[None, :], len(batch_starts), axis=0)
            logits = model(torch.from_numpy(flux_batch.astype(np.float32)),
                           torch.from_numpy(valid_batch.astype(np.float32)),
                           torch.from_numpy(pixel_batch.astype(np.float32)),
                           torch.from_numpy(instrument_batch.astype(np.float32)),
                           torch.from_numpy(context_batch.astype(np.float32)))
            probabilities = torch.sigmoid(logits).numpy()
            for start, values in zip(batch_starts, probabilities):
                stop = start + config["window_length"]
                probability_sum[start:stop] += values
                prediction_count[start:stop] += 1
    score = np.full(len(light), np.nan, dtype=np.float32)
    use = prediction_count > 0
    score[use] = (probability_sum[use] / prediction_count[use]).astype(np.float32)
    return score, valid, starts


def _candidate_match(time, peak, candidate):
    period = float(candidate["period_days"])
    epoch = float(candidate["epoch_bjd_tdb"]) - 2457000.
    duration = float(candidate["duration_hours"]) / 24
    return abs(float(phase_distance(np.asarray([time[peak]]), period, epoch)[0])) <= duration


def annotate_events(events, time, candidates):
    output = []
    for event in events:
        matches = [candidate for candidate in candidates if _candidate_match(
            time, event["peak_index"], candidate)]
        row = {**event,
               "start_btjd": float(time[event["start_index"]]),
               "end_btjd": float(time[event["end_index"]]),
               "peak_btjd": float(time[event["peak_index"]]),
               "matched_candidate_ids": [x["candidate_id"] for x in matches],
               "matched_labels": [int(x["label"]) for x in matches]}
        row["review_score"] = float(row["max_probability"]
                                    * math.log1p(row["cadences_above_threshold"]))
        output.append(row)
    return output


def scan_target(model, target, tpf_path, context_stats, threshold, config):
    pixels = read_target_pixels(tpf_path, target["target_id"])
    score, valid, starts = infer_target(model, pixels, _context(pixels.context, context_stats), config)
    events = annotate_events(group_events(score, valid, threshold,
                                           config["merge_gap_cadences"],
                                           config["minimum_event_cadences"]),
                             pixels.time, target["candidates"])
    recovered = {candidate["candidate_id"]: False for candidate in target["candidates"]}
    for event in events:
        for candidate_id in event["matched_candidate_ids"]:
            recovered[candidate_id] = True
    ranked = sorted(events, key=lambda x: (-x["review_score"], -x["max_probability"]))
    kept = ranked[:config["maximum_events_per_target"]]
    return {"status": "complete", "version": VERSION, "target_id": str(target["target_id"]),
            "sector": int(target["sector"]), "source_sha256": pixels.sha256,
            "windows_scanned": len(starts), "cadences": len(pixels.time),
            "valid_cadences": int(valid.sum()), "events_before_cap": len(events),
            "events": kept, "catalog_recovery": recovered}


def _write_csv(path, frame):
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def aggregate(results, cohort_by_id, config, threshold, output):
    event_rows, recovery_rows = [], []
    total_windows = total_cadences = total_valid = total_before_cap = 0
    for result in results:
        target = cohort_by_id[result["target_id"]]
        total_windows += result["windows_scanned"]
        total_cadences += result["cadences"]
        total_valid += result["valid_cadences"]
        total_before_cap += result["events_before_cap"]
        for event in result["events"]:
            event_rows.append({"target_id": result["target_id"], "sector": result["sector"],
                               "role": target["candidates"][0]["role"], **event})
        for candidate in target["candidates"]:
            recovery_rows.append({"target_id": result["target_id"],
                                  "candidate_id": candidate["candidate_id"],
                                  "role": candidate["role"], "label": int(candidate["label"]),
                                  "recovered": bool(result["catalog_recovery"][candidate["candidate_id"]])})
    events = pd.DataFrame(event_rows)
    recovery = pd.DataFrame(recovery_rows)
    if len(events):
        events["matched"] = events["matched_candidate_ids"].map(bool)
        unmatched = events[~events["matched"]].nlargest(config["top_unmatched"], "review_score")
    else:
        unmatched = events.copy()
    _write_csv(output / "events.csv", events)
    _write_csv(output / "unmatched_review_queue.csv", unmatched)
    _write_csv(output / "catalog_recovery.csv", recovery)
    by_role = {role: {"candidates": int(len(part)), "recovered": int(part.recovered.sum()),
                      "recall": float(part.recovered.mean()) if len(part) else None}
               for role, part in recovery.groupby("role")}
    by_label = {str(int(label)): {"candidates": int(len(part)), "recovered": int(part.recovered.sum()),
                                  "recall": float(part.recovered.mean()) if len(part) else None}
                for label, part in recovery.groupby("label")}
    return {"status": "complete", "version": VERSION, "completed_at": utc_now(),
            "scope": {"targets": len(results), "windows_scanned": total_windows,
                      "cadences": total_cadences, "valid_cadences": total_valid,
                      "events_before_per_target_cap": total_before_cap,
                      "events_saved": int(len(events)), "unmatched_review_queue": int(len(unmatched))},
            "threshold": {"value": threshold, "source": "context_v2_calibration_hosts",
                          "aggregation": "mean_probability_across_overlapping_windows"},
            "catalog_ephemeris_recovery": {"overall": {"candidates": int(len(recovery)),
                "recovered": int(recovery.recovered.sum()),
                "recall": float(recovery.recovered.mean()) if len(recovery) else None},
                "by_role": by_role, "by_label": by_label},
            "top_unmatched": unmatched.head(20).to_dict("records"),
            "claims": {"window_placement_is_ephemeris_blind": True,
                       "catalog_ephemerides_used_only_for_post_inference_matching": True,
                       "prospective_planet_discovery": False, "planet_probability": False,
                       "deployed_to_watcher": False},
            "limitations": [
                "The cohort is candidate-enriched and covers one cached SPOC sector per target",
                "The threshold was calibrated on centered windows, not on continuous sliding-window scores",
                "Averaging overlapping-window probabilities changes the score distribution",
                "Unmatched events can be stellar variability or instrument artifacts and require vetting",
                "Catalog recovery measures known periodic signal recovery, not confirmed-planet recall",
            ]}


def write_report(path, summary):
    recovery = summary["catalog_ephemeris_recovery"]["overall"]
    scope = summary["scope"]
    lines = ["# Ephemeris-blind sliding-window scan", "",
             "The frozen four-view localizer scanned regularly spaced windows. Catalog ephemerides "
             "were withheld until after inference and used only to label recovered versus unmatched events.", "",
             f"- Targets: **{scope['targets']}**",
             f"- Windows scanned: **{scope['windows_scanned']}**",
             f"- Valid cadences scored: **{scope['valid_cadences']}**",
             f"- Known catalog signals recovered: **{recovery['recovered']}/{recovery['candidates']}** "
             f"({recovery['recall']:.1%})",
             f"- Unmatched events queued for review: **{scope['unmatched_review_queue']}**",
             "", "## Boundaries", "", *["- " + x for x in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_blind_scan_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    torch.set_num_threads(config["cpu_threads"])
    model_run, physical = ROOT / config["model_run"], ROOT / config["physical_run"]
    model_complete, physical_complete = _checked_complete(model_run), _checked_complete(physical)
    model_config = json.loads((model_run / "spec.json").read_text())["config"]
    if (config["window_length"] != 256 or config["pixel_frames"] != 32
            or config["spatial_size"] != 11):
        raise ValueError("Blind scan must preserve the trained window geometry")
    checkpoint = torch.load(model_run / "ai_telescope_context.pt",
                            map_location="cpu", weights_only=True)
    context_stats = json.loads((model_run / "context_stats.json").read_text())
    context_dim = len(context_stats["features"]) * 2
    model = ExtendedEventLocalizer(context_dim, model_config["embedding_dim"],
                                   model_config["instrument_channels"])
    model.load_state_dict(checkpoint["localizer"]); model.eval()
    threshold = float(checkpoint["threshold"]["threshold"])
    if not 0 < threshold < 1:
        raise ValueError("Frozen model threshold is invalid")
    cohort = json.loads((physical / "cohort.json").read_text())
    plan = json.loads((physical / "download_plan.json").read_text())
    products = {str(x["target_id"]): x for x in plan["products"]}
    with np.load(model_run / "dataset.npz", allow_pickle=False) as saved:
        included = set(saved["target_id"].astype(str).tolist())
    targets = [x for x in cohort["targets"] if str(x["target_id"]) in included]
    cohort_by_id = {str(x["target_id"]): x for x in targets}
    source_hashes = {}
    for receipt_path in (model_run / "auxiliary").glob("TIC*.json"):
        receipt = json.loads(receipt_path.read_text())
        source_hashes[str(receipt["target_id"])] = receipt["source_sha256"]
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/ai_telescope_blind_scan.py",
               "scripts/experiments/ai_telescope_v2.py", "training/ai_telescope.py",
               "scripts/research/pixels.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "model_spec_sha256": model_complete["spec_sha256"],
            "physical_spec_sha256": physical_complete["spec_sha256"],
            "threshold": threshold,
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.is_file() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing blind-scan output uses a different specification")
    if (output / "complete.json").is_file():
        raise ValueError("Blind scan is already complete")
    atomic_json(spec_path, spec)
    cache = output / "targets"; cache.mkdir(parents=True, exist_ok=True)
    results, failures = [], []
    for number, target in enumerate(targets, 1):
        target_id = str(target["target_id"]); result_path = cache / ("TIC" + target_id + ".json")
        try:
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                if (result.get("spec_sha256") != spec_sha
                        or result.get("source_sha256") != source_hashes.get(target_id)
                        or result.get("status") != "complete"):
                    raise ValueError("Cached blind-scan target receipt mismatch")
            else:
                product = products[target_id]
                tpf_path = ROOT / "data/raw/tess/target_pixels" / ("TIC" + target_id) / product["filename"]
                result = scan_target(model, target, tpf_path, context_stats, threshold, config)
                if result["source_sha256"] != source_hashes.get(target_id):
                    raise ValueError("TPF checksum changed since context-v2 extraction")
                result["spec_sha256"] = spec_sha
                atomic_json(result_path, result)
            results.append(result)
        except Exception as exc:
            failures.append({"target_id": target_id, "type": type(exc).__name__, "reason": str(exc)})
        if number % 10 == 0 or number == len(targets):
            print(json.dumps({"stage": "blind_scan", "processed": number, "targets": len(targets),
                              "complete": len(results), "failures": len(failures)}), flush=True)
    if failures or len(results) != len(targets):
        atomic_json(output / "failures.json", {"status": "incomplete", "failures": failures})
        raise ValueError("Blind scan requires every context-v2 target")
    summary = aggregate(results, cohort_by_id, config, threshold, output)
    summary["spec_sha256"] = spec_sha
    atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "summary.json", "report.md", "events.csv",
              "unmatched_review_queue.csv", "catalog_recovery.csv")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files,
                                            "target_receipts": {str(p.relative_to(ROOT)): file_sha256(p)
                                                                for p in cache.glob("TIC*.json")}})
    print(json.dumps({"status": "complete", "scope": summary["scope"],
                      "catalog_recovery": summary["catalog_ephemeris_recovery"],
                      "claims": summary["claims"]}, indent=2))


if __name__ == "__main__":
    main()
