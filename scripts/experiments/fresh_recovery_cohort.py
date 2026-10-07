"""Freeze and acquire the next cached-host cohort without scoring its members."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

import pandas as pd
import requests

from scripts.experiments.freeze_prospective_cohort import candidate_targets
from scripts.experiments.mission_adaptation import atomic_json
from scripts.experiments.tls_pixel_pilot import _download, _head
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

OUTPUT = ROOT / "outputs/research/ai_telescope/fresh-recovery-cohort-v1"
ACQUISITION = {"target_pixel_root": "data/raw/tess/target_pixels",
               "receipt_root": "data/raw/tess/metadata/target_pixel_receipts",
               "max_product_bytes": 320 * 1024**2, "max_total_download_bytes": 12 * 1024**3}
SEED = 28092027


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def freeze():
    path = OUTPUT / "manifest.json"
    if path.exists():
        document = json.loads(path.read_text())
        receipt = json.loads((OUTPUT / "frozen.json").read_text())
        if receipt["manifest_sha256"] != file_sha256(path):
            raise ValueError("Fresh cohort manifest changed")
        for name, checksum in document["source_files"].items():
            if file_sha256(ROOT / name) != checksum:
                raise ValueError("Cohort source changed: " + name)
        return document
    shared_path = ROOT / "data/processed/tess/shared_v1/manifest_tess_shared_v1.csv"
    audit_path = ROOT / "data/processed/tess/v0/catalog_audit.csv"
    overlap_path = ROOT / "data/processed/tess/v0/kepler_overlap.csv"
    prior_path = ROOT / "results/prospective_cohort_v1/manifest.json"
    shared = pd.read_csv(shared_path)
    prior = json.loads(prior_path.read_text())
    audit = pd.read_csv(audit_path)
    excluded = set(shared.tic_id.astype(int))
    excluded.update(int(t["target_id"]) for t in prior["targets"])
    excluded.update(pd.read_csv(overlap_path).tic_id.astype(int))
    excluded.update(int(t.removeprefix("TIC")) for t in candidate_targets(
        ROOT / "outputs/research/research.sqlite3") if t.removeprefix("TIC").isdigit())
    # Propagate the existing five-arcsecond connected components, not just IDs.
    groups = set(audit[audit.tic_id.isin(excluded)].split_group.dropna())
    excluded.update(audit[audit.split_group.isin(groups)].tic_id.dropna().astype(int))
    available = []
    for folder in (ROOT / "data/raw/tess/lightcurves").glob("TIC*"):
        target_id = folder.name[3:]
        files = sorted(folder.glob("*_lc.fits"))
        if target_id.isdigit() and int(target_id) not in excluded and files:
            available.append((digest(f"{SEED}:{target_id}"), target_id, files[0]))
    if len(available) < 50:
        raise ValueError("Too few fresh cached hosts after cross-mission exclusions")
    targets = [{"target_id": tic, "product_path": str(path.relative_to(ROOT)),
                "product_sha256": file_sha256(path), "order": i + 1}
               for i, (_, tic, path) in enumerate(sorted(available)[:100])]
    sources = ["scripts/experiments/fresh_recovery_cohort.py", "scripts/experiments/tls_pixel_pilot.py"]
    document = {"version": "fresh_recovery_cohort_v1", "frozen_at": utc_now(),
                "selection": "first 100 by SHA256 of canonical seed:TIC; earliest cached LC filename",
                "seed": SEED, "eligible_hosts": len(available), "targets": targets,
                "exclusions": {"host_ids": sorted(excluded), "cross_mission_quarantine": True,
                               "prior_prospective_cohort": True, "proximity_groups": True},
                "inputs": {str(p.relative_to(ROOT)): file_sha256(p)
                           for p in (shared_path, audit_path, overlap_path, prior_path)},
                "source_files": {name: file_sha256(ROOT / name) for name in sources},
                "acquisition": ACQUISITION,
                "scope": "unscored injection evaluation; no inference or tuning before freeze; not a labelled classifier audit"}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_json(path, document)
    atomic_json(OUTPUT / "frozen.json", {"manifest_sha256": file_sha256(path), "frozen_at": utc_now()})
    return document


def acquire(document):
    plan_path = OUTPUT / "download_plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan["cohort_sha256"] != digest(document):
            raise ValueError("Archive plan cohort mismatch")
    else:
        def head(target):
            with requests.Session() as session:
                return {"target_id": target["target_id"], **_head(session, target, ACQUISITION)}
        products = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(head, t) for t in document["targets"]]
            for future in as_completed(futures):
                products.append(future.result())
        total = sum(p["size_bytes"] for p in products)
        if total > ACQUISITION["max_total_download_bytes"]:
            raise ValueError("Fresh cohort exceeds download budget")
        plan = {"cohort_sha256": digest(document), "products": sorted(products, key=lambda p: int(p["target_id"])),
                "total_bytes": total}
        atomic_json(plan_path, plan)
    targets = {t["target_id"]: t for t in document["targets"]}
    def download(product):
        target = targets[product["target_id"]]
        if file_sha256(ROOT / target["product_path"]) != target["product_sha256"]:
            raise ValueError("Frozen LC source changed")
        with requests.Session() as session:
            path, receipt, downloaded = _download(session, product, target, ACQUISITION)
        return {"target_id": target["target_id"], "path": str(path.relative_to(ROOT)),
                "sha256": receipt["sha256"], "downloaded": downloaded}
    acquired = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, p) for p in plan["products"]]
        for future in as_completed(futures):
            acquired.append(future.result())
            print(json.dumps({"stage": "fresh_acquisition", "completed": len(acquired), "registered": len(targets)}), flush=True)
    atomic_json(OUTPUT / "acquired.json", {"cohort_sha256": digest(document), "completed_at": utc_now(),
                "targets": sorted(acquired, key=lambda t: int(t["target_id"]))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquire", action="store_true")
    args = parser.parse_args()
    document = freeze()
    print(json.dumps({"stage": "frozen", "hosts": len(document["targets"]), "output": str(OUTPUT)}), flush=True)
    if args.acquire:
        acquire(document)


if __name__ == "__main__":
    main()
