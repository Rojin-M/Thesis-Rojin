"""Restartable local-file detection worker publishing real research dossiers."""
from __future__ import annotations

from dataclasses import asdict
import io
from pathlib import Path
import time

import numpy as np

from .detection import VERSION, SearchConfig, bounded_search, phase_distance
from .lightcurves import MAX_INPUT_BYTES, read_lightcurves, snapshot_file
from .protocol import ConflictError, ValidationError, canonical_json, digest, utc_now
from .provenance import code_snapshot


def _stage(store, job_id, name, operation):
    claim = store.claim_stage(job_id, name, worker="local-blind-bls")
    if claim is None:
        return next(s["result"] for s in store.get_job(job_id)["stages"] if s["name"] == name)
    token = claim["lease_token"]
    try:
        result = operation(token)
        store.finish_stage(token, result=result)
        return result
    except Exception as exc:
        store.finish_stage(token, error={"code": type(exc).__name__, "message": str(exc)[:1900] or type(exc).__name__,
                                        "retryable": isinstance(exc, (OSError, TimeoutError))})
        raise


def _plot(artifacts, candidate_id, token, key, x, y, title, x_label, kind, *, metadata=None, y_label=None):
    # Show every point up to the UI cap. For larger arrays retain each bucket's
    # extrema, not a stride that could hide a short dip. Full arrays are attached.
    x, y = np.asarray(x), np.asarray(y)
    if len(x) < 2:
        return
    if len(x) > 10000:
        indices = set()
        for bucket in np.array_split(np.arange(len(x)), 5000):
            indices.add(int(bucket[np.argmin(y[bucket])]))
            indices.add(int(bucket[np.argmax(y[bucket])]))
        idx = np.array(sorted(indices))
    else:
        idx = np.arange(len(x))
    meta = {"full_points": len(x), "preview_points": len(idx),
            "preview_reduction": "ordered_bucket_min_max" if len(idx) < len(x) else "none", **(metadata or {})}
    artifacts.put_plot({"kind": kind, "title": title[:200], "x_label": x_label,
                        "y_label": y_label or ("BLS log likelihood" if kind == "periodogram" else "Relative flux"),
                        "time_system": "BTJD", "x": x[idx].tolist(), "y": y[idx].tolist()},
                       candidate_id=candidate_id, artifact_key=VERSION + ":" + key,
                       filename=key + ".json", metadata=meta, lease_token=token)


