"""Freeze unseen cached TESS hosts before any new model inference or review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd

from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "prospective_cached_host_cohort_v1"


def candidate_targets(database):
    path = Path(database)
    if not path.exists():
        return set()
    with sqlite3.connect(path) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidates'").fetchone()
        return {str(row[0]) for row in db.execute("SELECT DISTINCT target_id FROM candidates")} if exists else set()


def freeze(root, database, size=100, seed=92027):
    if type(size) is not int or not 10 <= size <= 500 or type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("Invalid prospective cohort bounds")
    manifest = pd.read_csv(root / "data/processed/tess/shared_v1/manifest_tess_shared_v1.csv")
    excluded = {str(int(value)) for value in manifest.star_id}
    excluded |= {value.removeprefix("TIC") for value in candidate_targets(database)}
    folders = root / "data/raw/tess/lightcurves"
    eligible = []
    for folder in folders.glob("TIC*"):
        target = folder.name.removeprefix("TIC")
        products = sorted(folder.glob("*_lc.fits"))
        if target.isdigit() and target not in excluded and products:
            eligible.append((hashlib.sha256(f"{seed}:{target}".encode()).hexdigest(), target, products[0]))
    eligible.sort()
    if len(eligible) < size:
        raise ValueError(f"Only {len(eligible)} unseen cached hosts are eligible; requested {size}")
    selected = []
    for order, (_, target, product) in enumerate(eligible[:size], 1):
        selected.append({"order": order, "mission": "TESS", "target_id": target,
                         "product_path": str(product.relative_to(root)), "product_sha256": file_sha256(product),
                         "selection_score_sha256": hashlib.sha256(f"{seed}:{target}".encode()).hexdigest()})
    return {"schema_version": 1, "version": VERSION, "status": "frozen_unscored", "frozen_at": utc_now(),
            "selection": {"seed": seed, "requested_hosts": size,
                "rule": "first SHA256(seed:target_id) among cached TESS hosts absent from all shared_v1 rows and current research candidates; earliest filename only"},
            "exclusions": {"shared_v1_hosts": len({str(int(value)) for value in manifest.star_id}),
                           "research_candidate_targets": len(candidate_targets(database))},
            "targets": selected,
            "governance": {"model_inference_before_freeze": False, "catalog_label_selection": False,
                "human_review_selection": False, "original_test_partition_used": False,
                "allowed_next_actions": ["blind_detection", "fixed_expert_scoring", "catalog_and_human_vetting"],
                "prohibited": ["changing_membership_after_viewing_scores", "hyperparameter_tuning_on_this_cohort"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="outputs/research/research.sqlite3")
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=92027)
    parser.add_argument("--output", default="results/prospective_cohort_v1")
    args = parser.parse_args(argv)
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()): raise ValueError("Prospective cohort output already exists")
    output.mkdir(parents=True, exist_ok=True)
    document = freeze(ROOT, ROOT / args.database, args.size, args.seed)
    spec = {"version": VERSION, "size": args.size, "seed": args.seed,
            "database_path": args.database, "source_sha256": file_sha256(ROOT / "scripts/experiments/freeze_prospective_cohort.py")}
    document["spec_sha256"] = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    atomic_json(output / "spec.json", spec); atomic_json(output / "manifest.json", document)
    (output / "README.md").write_text("\n".join(["# Frozen prospective cached-host cohort", "",
        f"{len(document['targets'])} cached TESS hosts were frozen before new model inference, catalog selection, or review.",
        "They are absent from every shared_v1 partition and from current research candidates.", "",
        "Membership must not change after scores are viewed. Run blind detection and the already frozen experts without tuning,",
        "then record catalog and human-vetting outcomes. This is an archival prospective evaluation, not a sky survey.", ""]) + "\n")
    files = {name: file_sha256(output / name) for name in ("spec.json", "manifest.json", "README.md")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": document["spec_sha256"], "files": files})
    print(json.dumps({"status": "complete", "output": str(output), "hosts": len(document["targets"])}, indent=2))


if __name__ == "__main__": main()
