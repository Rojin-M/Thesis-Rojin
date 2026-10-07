"""Recover crowded Gaia cones without altering the frozen event-vetting run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from astropy.coordinates import SkyCoord
from astropy.io import fits
import numpy as np
import pandas as pd
import requests

from scripts.experiments.ai_telescope_blind_review import _complete
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.event_vetting import GAIA_ENDPOINT, gaia_query, parse_gaia, pixel_geometry, project_gaia
from scripts.research.pixels import target_pixel_product
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256


def main():
    source = ROOT / "outputs/research/ai_telescope/event-vetting-v1"
    output = ROOT / "outputs/research/ai_telescope/gaia-supplement-v1"
    _complete(source)
    records = []
    for folder in sorted((source / "targets").iterdir()):
        _complete(folder)
        records.append(json.loads((folder / "target.json").read_text()))
    missing = [r for r in records if r["gaia"]["status"] != "complete"]
    spec = {"version": "crowded_gaia_supplement_v1", "parent_receipt_sha256": file_sha256(source/"complete.json"),
            "target_ids": [r["target_id"] for r in missing], "maximum_sources_per_cone": 20000,
            "maximum_response_bytes": 4*1024**2,
            "sources": {name: file_sha256(ROOT/name) for name in
                        ("scripts/experiments/ai_telescope_gaia_supplement.py", "scripts/research/event_vetting.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    if (output/"spec.json").exists() and json.loads((output/"spec.json").read_text()) != spec:
        raise ValueError("Gaia supplement specification changed")
    if (output/"complete.json").exists():
        _complete(output); return
    atomic_json(output/"spec.json", spec)
    cohort = json.loads((ROOT/"outputs/research/physical_experts/pilot-v1/cohort.json").read_text())
    targets = {t["target_id"]: t for t in cohort["targets"]}
    restored = []
    with requests.Session() as session:
        for record in missing:
            tic = record["target_id"]
            path = ROOT/"data/raw/tess/target_pixels"/("TIC"+tic)/target_pixel_product(targets[tic]["lightcurve_path"])["filename"]
            if file_sha256(path) != record["pixel_sha256"]:
                raise ValueError("Pixel source changed")
            wcs, ra, dec, _ = pixel_geometry(path)
            with fits.open(path, memmap=False) as hdus:
                height, width = hdus[2].data.shape
                epoch = float(np.nanmedian(hdus[1].data["TIME"]))
                header = hdus[1].header
                epoch += float(header.get("BJDREFI", 2457000)) + float(header.get("BJDREFF", 0)) - 2457000 + float(header.get("TIMEZERO", 0))
            corners = wcs.pixel_to_world([-.5, -.5, width-.5, width-.5], [-.5, height-.5, -.5, height-.5])
            radius = max(.05, float(corners.separation(SkyCoord(ra, dec, unit="deg")).deg.max())+.005)
            query = gaia_query(ra, dec, radius, limit=20000)
            with session.get(GAIA_ENDPOINT, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query},
                             timeout=(10, 60), stream=True) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > spec["maximum_response_bytes"]:
                        raise ValueError("Supplemental Gaia response exceeds byte bound")
                    chunks.append(chunk)
            raw = b"".join(chunks)
            frame = parse_gaia(raw, limit=20000)
            sources = project_gaia(frame, wcs, epoch, (height, width), (ra, dec))
            raw_path = output/("TIC"+tic+".csv"); raw_path.write_bytes(raw)
            events = []
            for event in record["events"]:
                center = event["pixels"].get("localization", {}).get("difference_xy")
                nearest = [] if center is None else sorted(
                    [{**r, "difference_distance_pixels": float(np.hypot(r["pixel_x"]-center[0], r["pixel_y"]-center[1]))}
                     for r in sources if r["inside_stamp"]], key=lambda r: r["difference_distance_pixels"])[:5]
                events.append({"event_id": event["event_id"], "nearest_gaia_to_difference": nearest})
            result = {"status": "complete", "target_id": tic, "spec_sha256": spec_sha,
                      "original_unavailability": record["gaia"]["error"], "source_count": len(sources),
                      "inside_stamp": sum(r["inside_stamp"] for r in sources), "sources": sources, "events": events,
                      "provenance": {"endpoint": GAIA_ENDPOINT, "query": query, "retrieved_at": utc_now(),
                                     "response_sha256": file_sha256(raw_path), "bytes": size}}
            atomic_json(output/("TIC"+tic+".json"), result)
            restored.append(result)
            print(json.dumps({"target_id": tic, "sources": len(sources), "status": "recovered"}), flush=True)
    frame = pd.read_csv(source/"events.csv", dtype={"target_id": str}, keep_default_na=False)
    for record in restored:
        use = frame.target_id == record["target_id"]
        frame.loc[use, "gaia_status"] = "complete_supplement"
        frame.loc[use, "gaia_sources_in_stamp"] = record["inside_stamp"]
        frame.loc[use, "flags"] = frame.loc[use, "flags"].map(lambda value: ";".join(x for x in value.split(";") if x != "gaia_unavailable"))
    frame.to_csv(output/"events_with_gaia.csv", index=False)
    summary = {"status": "complete", "hosts_recovered": len(restored), "hosts_with_gaia_total": len(records)-len(missing)+len(restored),
               "event_count": len(frame), "spec_sha256": spec_sha}
    atomic_json(output/"summary.json", summary)
    (output/"report.md").write_text("# Crowded-field Gaia supplement\n\n"
        f"Recovered {len(restored)} originally unavailable Gaia cone(s), giving {summary['hosts_with_gaia_total']}/{len(records)} hosts with catalog evidence.\n\n"
        "The original frozen run and gallery are unchanged. This supplement raises the explicit per-cone limit from 2,000 to 20,000 while retaining a 4 MiB response cap; rows are never silently truncated.\n\n"
        "[Consolidated event table](events_with_gaia.csv) clears only recovered Gaia-unavailable flags. Pixel, periodicity, neural scores and cohort membership are unchanged. Raw query responses and projected source lists are retained per host. Gaia evidence does not establish the source of an event.\n")
    files = {p.name: file_sha256(p) for p in output.iterdir() if p.is_file() and p.name not in ("complete.json", "tmux.log")}
    atomic_json(output/"complete.json", {"status": "complete", "spec_sha256": spec_sha, "files": files})


if __name__ == "__main__":
    main()