def persist_detection(store, artifacts, job, token, source_id, result):
    flat = result["flat"]
    buffer = io.BytesIO()
    np.savez_compressed(buffer, time_btjd=flat.time, flux=flat.flux, flux_err=flat.error, segment=flat.segment,
                        **result["raw"], **{f"bls_{r['iteration']}_{key}": r[key] for r in result["rounds"] for key in ("periods", "power")})
    full_arrays = buffer.getvalue()
    candidates = []
    round_summaries = [{k: v for k, v in r.items() if k not in ("periods", "power")} for r in result["rounds"]]
    for proposal in result["proposals"]:
        candidate = store.put_candidate(job_id=job["id"], signal_key=f"{VERSION}:signal-{proposal['rank']}",
            target_id=job["inputs"]["target_id"], mission=job["inputs"]["mission"],
            period_days=proposal["period_days"], epoch=proposal["epoch_btjd"], epoch_system="BTJD",
            duration_hours=proposal["duration_hours"], provenance_id=source_id, lease_token=token,
            detection={"method": VERSION, "ephemeris_origin": "blind_search", "used_catalog_ephemeris": False,
                       "rank": proposal["rank"], "search_iteration": proposal["search_iteration"],
                       "bls_log_likelihood": proposal["bls_log_likelihood"], "depth_snr_white": proposal["depth_snr_white"],
                       "depth_relative_flux": proposal["depth_relative_flux"], "experiment": job["inputs"]["experiment"],
                       "semantics": result["score_semantics"], "sampling_gate_passed": proposal["diagnostics"]["sampling_gate_passed"]})
        cid = candidate["id"]
        def evidence(kind, state, summary, payload):
            store.put_evidence(candidate_id=cid, evidence_key=VERSION + ":" + kind, kind=kind, state=state,
                               summary=summary, payload=payload, provenance_id=source_id, lease_token=token)
        evidence("lightcurve", "complete", "Quality-zero native/local photometry; blind gap-local detrending. Full arrays and source receipts attached.",
                 {**flat.metadata, "source_provenance_id": source_id, "source_products": len(flat.sources), "n_flat_samples": len(flat.time)})
        evidence("detection", "complete", "Period and epoch estimated by bounded blind BLS; a proposal is not a validated signal.",
                 {"proposal": proposal, "config": result["config"], "search_grid": result["search_grid"],
                  "astropy_version": result["astropy_version"], "numpy_version": result["numpy_version"],
                  "used_catalog_ephemeris": False, "suppressed_harmonics": result["suppressed_harmonics"], "tls": result["tls"]})
        evidence("transit_diagnostics", "incomplete", "Event coverage, odd/even event depths and phase-half secondary measured; image/contamination checks remain missing.",
                 proposal["diagnostics"])
        evidence("controls", "incomplete", "This is a labelled pilot experiment. Search completeness and false-alarm calibration are not established.",
                 {"experiment": job["inputs"]["experiment"], "search_readiness": False})
        artifacts.put_bytes(full_arrays, candidate_id=cid, artifact_key=VERSION + ":lightcurve-arrays",
                            kind="data", filename="blind-search-lightcurve.npz", metadata={
                                "time_system": "BTJD", "arrays": ["time_btjd", "flux", "flux_err", "segment", *result["raw"]],
                                "flux_semantics": "blindly detrended relative flux", "source_provenance_id": source_id,
                                "normalizer_applied": False, "not_shared_v1_model_inputs": True}, lease_token=token)
        _plot(artifacts, cid, token, "unfolded", flat.time, flat.flux,
              f"{job['inputs']['target_id']} · {job['cohort']} · blind detrending", "Time (BTJD, TDB days)", "time_series")
        _plot(artifacts, cid, token, "raw-normalized", result["raw"]["time"], result["raw"]["flux_raw_normalized"],
              "Native photometry before blind detrending · normalized for display", "Time (BTJD, TDB days)", "time_series")
        _plot(artifacts, cid, token, "trend", result["raw"]["time"], result["raw"]["trend_normalized"],
              "Blind rolling-median trend · gaps/products treated separately", "Time (BTJD, TDB days)", "time_series")
        phase = phase_distance(flat.time, proposal["period_days"], proposal["epoch_btjd"]) / proposal["period_days"]
        order = np.argsort(phase)
        _plot(artifacts, cid, token, "phase-folded", phase[order], flat.flux[order],
              "Folded at blind BLS period · all unmasked observations", "Phase (cycles)", "phase_folded")
        local = np.abs(phase * proposal["period_days"]) < proposal["duration_hours"] / 24 * 3
        _plot(artifacts, cid, token, "transit-window", phase[local] * proposal["period_days"] * 24, flat.flux[local],
              "Blind proposal · individual transit samples", "Hours from blind mid-transit", "phase_folded")
        round_data = result["rounds"][proposal["search_iteration"] - 1]
        _plot(artifacts, cid, token, "periodogram", round_data["periods"], round_data["power"],
              "Blind BLS periodogram · bounded coarse grid", "Trial period (days)", "periodogram")
        events = proposal["diagnostics"]["events"]
        sampled = [event for event in events if event["depth"] is not None]
        _plot(artifacts, cid, token, "event-depths", [e["center_btjd"] for e in sampled], [e["depth"] for e in sampled],
              "Individual-event depths (local baseline; white-noise model)", "Event center (BTJD)", "diagnostic", y_label="Transit depth (relative flux)")
        # Keep complete periodograms, aliases and diagnostics, not only previews.
        artifacts.put_bytes(canonical_json({"proposal": proposal, "rounds": round_summaries,
            "search_grid": result["search_grid"]}).encode(), candidate_id=cid, artifact_key=VERSION + ":search-report",
            kind="report", filename="blind-search-report.json", media_type="application/json", lease_token=token)
        candidates.append(cid)
    return {"version": VERSION, "candidate_ids": candidates, "proposal_count": len(candidates),
            "search_grid": result["search_grid"], "rounds": round_summaries,
            "suppressed_harmonics": result["suppressed_harmonics"], "tls": result["tls"],
            "used_catalog_ephemeris": False, "threshold_applied": False,
            "next_stage": "features", "scientific_readiness": False}


