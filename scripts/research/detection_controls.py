"""Small, explicit engineering recovery experiment; never a search-readiness claim.

Known-object controls are drawn deterministically from TRAIN groups only.
Catalog ephemerides reach evaluation only after blind proposals are persisted.
Injections and transformed negative controls are separate synthetic jobs, with
parent byte receipts and fixed random seeds. No model/threshold is fitted.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .detection import SearchConfig, harmonic_relation, phase_distance
from .detection_worker import run_local_detection
from .lightcurves import read_lightcurves
from .local_selection import cached_tess_paths
from .protocol import ConflictError, ROOT, canonical_json, digest, utc_now
from .provenance import code_snapshot, file_sha256

EXPERIMENT = "detection-engineering-controls-v1"
# A declared descriptive reference only; it is not used to filter proposals,
# optimize configuration, authorize a search, or interpret planet probabilities.
DESCRIPTIVE_WHITE_SNR = 7.1


def evaluate_proposals(proposals, truth, baseline_start, baseline_days):
    """Truth-only post-search check of period AND observed transit phase."""
    true_p = float(truth["period_days"])
    true_t = float(truth["epoch_bjd_tdb"]) - 2457000
    true_d = float(truth["duration_hours"]) / 24
    anchor = true_t + round((baseline_start - true_t) / true_p) * true_p
    evaluated = []
    for proposal in proposals:
        p = proposal["period_days"]
        epoch = proposal["epoch_btjd"]
        relative_period_error = abs(p - true_p) / true_p
        phase_error = abs(float(phase_distance([anchor], p, epoch)[0]))
        accumulated_drift = relative_period_error * baseline_days
        tolerance = max(true_d, proposal["duration_hours"] / 24) / 2
        recovered = relative_period_error <= .005 and accumulated_drift <= true_d and phase_error <= tolerance
        harmonic = harmonic_relation(proposal, {"period_days": true_p, "epoch_btjd": anchor,
                                               "duration_hours": truth["duration_hours"]}, baseline_days)
        evaluated.append({"rank": proposal["rank"], "period_days": p, "relative_period_error": relative_period_error,
            "epoch_phase_error_days": phase_error, "accumulated_drift_days": accumulated_drift,
            "direct_ephemeris_recovery": bool(recovered), "harmonic_relation": harmonic,
            "sampling_gate_passed": proposal["diagnostics"]["sampling_gate_passed"],
            "depth_snr_white": proposal["depth_snr_white"],
            "above_descriptive_snr_reference": proposal["depth_snr_white"] >= DESCRIPTIVE_WHITE_SNR})
    return {"truth": truth, "evaluation_rules": {"relative_period_tolerance": .005,
        "accumulated_drift_limit": "one_truth_duration", "epoch_tolerance": "half_the_larger_duration",
        "descriptive_snr_reference": DESCRIPTIVE_WHITE_SNR, "truth_used_in_search": False},
        "direct_recovery": any(p["direct_ephemeris_recovery"] for p in evaluated),
        "recovered_with_sampling_gate": any(p["direct_ephemeris_recovery"] and p["sampling_gate_passed"] for p in evaluated),
        "proposals": evaluated}


def _selection(root):
    """Two short-period positive TRAIN objects per mission, fixed sorting; no tuning."""
    selected = []
    for mission in ("tess", "kepler"):
        manifest_path = root / f"data/processed/{mission}/shared_v1/manifest_{mission}_shared_v1.csv"
        manifest = pd.read_csv(manifest_path)
        eligible = manifest[(manifest.split == "train") & (manifest.y == 1) &
                            manifest.period.between(.5, 10.) & (manifest.duration_hours < 6.)].sort_values("candidate_id")
        chosen = eligible.drop_duplicates("star_id").head(2)
        if len(chosen) != 2:
            raise ValueError("Need two eligible TRAIN stars per mission for this fixed control suite")
        for _, row in chosen.iterrows():
            star = int(row.star_id)
            # Explicit group leakage check against all held-out rows.
            if not (manifest.loc[manifest.star_id == star, "split"] == "train").all():
                raise ValueError("Selected control star also occurs in a held-out group")
            if mission == "tess":
                paths = cached_tess_paths(root, str(star), 1)
            else:
                directory = root / "data/raw/kepler/lightcurves/mastDownload/Kepler"
                products = sorted(directory.glob(f"kplr{star:09d}*/*_llc.fits"))
                # Choose the first sufficiently long product, using only times,
                # never catalog ephemerides in product selection or the search.
                paths = []
                for p in products[:20]:
                    trial = read_lightcurves([p], mission="Kepler", target_id=str(star))
                    if np.ptp(trial.time) >= 20:
                        paths = [p]
                        break
                if not paths:
                    raise ValueError("No bounded >=20 day cached Kepler product for selected training control")
            selected.append({"mission": "TESS" if mission == "tess" else "Kepler", "target_id": str(star), "paths": paths,
                "candidate_id": str(row.candidate_id), "split": "train", "manifest_path": str(manifest_path),
                "manifest_sha256": file_sha256(manifest_path), "truth": {"period_days": float(row.period),
                "epoch_bjd_tdb": float(row.epoch_bjd), "duration_hours": float(row.duration_hours)}})
    return selected


def _write_derived(path, curve, flux):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, time=curve.time, flux=flux, flux_err=curve.error,
                        quality=np.zeros(len(curve.time), dtype=np.int32))
    payload = buffer.getvalue()
    if path.exists():
        if path.read_bytes() != payload:
            raise ConflictError("Derived control file changed; choose a new versioned experiment directory")
    else:
        with path.open("xb") as handle:
            handle.write(payload)


def run_controls(store, artifacts, protocol_id, output, root=ROOT):
    output, root = Path(output).resolve(), Path(root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cfg = SearchConfig.from_protocol(store.get_protocol(protocol_id)["document"])
    selection = _selection(root)
    source_signature = [{**entry, "paths": [str(p) for p in entry["paths"]],
                         "source_hashes": {str(p): file_sha256(p) for p in entry["paths"]}} for entry in selection]
    frozen = {"experiment": EXPERIMENT, "config": asdict(cfg), "selection": source_signature,
              "code_manifest_sha256": code_snapshot()["manifest_sha256"],
              "selection_rule": "first_two_distinct_train_positive_stars_sorted_by_candidate_id_per_mission; catalog P=.5–10 days, duration<6 hours for engineering controls only",
              "injections": {"periods_days": [2.731, 5.173], "depths": [.0005, .002, .008], "duration_hours": 2.4},
              "negative_controls": ["flux_permutation_seed_2401", "flux_inversion", "white_noise_seed_2402", "white_noise_seed_2403"],
              "descriptive_snr_reference": DESCRIPTIVE_WHITE_SNR, "selection_or_threshold_fitting": False}
    frozen_path = output / "experiment.json"
    if frozen_path.exists():
        if json.loads(frozen_path.read_text()) != json.loads(canonical_json(frozen)):
            raise ConflictError("Experiment configuration/code changed; use a new output directory")
    else:
        with frozen_path.open("x") as handle:
            handle.write(json.dumps(frozen, indent=2) + "\n")
    report = {"experiment": EXPERIMENT, "config_sha256": digest(frozen), "known_controls": [], "injections": [], "negatives": [],
              "scientific_readiness": False, "new_scientific_download_bytes": 0,
              "limitations": ["Small selected TRAIN-star engineering experiment, not an unbiased survey benchmark",
                "White-noise S/N is uncalibrated under correlated variability; no false-alarm control established",
                "Injections are boxes added before detrending to real PDCSAP flux; native pipeline losses are unmeasured",
                "Inverted real photometry is not guaranteed planet-free; permutation destroys temporal correlations",
                "Known signals remain present in injection curves; recovery is assessed among at most three blind proposals",
                "No test-set model selection, no CNN score, no pixel-based discovery, no prospective search"]}

    def run_one(entry, category, label, truth=None):
        print("Running " + category + ": " + label, flush=True)
        result = run_local_detection(store, artifacts, protocol_id, paths=entry["paths"], mission=entry["mission"],
            target_id=entry["target_id"], cohort="known_object_control" if category == "known_controls" else "synthetic_fixture",
            config=cfg, time_system=entry.get("time_system"),
            experiment={"kind": category, "label": label, "suite": EXPERIMENT, "config_sha256": digest(frozen),
                        "parent_sources": entry.get("parent_sources", []), "split": "train",
                        "truth_access": "evaluation_only_after_search", "transform": entry.get("transform")},
            job_key=EXPERIMENT + ":" + digest({"config": digest(frozen), "label": label})[:24])
        proposals = []
        for cid in result["candidate_ids"]:
            record = store.get_candidate(cid)
            proposals.append(next(e["payload"]["proposal"] for e in record["evidence"] if e["kind"] == "detection"))
        data = read_lightcurves(entry["paths"], mission=entry["mission"], target_id=entry["target_id"], time_system=entry.get("time_system"))
        record = {"label": label, "job_id": result["job_id"], "candidate_ids": result["candidate_ids"],
                  "target_id": entry["target_id"], "mission": entry["mission"], "source_sha256": [s["sha256"] for s in data.sources],
                  "proposal_count": len(proposals), "strongest_depth_snr_white": max((p["depth_snr_white"] for p in proposals), default=None),
                  "proposals_above_descriptive_reference_with_coverage": sum(p["depth_snr_white"] >= DESCRIPTIVE_WHITE_SNR and
                                                                 p["diagnostics"]["sampling_gate_passed"] for p in proposals)}
        if truth:
            record["evaluation"] = evaluate_proposals(proposals, truth, float(data.time[0]), float(np.ptp(data.time)))
        report[category].append(record)
        # A partial report is intentionally explicit and restartable.
        (output / "progress.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")

    for entry in selection:
        run_one(entry, "known_controls", entry["mission"] + "-" + entry["candidate_id"], entry["truth"])
    base_entry = selection[0]
    base = read_lightcurves(base_entry["paths"], mission="TESS", target_id=base_entry["target_id"])
    parents = [{"path": s["path"], "sha256": s["sha256"], "source_uri": s["source_uri"]} for s in base.sources]
    for period in frozen["injections"]["periods_days"]:
        for depth in frozen["injections"]["depths"]:
            epoch = float(base.time[0] + .37 * period)
            duration = 2.4 / 24
            mask = np.abs(phase_distance(base.time, period, epoch)) < duration / 2
            name = f"box-p{period}-d{depth}"
            path = output / (name + ".npz")
            _write_derived(path, base, base.flux * (1 - depth * mask))
            run_one({"paths": [path], "mission": "TESS", "target_id": "SYNTHETIC-" + name,
                     "time_system": "BTJD", "parent_sources": parents,
                     "transform": {"kind": "multiplicative_box_before_detrending", "period_days": period,
                                   "epoch_btjd": epoch, "duration_hours": 2.4, "depth": depth}},
                    "injections", name, {"period_days": period, "epoch_bjd_tdb": epoch + 2457000,
                                         "duration_hours": 2.4, "injected_depth": depth})
    median = float(np.median(base.flux))
    for name in frozen["negative_controls"]:
        if name.startswith("flux_permutation"):
            flux = np.random.default_rng(2401).permutation(base.flux)
        elif name == "flux_inversion":
            flux = 2 * median - base.flux
        else:
            seed = int(name.rsplit("_", 1)[1])
            flux = median + np.random.default_rng(seed).normal(0, base.error)
        path = output / (name + ".npz")
        _write_derived(path, base, flux)
        run_one({"paths": [path], "mission": "TESS", "target_id": "SYNTHETIC-" + name, "time_system": "BTJD",
                 "parent_sources": parents, "transform": {"kind": name}}, "negatives", name)
    report["summary"] = {"known_direct_recovery": sum(r["evaluation"]["direct_recovery"] for r in report["known_controls"]),
                         "known_controls": len(report["known_controls"]),
                         "injected_direct_recovery": sum(r["evaluation"]["direct_recovery"] for r in report["injections"]),
                         "injection_controls": len(report["injections"]), "negative_controls": len(report["negatives"]),
                         "negative_controls_above_descriptive_reference": sum(r["proposals_above_descriptive_reference_with_coverage"] > 0 for r in report["negatives"])}
    report_path = output / "report.json"
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if report_path.exists() and report_path.read_text() != serialized:
        raise ConflictError("Completed experiment report changed unexpectedly")
    report_path.write_text(serialized)
    provenance = store.register_provenance(kind="control_experiment", identity=EXPERIMENT + ":" + report["config_sha256"],
        sha256_digest=file_sha256(report_path), retrieved_at=datetime.fromtimestamp(frozen_path.stat().st_mtime, timezone.utc).isoformat(),
        details={"report_path": str(report_path), "experiment": frozen, "search_readiness": False})
    for category in ("known_controls", "injections", "negatives"):
        for record in report[category]:
            for cid in record["candidate_ids"]:
                store.put_evidence(candidate_id=cid, evidence_key=EXPERIMENT + ":evaluation", kind="recovery_evaluation", state="complete",
                    summary="Post-search labelled control evaluation; catalog/injection truth was not passed into BLS.",
                    payload=record, provenance_id=provenance["id"])
                store.put_evidence(candidate_id=cid, evidence_key=EXPERIMENT + ":controls", kind="controls", state="incomplete",
                    summary="Small engineering controls executed; survey completeness and calibrated false-alarm rate remain unestablished.",
                    payload={"summary": report["summary"], "control": record, "limitations": report["limitations"]}, provenance_id=provenance["id"])
                artifacts.put_bytes(serialized.encode(), candidate_id=cid, artifact_key=EXPERIMENT + ":report", kind="report",
                    filename="detection-control-experiment.json", media_type="application/json",
                    metadata={"experiment": EXPERIMENT, "provenance_id": provenance["id"]})
    return {"report_path": str(report_path), **report["summary"]}
