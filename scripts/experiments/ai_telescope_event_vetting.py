"""Vet every frozen audit event with local pixels, public Gaia DR3 and BLS/TLS."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import multiprocessing
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from astropy.coordinates import SkyCoord

from scripts.experiments.ai_telescope_blind_review import _complete
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.detection import SearchConfig, search
from scripts.research.event_vetting import (GAIA_ENDPOINT, clean_json, gaia_query, known_intervals,
    parse_gaia, periodic_event_matches, pixel_geometry, project_gaia, review_flags, single_event_pixels)
from scripts.research.lightcurves import detrend, read_lightcurves
from scripts.research.pixels import read_target_pixels, target_pixel_product
from scripts.research.protocol import ROOT, ValidationError, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from scripts.research.tls_search import search_tls

VERSION = "ai_telescope_single_event_vetting_v1"
FIELDS = {"schema_version", "review_run", "scan_run", "physical_run", "output", "period_min_days",
          "period_max_days", "bls_max_period_grid", "search_timeout_seconds", "seed"}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != FIELDS or config["schema_version"] != 1:
        raise ValueError("Event-vetting config differs from schema")
    for key in ("review_run", "scan_run", "physical_run", "output"):
        path = Path(config[key])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Vetting paths must remain within project")
    for key, lower, upper in (("bls_max_period_grid", 100, 20000), ("search_timeout_seconds", 10, 300),
                              ("seed", 0, 2**31-1)):
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise ValueError("Invalid " + key)
    if not .5 <= config["period_min_days"] < config["period_max_days"] <= 100:
        raise ValueError("Invalid search bounds")
    return config


def _search_child(connection, curve, config, method):
    try:
        upper = min(config["period_max_days"], float(np.ptp(curve.time)) / 2)
        if method == "bls":
            result = search(curve, SearchConfig(period_min_days=config["period_min_days"],
                period_max_days=upper, max_period_grid=config["bls_max_period_grid"],
                max_signals=3, max_seconds=config["search_timeout_seconds"]))
            peaks = result["proposals"]
        else:
            flat, _ = detrend(curve)
            peaks = [search_tls(flat, period_min_days=config["period_min_days"], period_max_days=upper,
                               oversampling_factor=2, duration_grid_step=1.2, use_threads=1)]
        connection.send(clean_json({"status": "complete", "peaks": peaks,
                                   "used_catalog_ephemeris": False, "period_max_days": upper}))
    except Exception as exc:
        connection.send({"status": "unavailable", "error": type(exc).__name__ + ": " + str(exc)})
    finally:
        connection.close()


def bounded_period_search(curve, config, method):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_search_child, args=(child, curve, config, method), daemon=True)
    process.start(); child.close()
    try:
        if parent.poll(config["search_timeout_seconds"]):
            return parent.recv()
        return {"status": "unavailable", "error": "search_timeout"}
    except EOFError:
        return {"status": "unavailable", "error": "worker_exited_without_result"}
    finally:
        parent.close(); process.join(.1)
        if process.is_alive():
            process.terminate(); process.join(2)
        if process.is_alive():
            process.kill(); process.join(2)


def fetch_gaia(session, pixels, folder):
    wcs, ra, dec, _ = pixel_geometry(pixels.path)
    height, width = pixels.aperture.shape
    corners = wcs.pixel_to_world([-.5, -.5, width-.5, width-.5], [-.5, height-.5, -.5, height-.5])
    radius = max(.05, float(corners.separation(SkyCoord(ra, dec, unit="deg")).deg.max()) + .005)
    query = gaia_query(ra, dec, radius)
    raw_path, receipt_path = folder / "gaia_dr3.csv", folder / "gaia_receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["query"] != query or file_sha256(raw_path) != receipt["sha256"]:
            raise ValueError("Gaia cache provenance mismatch")
        payload = raw_path.read_bytes()
    else:
        for attempt in range(2):
            try:
                with session.get(GAIA_ENDPOINT, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query},
                                 timeout=(10, 45), stream=True) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 4 * 1024**2:
                            raise ValueError("Gaia cone response exceeds 4 MiB")
                        chunks.append(chunk)
                payload = b"".join(chunks)
                parse_gaia(payload)
                break
            except (requests.RequestException, ValueError):
                if attempt:
                    raise
        raw_path.write_bytes(payload)
        receipt = {"status": "complete", "endpoint": GAIA_ENDPOINT, "table": "gaiadr3.gaia_source",
                   "query": query, "retrieved_at": utc_now(), "sha256": file_sha256(raw_path),
                   "size_bytes": len(payload)}
        atomic_json(receipt_path, receipt)
    sources = project_gaia(parse_gaia(payload), wcs, float(np.nanmedian(pixels.time)), pixels.aperture.shape, (ra, dec))
    inside = [row for row in sources if row["inside_stamp"]]
    nearest = min(sources, key=lambda r: r["target_separation_arcsec"]) if sources else None
    counterpart = nearest if nearest and nearest["target_separation_arcsec"] <= 3 else None
    return {"status": "complete", "provenance": receipt, "sources": sources, "inside_stamp": len(inside),
            "positional_counterpart_source_id": counterpart["source_id"] if counterpart else None,
            "interpretation": "Gaia DR3 cone propagated to sector midpoint when proper motion exists; positional counterpart within 3 arcsec is provisional. G is not the TESS passband; nearby sources alone do not establish contamination."}


def event_plot(path, event, pixels, curve, pixel, maps, gaia):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    start, end = event["start_btjd"], event["end_btjd"]
    center, duration = (start+end)/2, end-start
    chosen = abs(curve.time-center) <= 3 * duration
    axes[0, 0].plot((curve.time[chosen]-center)*24, curve.flux[chosen]/np.median(curve.flux[chosen]), ".", ms=2)
    axes[0, 0].axvspan((start-center)*24, (end-center)*24, alpha=.2, color="orange")
    axes[0, 0].set(xlabel="Hours from segment midpoint", ylabel="Normalized PDCSAP flux")
    mask = (pixels.aperture & 2) != 0
    raw = np.sum(pixels.flux[:, mask], axis=1)
    chosen = np.isfinite(pixels.time) & (abs(pixels.time-center) <= 3*duration) & (pixels.quality == 0)
    axes[0, 1].plot((pixels.time[chosen]-center)*24, raw[chosen]/np.nanmedian(raw[chosen]), ".", ms=2)
    axes[0, 1].axvspan((start-center)*24, (end-center)*24, alpha=.2, color="orange")
    axes[0, 1].set(xlabel="Hours from segment midpoint", ylabel="Normalized pixel-aperture flux")
    for ax, key in zip(axes[1], ("reference", "difference")):
        if maps is None:
            ax.text(.05, .5, pixel.get("error", "Unavailable"), wrap=True, fontsize=8, transform=ax.transAxes)
            ax.set_axis_off(); continue
        image = ax.imshow(maps[key], origin="lower", cmap="viridis" if key == "reference" else "RdBu_r")
        fig.colorbar(image, ax=ax, shrink=.75)
        ax.contour(mask.astype(float), levels=[.5], colors="orange", linewidths=.7)
        target = pixel["localization"]["target_wcs_xy"]
        ax.plot(*target, "+", color="lime", ms=10, label="TIC WCS position")
        for row in gaia.get("sources", []):
            if row["inside_stamp"]:
                ax.plot(row["pixel_x"], row["pixel_y"], "o", mfc="none", mec="white", ms=4)
        centroid = pixel["localization"]["difference_xy"]
        if centroid is not None:
            ax.plot(*centroid, "x", color="magenta", ms=8)
        ax.set_title(key.replace("_", " ").title())
    fig.suptitle(f"TIC {event['target_id']} / sector {event['sector']} / BTJD {center:.5f}\nReview evidence only; white circles: Gaia, magenta: difference centroid", fontsize=10)
    fig.savefig(path, dpi=130); plt.close(fig)


def _checked_target(folder, spec_sha):
    receipt_path = folder / "complete.json"
    if not receipt_path.exists():
        return None
    receipt = _complete(folder)
    if receipt["spec_sha256"] != spec_sha:
        raise ValueError("Target vetting specification mismatch")
    return json.loads((folder / "target.json").read_text())


def run_target(target, rows, all_events, config, output, spec_sha, session):
    tic = target["target_id"]
    folder = output / "targets" / ("TIC" + tic); folder.mkdir(parents=True, exist_ok=True)
    cached = _checked_target(folder, spec_sha)
    if cached is not None:
        return cached
    product = target_pixel_product(target["lightcurve_path"])
    path = ROOT / "data/raw/tess/target_pixels" / ("TIC"+tic) / product["filename"]
    pixels = read_target_pixels(path, tic)
    original = json.loads((ROOT / config["scan_run"] / "targets" / ("TIC"+tic+".json")).read_text())
    if pixels.sha256 != original["source_sha256"] or pixels.sector != target["sector"]:
        raise ValueError("Pixels changed since blind scan")
    lightcurve = ROOT / target["lightcurve_path"]
    if file_sha256(lightcurve) != target["lightcurve_sha256"]:
        raise ValueError("Frozen light curve changed")
    curve = read_lightcurves([lightcurve], mission="TESS", target_id=tic)
    search_path = folder / "period_searches.json"
    if search_path.exists():
        saved = json.loads(search_path.read_text())
        if saved["spec_sha256"] != spec_sha:
            raise ValueError("Search cache specification mismatch")
        searches = saved["searches"]
    else:
        searches = {method: bounded_period_search(curve, config, method) for method in ("bls", "tls")}
        atomic_json(search_path, {"spec_sha256": spec_sha, "searches": searches})
    try:
        gaia = fetch_gaia(session, pixels, folder)
    except Exception as exc:
        gaia = {"status": "unavailable", "error": type(exc).__name__ + ": " + str(exc)}
    exclusions = known_intervals(pixels.time, target["candidates"])
    exclusions += [(float(r.start_btjd), float(r.end_btjd)) for r in all_events.itertuples()]
    events = []
    for row in rows.to_dict("records"):
        event_id = f"TIC{tic}-s{int(row['sector']):04d}-i{int(row['start_index'])}"
        maps = None
        try:
            pixel, maps = single_event_pixels(pixels, row["start_btjd"], row["end_btjd"],
                excluded_intervals=exclusions, seed=config["seed"] + int(row["start_index"]))
        except ValidationError as exc:
            pixel = {"status": "unavailable", "error": str(exc)}
        matches = periodic_event_matches(row["start_btjd"], row["end_btjd"], searches)
        flags = review_flags(pixel, gaia["status"], matches)
        if any(s["status"] != "complete" for s in searches.values()):
            flags.append("period_search_incomplete")
        neighbors = []
        if pixel["status"] == "complete" and gaia["status"] == "complete":
            center = pixel["localization"]["difference_xy"]
            if center is not None:
                neighbors = sorted([{**r, "difference_distance_pixels": float(np.hypot(r["pixel_x"]-center[0], r["pixel_y"]-center[1]))}
                                    for r in gaia["sources"] if r["inside_stamp"]], key=lambda r: r["difference_distance_pixels"])[:5]
        plot_name = event_id + ".png"
        event_plot(folder / plot_name, row, pixels, curve, pixel, maps, gaia)
        if maps is not None:
            np.savez_compressed(folder / (event_id + ".npz"), **maps)
        events.append({"event_id": event_id, "input": clean_json(row), "pixels": pixel,
                       "periodic_matches": matches, "nearest_gaia_to_difference": neighbors,
                       "flags": flags, "plot": str((folder / plot_name).relative_to(output))})
    record = {"status": "complete", "target_id": tic, "spec_sha256": spec_sha,
              "lightcurve_sha256": target["lightcurve_sha256"], "pixel_sha256": pixels.sha256,
              "gaia": gaia, "searches": searches, "events": events}
    atomic_json(folder / "target.json", clean_json(record))
    files = {p.name: file_sha256(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != "complete.json"}
    atomic_json(folder / "complete.json", {"status": "complete", "spec_sha256": spec_sha, "files": files})
    return record


def aggregate(records, output, spec_sha):
    rows = []
    for record in records:
        for event in record["events"]:
            pixel = event["pixels"]
            ap = pixel.get("photometry", {}).get("pipeline", {})
            loc = pixel.get("localization", {})
            rows.append({"event_id": event["event_id"], "target_id": record["target_id"],
                "sector": event["input"]["sector"], "start_btjd": event["input"]["start_btjd"],
                "end_btjd": event["input"]["end_btjd"], "pixel_status": pixel["status"],
                "depth_relative_flux": ap.get("depth_relative_flux"), "depth_snr_white": ap.get("depth_snr_white"),
                "offset_pixels": loc.get("offset_pixels"), "gaia_status": record["gaia"]["status"],
                "gaia_sources_in_stamp": record["gaia"].get("inside_stamp"),
                "periodic_match_count": len(event["periodic_matches"]), "flags": ";".join(event["flags"]),
                "scientific_review_score": event["input"]["scientific_review_score"], "plot": event["plot"]})
    frame = pd.DataFrame(rows).sort_values("scientific_review_score", ascending=False)
    frame.to_csv(output / "events.csv", index=False)
    flagged = {flag: int(sum(flag in event["flags"] for record in records for event in record["events"]))
               for flag in sorted({flag for record in records for event in record["events"] for flag in event["flags"]})}
    counts = {"events": len(frame), "hosts": len(records), "pixel_complete": int((frame.pixel_status == "complete").sum()),
              "gaia_hosts_complete": sum(r["gaia"]["status"] == "complete" for r in records),
              "bls_hosts_complete": sum(r["searches"]["bls"]["status"] == "complete" for r in records),
              "tls_hosts_complete": sum(r["searches"]["tls"]["status"] == "complete" for r in records)}
    summary = {"status": "complete", "version": VERSION, "spec_sha256": spec_sha, "counts": counts,
               "event_flags_nonexclusive": flagged, "claims": {"new_planets": False, "calibrated_false_alarm_rate": False,
               "prospective_evaluation": False, "deployed_to_watcher": False}}
    atomic_json(output / "summary.json", summary)
    lines = ["# Single-event audit vetting", "", f"All {len(frame)} frozen audit events on {len(records)} hosts are accounted for.",
        "", "| Diagnostic | Completed |", "| --- | ---: |",
        f"| Local pixel evidence | {counts['pixel_complete']}/{counts['events']} events |",
        *[f"| {method.upper()} | {counts[method+'_hosts_complete']}/{counts['hosts']} hosts |" for method in ("gaia", "bls", "tls")],
        "", "## Review flags (overlapping)", "", *[f"- {flag}: {count}" for flag, count in flagged.items()],
        "", "Open [the visual review gallery](index.html) and [event table](events.csv). Every event has a plot and retained evidence, including failures.",
        "", "## Method and limits", "",
        "Local difference images use the segment midpoint and actual boundaries, a two-sided linear baseline, and masks for other detected segments and known primary transits. Period searches use the full light curve without catalog masking. Ephemeris overlap alone is not evidence of a significant periodic signal.",
        "", "Depth errors assume independent samples; centroid Monte Carlo fixes pixels selected at S/N >= 3. Neither uncertainty accounts for correlated noise, model selection, or WCS errors. Offset flags require human inspection, and no event is promoted to a planet candidate.",
        "", "The Gaia positional counterpart is provisional. Proper motions are propagated to the sector midpoint when available; parallax and radial velocity are omitted. Missing proper motion is recorded. Gaia G magnitudes are not TESS dilution estimates, and sources outside the stamp may contaminate it.",
        "", "This is the candidate-enriched, reused audit cohort. The neural threshold has not been calibrated for continuous scans. Current TOI/planet registry crossmatching, astrophysical disposition, injection recovery and independent prospective performance remain outstanding.",
        "", "Data references: [ESA Gaia archive queries](https://www.cosmos.esa.int/web/gaia-users/archive/writing-queries), [MAST TESS products](https://archive.stsci.edu/missions-and-data/tess/data-products)."]
    (output / "report.md").write_text("\n".join(lines)+"\n")
    cards = []
    for row in frame.to_dict("records"):
        cards.append(f"<article><h2>{html.escape(row['event_id'])}</h2><p>{html.escape(row['flags'] or 'No automatic flags; still requires review')}</p><a href='{row['plot']}'><img loading='lazy' src='{row['plot']}'></a></article>")
    (output / "index.html").write_text("<!doctype html><meta charset='utf-8'><title>Single-event audit review</title><style>body{font-family:system-ui;max-width:1100px;margin:2em auto;background:#f5f6f8;color:#192230}article{background:white;padding:1em;margin:2em 0}img{width:100%}h2{font-size:1.1em}</style><h1>Single-event audit review</h1><p>79 events; review diagnostics, not validated planets. Flags overlap. Pixel errors assume independent samples.</p>" + "\n".join(cards))
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "report.md", "events.csv", "index.html")}
    files.update({str(p.relative_to(output)): file_sha256(p) for p in (output / "targets").glob("*/complete.json")})
    atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha, "completed_at": utc_now(), "files": files})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_event_vetting_v1.json")
    args = parser.parse_args(argv)
    config = validate_config(json.loads((ROOT / args.config).read_text()))
    inputs = {key: _complete(ROOT / config[key]) for key in ("review_run", "scan_run", "physical_run")}
    source_files = ("scripts/experiments/ai_telescope_event_vetting.py", "scripts/research/event_vetting.py",
                    "scripts/research/pixels.py", "scripts/research/tls_search.py", "scripts/research/detection.py",
                    "scripts/research/lightcurves.py", "scripts/experiments/mission_adaptation.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(ROOT / args.config),
            "inputs": {k: file_sha256(ROOT / config[k] / "complete.json") for k in inputs},
            "source_files": {name: file_sha256(ROOT / name) for name in source_files},
            "review_rules": "Descriptive flags only; white depth S/N < 5; centroid offset >= 1 pixel; no model tuning or planet promotion"}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    spec_path = output / "spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing vetting run uses a different specification")
    if (output / "complete.json").exists():
        _complete(output)
        for folder in (output / "targets").iterdir():
            _checked_target(folder, spec_sha)
        print(json.dumps({"status": "already_complete", "output": str(output)})); return
    atomic_json(spec_path, spec)
    queue = pd.read_csv(ROOT / config["review_run"] / "audit_review_queue.csv", dtype={"target_id": str})
    events = pd.read_csv(ROOT / config["scan_run"] / "events.csv", dtype={"target_id": str})
    cohort = json.loads((ROOT / config["physical_run"] / "cohort.json").read_text())
    targets = {t["target_id"]: t for t in cohort["targets"]}
    records = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "Thesis-Rojin-event-vetting/1"
        for tic, rows in queue.groupby("target_id", sort=True):
            began = time.monotonic()
            records.append(run_target(targets[tic], rows, events[events.target_id == tic], config, output, spec_sha, session))
            print(json.dumps({"stage": "event_vetting", "target_id": tic, "hosts_complete": len(records),
                              "hosts_total": queue.target_id.nunique(), "events": len(rows), "seconds": time.monotonic()-began}), flush=True)
    if sum(len(r["events"]) for r in records) != len(queue):
        raise ValueError("Event accounting mismatch")
    print(json.dumps(aggregate(records, output, spec_sha), indent=2), flush=True)


if __name__ == "__main__":
    main()