def run_local_detection(store, artifacts, protocol_id, *, paths, mission, target_id, cohort,
                        config=None, time_system=None, experiment=None, job_key=None, public_product=None):
    protocol = store.get_protocol(protocol_id)["document"]
    cfg = config or SearchConfig.from_protocol(protocol)
    # Validate even callers that bypass the CLI against this job's protocol.
    SearchConfig.from_protocol(protocol, **asdict(cfg))
    if cohort not in ("known_object_control", "archival_pilot", "synthetic_fixture"):
        raise ValidationError("Local blind-search v1 accepts only explicitly labelled controls/archival jobs")
    paths = sorted({str(Path(p).resolve()) for p in paths})
    if not 1 <= len(paths) <= min(20, protocol["limits"]["initial_products"]):
        raise ValidationError("Bounded local selection must contain 1–20 files")
    if sum(Path(p).stat().st_size for p in paths) > MAX_INPUT_BYTES:
        raise ValidationError("Local input selection exceeds 512 MiB")
    snapshots = [snapshot_file(p)[1] for p in paths]
    inputs = {"mission": mission, "target_id": str(target_id), "paths": paths,
              "sha256": {r["path"]: r["sha256"] for r in snapshots}, "time_system": time_system,
              "config": asdict(cfg), "detector_version": VERSION,
              "experiment": experiment or {"kind": "local_blind_search", "cohort": cohort},
              "selection": "explicit_local_files_no_live_discovery", "new_download_bytes": 0}
    if public_product is not None:
        inputs.update(public_product=public_product, selection="frozen_bounded_public_MAST_selection",
                      new_download_bytes=public_product["receipt"].get("new_download_bytes", 0))
    snapshot = code_snapshot()
    key = job_key or "local-bls:" + digest({"inputs": inputs, "cohort": cohort, "protocol_id": protocol_id,
                                           "code_sha256": snapshot["manifest_sha256"]})
    with store.connection() as db:
        old = db.execute("SELECT id FROM jobs WHERE job_key=?", (key,)).fetchone()
    if old:
        previous = store.get_job(old["id"])
        code_id = previous["code_provenance_id"]
        code = store.get_provenance(code_id)["document"]
        complete = next(s for s in previous["stages"] if s["name"] == "detection")["status"] == "succeeded"
        if not complete and code["sha256"] != snapshot["manifest_sha256"]:
            raise ConflictError("Code changed for unfinished job; use a new versioned job key")
    else:
        code_id = store.register_provenance(kind="code", identity="research-application-source",
            sha256_digest=snapshot["manifest_sha256"], retrieved_at=utc_now(), details=snapshot)["id"]
    job = store.create_job(job_key=key, cohort=cohort, protocol_id=protocol_id, code_provenance_id=code_id, inputs=inputs,
        release_id=public_product["release_id"] if public_product else None,
        product_id=public_product["product_id"] if public_product else None)
    _stage(store, job["id"], "metadata", lambda token: {"mode": "public_MAST_pilot" if public_product else "local_archive", "files": snapshots,
        "public_availability": public_product or "not_revalidated_by_local_search", "release_record_created": bool(public_product)})
    _stage(store, job["id"], "selection", lambda token: {"selected_products": len(paths), "selected_targets": 1,
        "rule": inputs["selection"], "cohort": cohort, "experiment": inputs["experiment"], "catalog_ephemerides_used_for_search": False})
    def acquisition(token):
        curve = read_lightcurves(paths, mission=mission, target_id=str(target_id), time_system=time_system, expected_hashes=inputs["sha256"])
        source = store.register_provenance(kind="lightcurve_bundle", identity="local-file-selection:" + digest(inputs["sha256"]),
            sha256_digest=digest(inputs["sha256"]), retrieved_at=utc_now(), details={"sources": curve.sources,
                "metadata": curve.metadata, "retrieval_semantics": "local verification time; original acquisition timestamps retained where available",
                "experiment": inputs["experiment"], "public_product": public_product})
        return {"provenance_id": source["id"], "sources": curve.sources, "quality": curve.metadata,
                "new_download_bytes": inputs["new_download_bytes"], "public_product": public_product}
    receipt = _stage(store, job["id"], "acquisition", acquisition)
    def detect(token):
        curve = read_lightcurves(paths, mission=mission, target_id=str(target_id), time_system=time_system, expected_hashes=inputs["sha256"])
        last_heartbeat = [time.monotonic()]
        def heartbeat():
            if time.monotonic() - last_heartbeat[0] > 30:
                store.heartbeat(token)
                last_heartbeat[0] = time.monotonic()
        result = bounded_search(curve, cfg, heartbeat=heartbeat)
        return persist_detection(store, artifacts, job, token, receipt["provenance_id"], result)
    result = _stage(store, job["id"], "detection", detect)
    return {"job_id": job["id"], "job_key": key, "cohort": cohort, **result}
