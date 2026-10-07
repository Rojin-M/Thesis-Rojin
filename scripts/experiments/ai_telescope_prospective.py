"""Freeze and blindly scan the unreviewed remainder of the 100-host cohort."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests
import torch

from scripts.experiments.ai_telescope_blind_review import _complete
from scripts.experiments.ai_telescope_blind_scan import scan_target, validate_config as scan_config
from scripts.experiments.mission_adaptation import atomic_json
from scripts.experiments.tls_pixel_pilot import _download, _head
from scripts.research.pixels import MAX_TPF_BYTES
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_frozen_unreviewed_hosts_v1"
FIELDS = {"schema_version", "cohort_run", "prior_pixel_run", "model_run", "scan_config", "review_run",
          "output", "target_pixel_root", "receipt_root", "max_product_bytes", "max_total_download_bytes"}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != FIELDS or config["schema_version"] != 1:
        raise ValueError("Prospective config differs from schema")
    for key in FIELDS - {"schema_version", "max_product_bytes", "max_total_download_bytes"}:
        path = Path(config[key])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Prospective paths must stay within project")
    if (type(config["max_product_bytes"]) is not int or not 1 <= config["max_product_bytes"] <= MAX_TPF_BYTES
            or type(config["max_total_download_bytes"]) is not int
            or not config["max_product_bytes"] <= config["max_total_download_bytes"] <= 32 * 1024**3):
        raise ValueError("Invalid prospective download limits")
    return config


def select_unreviewed(targets, prior_ids, exposed_ids):
    ids = [str(t["target_id"]) for t in targets]
    if len(set(ids)) != len(ids) or not set(prior_ids).issubset(ids):
        raise ValueError("Invalid original/prior cohort membership")
    if set(ids) & set(exposed_ids):
        raise ValueError("Prospective cohort overlaps model-development hosts")
    # Preserve original frozen ordering. Prior review is an exposure exclusion,
    # never a cut on a model score or catalog outcome. No replacement hosts.
    return [t for t in targets if str(t["target_id"]) not in set(prior_ids)]


def prepare(config, config_path):
    receipts = {key: _complete(ROOT / config[key]) for key in ("cohort_run", "prior_pixel_run", "model_run", "review_run")}
    manifest = json.loads((ROOT / config["cohort_run"] / "manifest.json").read_text())
    previous = json.loads((ROOT / config["prior_pixel_run"] / "spec.json").read_text())["selected_targets"]
    model_spec = json.loads((ROOT / config["model_run"] / "spec.json").read_text())
    physical = ROOT / model_spec["config"]["physical_run"]
    _complete(physical)
    development = {str(t["target_id"]) for t in json.loads((physical / "cohort.json").read_text())["targets"]}
    shared_path = ROOT / "data/processed/tess/shared_v1/manifest_tess_shared_v1.csv"
    shared = pd.read_csv(shared_path, dtype={"star_id": str})
    development |= {str(int(float(t))) for t in shared.star_id}
    targets = select_unreviewed(manifest["targets"], previous, development)
    if not targets:
        raise ValueError("No unreviewed hosts remain")
    for target in targets:
        if file_sha256(ROOT / target["product_path"]) != target["product_sha256"]:
            raise ValueError("Prospective light curve changed: " + target["target_id"])
    checkpoint = torch.load(ROOT / config["model_run"] / "ai_telescope_context.pt", map_location="cpu", weights_only=True)
    threshold = float(checkpoint["threshold"]["threshold"])
    if not 0 < threshold < 1:
        raise ValueError("Invalid frozen threshold")
    geometry = scan_config(json.loads((ROOT / config["scan_config"]).read_text()))
    if (geometry["window_length"], geometry["pixel_frames"], geometry["spatial_size"]) != (256, 32, 11):
        raise ValueError("Prospective geometry differs from trained model")
    sources = ("scripts/experiments/ai_telescope_prospective.py", "scripts/experiments/ai_telescope_blind_scan.py",
               "scripts/experiments/ai_telescope.py", "scripts/experiments/ai_telescope_v2.py",
               "scripts/experiments/tls_pixel_pilot.py", "scripts/research/pixels.py", "training/ai_telescope.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "input_receipts": {key: file_sha256(ROOT / config[key] / "complete.json") for key in receipts},
            "source_files": {name: file_sha256(ROOT / name) for name in sources},
            "shared_manifest_sha256": file_sha256(shared_path), "scan_config": geometry, "threshold": threshold,
            "original_cohort_hosts": len(manifest["targets"]), "previously_reviewed_excluded": previous,
            "selected_targets": targets, "model_development_overlap": 0,
            "policy": "All original frozen members except prior pixel pilot; no replacements, tuning, catalog access, or score-dependent membership changes"}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    spec_path = output / "spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Prospective run specification changed")
    atomic_json(spec_path, spec)
    return spec, spec_sha, output, model_spec, checkpoint


def archive_plan(spec, output):
    config = spec["config"]
    path = output / "download_plan.json"
    if path.exists():
        plan = json.loads(path.read_text())
        if plan["spec_sha256"] != hashlib.sha256(canonical_json(spec).encode()).hexdigest():
            raise ValueError("Download plan specification mismatch")
        return plan
    def head(target):
        with requests.Session() as session:
            session.headers["User-Agent"] = "Thesis-Rojin-prospective-telescope/1"
            for attempt in range(2):
                try:
                    return {**_head(session, target, config), "target_id": target["target_id"]}
                except (requests.RequestException, OSError):
                    if attempt:
                        raise
    with ThreadPoolExecutor(max_workers=4) as pool:
        products = list(pool.map(head, spec["selected_targets"]))
    total = sum(p["size_bytes"] for p in products)
    if total > config["max_total_download_bytes"]:
        raise ValueError("Frozen cohort exceeds total download limit; no data downloaded")
    plan = {"status": "planned", "planned_at": utc_now(), "products": products, "total_bytes": total,
            "spec_sha256": hashlib.sha256(canonical_json(spec).encode()).hexdigest()}
    atomic_json(path, plan)
    return plan


def summarize(results, failures, spec, spec_sha, output, new_bytes):
    rows = []
    duration = json.loads((ROOT / spec["config"]["review_run"] / "summary.json").read_text())["duration_prior"]
    for result in results:
        for event in result["events"]:
            hours = (event["end_btjd"] - event["start_btjd"]) * 24
            rows.append({"target_id": result["target_id"], "sector": result["sector"], **event,
                         "duration_hours": hours,
                         "within_frozen_duration_prior": duration["lower_hours"] <= hours <= duration["upper_hours"]})
    frame = pd.DataFrame(rows, columns=["target_id", "sector", "start_index", "end_index", "peak_index",
        "cadences_above_threshold", "max_probability", "mean_probability", "start_btjd", "end_btjd", "peak_btjd",
        "matched_candidate_ids", "matched_labels", "review_score", "duration_hours", "within_frozen_duration_prior"])
    frame.to_csv(output / "events.csv", index=False)
    frame[frame.within_frozen_duration_prior.astype(bool)].sort_values("review_score", ascending=False).to_csv(output / "review_queue.csv", index=False)
    counts = {"registered_hosts": len(spec["selected_targets"]), "completed_hosts": len(results),
              "failed_hosts": len(failures), "windows": sum(r["windows_scanned"] for r in results),
              "valid_cadences": sum(r["valid_cadences"] for r in results), "retained_events": len(frame),
              "events_before_per_host_cap": sum(r["events_before_cap"] for r in results),
              "within_frozen_duration_prior": int(frame.within_frozen_duration_prior.sum()),
              "hosts_with_retained_events": int(frame.target_id.nunique()), "new_download_bytes_this_invocation": new_bytes}
    summary = {"status": "complete" if not failures else "incomplete", "version": VERSION, "counts": counts,
        "spec_sha256": spec_sha, "threshold": spec["threshold"], "failures": failures,
        "claims": {"model_development_host_disjoint": True, "trained_on_this_cohort": False,
                   "new_planets": False, "survey_recall_measured": False, "false_alarm_rate_measured": False,
                   "prospective_performance_confirmed": False, "deployed_to_watcher": False}}
    atomic_json(output / "summary.json", summary)
    lines = ["# Frozen unseen-host AI-telescope scan", "",
        f"Scored {len(results)}/{len(spec['selected_targets'])} registered hosts with the frozen v2 model and threshold ({spec['threshold']:.6f}).",
        f"Excluded {len(spec['previously_reviewed_excluded'])} previously reviewed pixel-pilot hosts from the original {spec['original_cohort_hosts']}-host manifest; no replacements or score-dependent selection.",
        "", f"- Windows: {counts['windows']:,}", f"- Valid cadences: {counts['valid_cadences']:,}",
        f"- Retained events: {counts['retained_events']} (per-host cap {spec['scan_config']['maximum_events_per_target']})",
        f"- Within the previously frozen duration range: {counts['within_frozen_duration_prior']}",
        f"- Failed hosts, retained in denominator: {counts['failed_hosts']}",
        "", "## Interpretation", "",
        "This demonstrates execution on hosts disjoint from model development. Event labels and catalog ephemerides were not accessed during this run. It does not measure accuracy, recall, false-alarm rate, or discovery yield. Duration-compatible events are review targets, not planet candidates.",
        "", "The cohort is an archival sample of cached TESS targets, not a random sky survey. Only one sector per host is scanned. The original model threshold came from centered windows; continuous-scan calibration remains outstanding. Earlier reviews of the separate 10-host subset are disclosed in spec.json.",
        "", "[Review queue](review_queue.csv), [all retained events](events.csv), and [frozen specification](spec.json)."]
    (output / "report.md").write_text("\n".join(lines)+"\n")
    if not failures:
        files = {name: file_sha256(output/name) for name in ("spec.json", "download_plan.json", "summary.json", "report.md", "events.csv", "review_queue.csv")}
        files.update({str(p.relative_to(output)): file_sha256(p) for p in (output/"targets").glob("*.json")})
        atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(), "files": files})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_prospective_v1.json")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    spec, spec_sha, output, model_spec, checkpoint = prepare(config, config_path)
    if (output / "complete.json").exists():
        _complete(output); print(json.dumps({"status": "already_complete"})); return
    plan = archive_plan(spec, output)
    print(json.dumps({"stage": "frozen", "hosts": len(spec["selected_targets"]),
                      "archive_bytes": plan["total_bytes"], "spec_sha256": spec_sha}), flush=True)
    if args.prepare_only:
        return
    torch.set_num_threads(spec["scan_config"]["cpu_threads"])
    stats = json.loads((ROOT / config["model_run"] / "context_stats.json").read_text())
    model = ExtendedEventLocalizer(len(stats["features"])*2, model_spec["config"]["embedding_dim"], model_spec["config"]["instrument_channels"])
    model.load_state_dict(checkpoint["localizer"]); model.eval()
    cache = output / "targets"; cache.mkdir(exist_ok=True)
    products = {p["target_id"]: p for p in plan["products"]}
    results, failures, new_bytes = [], [], 0
    with requests.Session() as session:
        session.headers["User-Agent"] = "Thesis-Rojin-prospective-telescope/1"
        for target in spec["selected_targets"]:
            began = time.monotonic(); tic = target["target_id"]
            path = cache / ("TIC"+tic+".json")
            try:
                product = products[tic]
                tpf, receipt, downloaded = _download(session, product, target, config)
                if downloaded:
                    new_bytes += receipt["size_bytes"]
                if path.exists():
                    result = json.loads(path.read_text())
                    if result.get("spec_sha256") != spec_sha or result.get("source_sha256") != receipt["sha256"]:
                        raise ValueError("Prospective target cache mismatch")
                else:
                    result = scan_target(model, {"target_id": tic, "sector": product["sector"], "candidates": []},
                                         tpf, stats, spec["threshold"], spec["scan_config"])
                    if result["source_sha256"] != receipt["sha256"]:
                        raise ValueError("Prospective TPF bytes differ from acquisition")
                    result.update(spec_sha256=spec_sha, completed_at=utc_now(), lightcurve_sha256=target["product_sha256"])
                    atomic_json(path, result)
                results.append(result)
                print(json.dumps({"stage": "prospective_scan", "complete": len(results), "target_id": tic,
                                  "events": len(result["events"]), "seconds": time.monotonic()-began}), flush=True)
            except Exception as exc:
                failures.append({"target_id": tic, "error": type(exc).__name__+": "+str(exc)})
                print(json.dumps({"stage": "target_failure", **failures[-1]}), flush=True)
    summary = summarize(results, failures, spec, spec_sha, output, new_bytes)
    print(json.dumps(summary, indent=2), flush=True)
    if failures:
        raise RuntimeError("Prospective run incomplete; preserve all registered hosts and retry failed acquisitions")


if __name__ == "__main__":
    main()
