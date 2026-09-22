"""Resume blind proposals through features, actual CNN inference and human dossiers."""
import io
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from scripts.vetting.registry import Candidate, assess_candidate
from .bounded import bounded_call
from .contracts import validate_shared_inputs
from .diagnostics import VERSION as DIAGNOSTICS_VERSION, native_evidence, transit_diagnostics
from .features import VERSION as FEATURE_VERSION, build_features
from .interpretation import review_flags
from .protocol import ROOT, ConflictError, ValidationError, canonical_json, digest, utc_now
from .provenance import code_snapshot
from .registry_cache import fetch_bundle
from .reports import dossier, markdown_report
from .scoring import FrozenScorer, CHECKPOINT_SHA, NORMALIZER_SHA

VERSION = "scoring_vetting_v1"
DEFAULT_CACHE = ROOT / "outputs/research/registry"


def _artifact(candidate, key):
    return next((a for a in candidate["artifacts"] if a["artifact_key"] == key), None)


def read_npz(artifacts, record):
    if record is None:
        raise ValidationError("Required persisted array artifact is missing")
    _, payload = artifacts.read(record["id"])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 64 * 1024 ** 2:
            raise ValidationError("Expanded feature/diagnostic arrays exceed 64 MiB")
    with np.load(io.BytesIO(payload), allow_pickle=False) as values:
        return {key: values[key] for key in values.files}


def _save_arrays(artifacts, candidate_id, key, filename, arrays, token, metadata):
    out = io.BytesIO()
    np.savez_compressed(out, **arrays)
    return artifacts.put_bytes(out.getvalue(), candidate_id=candidate_id, artifact_key=key, kind="data",
                               filename=filename, lease_token=token, metadata=metadata)


def _evidence(store, cid, key, kind, state, summary, payload, provenance_id, token=None):
    return store.put_evidence(candidate_id=cid, evidence_key=key, kind=kind, state=state,
                             summary=summary, payload=payload, provenance_id=provenance_id, lease_token=token)


def _catalog_bundle(cache_root, tic, mode, force=False, heartbeat=None):
    try:
        return bounded_call(fetch_bundle, cache_root, tic, mode, force, seconds=180, heartbeat=heartbeat)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        # The report still records a failed lookup if the owned network process
        # times out. Bytes consumed before a hard kill cannot be called zero.
        return {"snapshots": [], "checked_at": utc_now(), "cache_error": str(exc),
                "lookup_failure": {"code": type(exc).__name__, "message": str(exc), "retryable": True},
                "downloaded_bytes_this_call": None, "maximum_download_bytes_this_call": 64 * 1024 ** 2}


def registry_report(store, artifacts, candidate, bundle, token=None, code=None, assessed_at=None):
    cid = candidate["id"]
    if candidate["cohort"] == "synthetic_fixture" or candidate["mission"] != "TESS":
        reason = ("Synthetic/transformed controls are not registry discovery searches" if candidate["cohort"] == "synthetic_fixture"
                  else "Current checker requires a verified TIC identity; KIC-to-TIC resolution is not implemented")
        report = {"status": "INCOMPLETE_LOOKUP", "coverage": "NONE", "required_sources_complete": False,
                  "summary": reason, "sources": [], "matches": [], "candidate_id": cid,
                  "generated_at_utc": assessed_at or candidate["job"]["created_at"], "retryable": False,
                  "scope_missing": ["coordinate_matches", "TCE_catalog", "eclipsing_binary_catalog", "literature_search"]}
        snapshots = []
    else:
        eph = candidate["ephemeris"]
        snapshots = bundle["snapshots"]
        report = assess_candidate(Candidate(candidate["target_id"], eph["period_days"], eph["epoch_bjd_tdb"],
                                             eph["duration_hours"], candidate_id=cid), snapshots,
                                  generated_at_utc=bundle.get("checked_at") or assessed_at or utc_now())
        report.update(required_sources_complete=report["coverage"] == "COMPLETE",
                      retryable=report["coverage"] != "COMPLETE", ttl_seconds=bundle.get("ttl_seconds"),
                      cache_error=bundle.get("cache_error"),
                      lookup_failure=bundle.get("lookup_failure"),
                      scope_missing=["coordinate_matches", "TCE_catalog", "eclipsing_binary_catalog", "literature_search"])
    report["human_review_required"] = True
    report["interpretation"] = "Catalog identity evidence only. UNMATCHED is not proof of novelty; even a known-planet match does not confirm this proposal."
    signature = digest(report)
    key = "registry_v1:" + signature
    previous = next((e for e in candidate["evidence_history"] if e["evidence_key"] == key), None)
    if previous:
        return previous
    provenance = store.register_provenance(kind="registry_assessment", identity=cid + ":" + signature,
        sha256_digest=signature, retrieved_at=report["generated_at_utc"], details={"assessment": report,
            "code": code or code_snapshot(), "raw_snapshot_hashes": [s.payload_sha256 for s in snapshots if s.payload_sha256]})
    for snapshot in snapshots:
        if snapshot.raw_payload:
            artifacts.put_bytes(snapshot.raw_payload, candidate_id=cid,
                artifact_key="catalog_raw:" + snapshot.source_id + ":" + digest(snapshot.to_dict()),
                kind="catalog_snapshot", filename=snapshot.source_id + (".csv" if snapshot.source_id.startswith("exofop") else ".json"),
                media_type="text/csv" if snapshot.source_id.startswith("exofop") else "application/json",
                metadata=snapshot.to_dict(), lease_token=token)
    artifacts.put_bytes((canonical_json(report) + "\n").encode(), candidate_id=cid, artifact_key=key,
                        kind="report", filename="registry-" + signature[:12] + ".json", media_type="application/json",
                        metadata={"provenance_id": provenance["id"], "scope": "supported_TIC_catalogs"}, lease_token=token)
    return _evidence(store, cid, key, "registry", "complete" if report["required_sources_complete"] else "incomplete",
                     report["status"] + ": " + report["summary"], report, provenance["id"], token)


def _stage(store, job_id, name, run, operation):
    claim = store.claim_stage(job_id, name, worker=VERSION)
    if claim is None:
        return next(s["result"] for s in store.get_job(job_id)["stages"] if s["name"] == name)
    token = claim["lease_token"]
    last = [time.monotonic()]
    def heartbeat():
        if time.monotonic() - last[0] > 30:
            store.heartbeat(token); last[0] = time.monotonic()
    try:
        result = operation(token, heartbeat)
        result["processing_provenance_id"] = run["provenance_id"]
        store.finish_stage(token, result=result)
        return result
    except Exception as exc:
        store.finish_stage(token, error={"code": type(exc).__name__, "message": str(exc)[:1900] or type(exc).__name__,
                                        "retryable": isinstance(exc, (OSError, TimeoutError))})
        raise


def run_vetting(store, artifacts, job_id, *, scorer=None, cache_root=DEFAULT_CACHE,
                catalog_mode="offline", feature_seconds=300, bundles=None):
    job = store.get_job(job_id)
    stages = {s["name"]: s for s in job["stages"]}
    if stages["dossier"]["status"] == "succeeded":
        return {"job_id": job_id, "already_complete": True, "result": stages["dossier"]["result"]}
    if stages["detection"]["status"] != "succeeded":
        raise ConflictError("Scoring requires a completed blind detection stage")
    if catalog_mode not in ("offline", "live") or not 1 <= feature_seconds <= 300:
        raise ValidationError("Invalid catalog mode or bounded feature deadline")
    # Read only the IDs already published by this detector, never an archive scan.
    ids = stages["detection"]["result"]["candidate_ids"]
    if len(ids) > 3:
        raise ValidationError("At most three proposals per job")
    snapshot = code_snapshot()
    spec = {"worker": VERSION, "source": snapshot, "checkpoint_sha256": CHECKPOINT_SHA,
            "normalizer_sha256": NORMALIZER_SHA, "feature_seconds": feature_seconds,
            "catalog_mode": catalog_mode, "cache_root": str(Path(cache_root).resolve()), "device": "cpu",
            "batch_size": scorer.batch_size if scorer is not None else 32}
    run = store.freeze_processing_run(job_id, VERSION, spec)
    provenance_id = run["provenance_id"]
    bundles = {} if bundles is None else bundles
    def candidates():
        return [store.get_candidate(cid) for cid in ids]
    def evidence(cid, kind, state, summary, payload, token):
        return _evidence(store, cid, VERSION + ":" + kind, kind, state, summary, payload, provenance_id, token)

    def features(token, heartbeat):
        if not ids:
            return {"candidate_ids": [], "feature_count": 0, "reason": "No detected proposals"}
        result = bounded_call(build_features, job["inputs"], candidates(), seconds=feature_seconds, heartbeat=heartbeat)
        common = {k: v for k, v in result.items() if k != "candidates"}
        accepted = []
        for item in result["candidates"]:
            cid = item["candidate_id"]
            arrays = item.pop("arrays", None)
            if arrays is not None:
                receipt = _save_arrays(artifacts, cid, FEATURE_VERSION + ":raw", "shared-v1-raw-inputs.npz", arrays, token,
                    {"normalizer_applied": False, "contract": "shared_v1", "ephemeris_source": "blind_inferred", "processing_provenance_id": provenance_id})
                item["raw_artifact_id"] = receipt["id"]
                for key, bins in (("X_global", 200), ("X_local", 100)):
                    half = .5 if bins == 200 else item["diagnostics"]["local_half_window"]
                    x = np.linspace(-half, half, bins, endpoint=False) + half / bins
                    artifacts.put_plot({"kind": "phase_folded", "title": "CNN input · " + key + " · robust scaled, before frozen normalization",
                        "x_label": "Orbital phase (cycles)", "y_label": "Robust scaled flux", "x": x.tolist(), "y": arrays[key][0, :, 0].tolist()},
                        candidate_id=cid, artifact_key=FEATURE_VERSION + ":" + key, filename=key + ".json",
                        lease_token=token, metadata={"full_points": bins, "preview_points": bins, "coverage_in_npz": True})
                accepted.append(cid)
            evidence(cid, "shared_inputs", "complete" if arrays is not None else "incomplete",
                     "Shared_v1 input constructed from blind ephemerides." if arrays is not None else "Feature construction unavailable: " + item["reason"] + "; proposal retained for review.",
                     {**common, **item}, token)
        return {"candidate_ids": ids, "feature_count": len(accepted), "accepted_ids": accepted,
                "unscorable_ids": [cid for cid in ids if cid not in accepted]}
    feature_result = _stage(store, job_id, "features", run, features)

    def scoring(token, heartbeat):
        nonlocal scorer
        selected, batches = [], []
        for c in candidates():
            if c["id"] in feature_result.get("accepted_ids", []):
                arrays = read_npz(artifacts, _artifact(c, FEATURE_VERSION + ":raw"))
                validate_shared_inputs(arrays)
                selected.append(c); batches.append(arrays)
            else:
                evidence(c["id"], "model_score", "incomplete", "No valid shared input; no score invented. Human review remains available.",
                         {"reason": "shared_input_incomplete", "ml_hard_veto": False}, token)
        if not selected:
            return {"scored_ids": [], "unscorable_ids": ids}
        scorer = scorer or FrozenScorer()
        arrays = {key: np.concatenate([batch[key] for batch in batches]) for key in batches[0]}
        prediction = scorer.predict(arrays)
        for index, c in enumerate(selected):
            norms = {key: value[index:index + 1] for key, value in prediction["normalized"].items()}
            receipt = _save_arrays(artifacts, c["id"], VERSION + ":normalized", "shared-v1-normalized-inputs.npz", norms, token,
                {"normalization_sha256": NORMALIZER_SHA, "input_contract": "shared_v1"})
            evidence(c["id"], "model_score", "complete", "Actual frozen Kepler CNN sigmoid ranking score; uncalibrated for blind proposals.",
                {**scorer.manifest, "score": prediction["scores"][index], "logit": prediction["logits"][index],
                 "normalized_artifact_id": receipt["id"], "scalar_z_scores": norms["x_scalar"][0].tolist(),
                 "domain_warning": "Inferred ephemerides, proposal masks and product coverage differ from labelled benchmark inputs; TRAIN-star controls do not measure generalization."}, token)
        return {"scored_ids": [c["id"] for c in selected], "unscorable_ids": feature_result.get("unscorable_ids", []),
                "model_sha256": CHECKPOINT_SHA, "normalization_sha256": NORMALIZER_SHA, "batch_count": int(np.ceil(len(selected) / scorer.batch_size))}
    score_result = _stage(store, job_id, "scoring", run, scoring)

    def diagnostics(token, heartbeat):
        for c in candidates():
            arrays = read_npz(artifacts, _artifact(c, "blind_bls_v1:lightcurve-arrays"))
            detection = next(e["payload"] for e in c["evidence"] if e["kind"] == "detection")
            state, payload = transit_diagnostics(c, arrays, detection)
            evidence(c["id"], "transit_diagnostics", state, "Covered-event odd/even depths, bounded secondary scan, sampling and fixed-epoch harmonic comparisons; errors are descriptive.", payload, token)
            scan = [r for r in payload["secondary_scan"]["samples"] if r["snr"] is not None]
            if len(scan) >= 2:
                artifacts.put_plot({"kind": "diagnostic", "title": "Secondary phase scan · uncorrected for trials and red noise",
                    "x_label": "Secondary phase (cycles)", "y_label": "White-noise depth S/N",
                    "x": [r["phase"] for r in scan], "y": [r["snr"] for r in scan]}, candidate_id=c["id"],
                    artifact_key=DIAGNOSTICS_VERSION + ":secondary", filename="secondary-phase-scan.json", lease_token=token)
            native = native_evidence(job["inputs"], c)
            for kind in ("centroid", "contamination"):
                evidence(c["id"], kind, native[kind]["state"],
                         "Available native light-curve measurements retained; image/source localization and aperture tests remain incomplete.", native[kind], token)
            bundle = None
            if c["cohort"] != "synthetic_fixture" and c["mission"] == "TESS":
                tic = c["target_id"]
                if tic not in bundles:
                    bundles[tic] = _catalog_bundle(cache_root, tic, catalog_mode, heartbeat=heartbeat)
                bundle = bundles[tic]
            registry_report(store, artifacts, c, bundle, token, snapshot, run["created_at"])
            evidence(c["id"], "review_priority", "complete", "Review retained for every proposal, including low scores, unusual signals and missing evidence.",
                     review_flags(store.get_candidate(c["id"])), token)
            heartbeat()
        return {"candidate_ids": ids, "complete_evidence_is_not_validation": True,
                "registry_mode": catalog_mode, "image_diagnostics": "incomplete"}
    _stage(store, job_id, "diagnostics", run, diagnostics)

    def dossiers(token, heartbeat):
        reports = []
        for c in candidates():
            # Snapshot once: a crash between writing JSON and Markdown reuses
            # identical JSON, so timestamps/stage transitions cannot conflict.
            key = VERSION + ":dossier-json"
            old = _artifact(c, key)
            if old:
                document = json.loads(artifacts.read(old["id"])[1])
            else:
                document = dossier(store, c["id"])
                document["snapshot_note"] = "Captured during dossier stage; API exports always show current stage and refreshed evidence."
                old = artifacts.put_bytes(canonical_json(document).encode(), candidate_id=c["id"], artifact_key=key,
                    kind="report", filename="candidate-dossier.json", media_type="application/json", lease_token=token)
            md = artifacts.put_bytes(markdown_report(document).encode(), candidate_id=c["id"], artifact_key=VERSION + ":dossier-md",
                kind="report", filename="candidate-dossier.md", media_type="text/markdown", lease_token=token)
            reports.append({"candidate_id": c["id"], "json_artifact_id": old["id"], "markdown_artifact_id": md["id"]})
        return {"reports": reports, "all_proposals_retained": True, "scientific_validation": False}
    result = _stage(store, job_id, "dossier", run, dossiers)
    return {"job_id": job_id, "scoring": score_result, "result": result}


def refresh_registry(store, artifacts, candidate_ids, *, mode="offline", cache_root=DEFAULT_CACHE, force=False):
    ids = list(dict.fromkeys(candidate_ids))
    if not 1 <= len(ids) <= 60:
        raise ValidationError("Registry batch accepts 1–60 explicit proposals")
    candidates = [store.get_candidate(cid) for cid in ids]
    targets = {c["target_id"] for c in candidates if c["mission"] == "TESS" and c["cohort"] != "synthetic_fixture"}
    if len(targets) > 20:
        raise ValidationError("At most 20 explicit TIC targets per registry batch")
    bundles, outcomes, code = {}, [], code_snapshot()
    for c in candidates:
        bundle = None
        if c["mission"] == "TESS" and c["cohort"] != "synthetic_fixture":
            tic = c["target_id"]
            if tic not in bundles:
                bundles[tic] = _catalog_bundle(cache_root, tic, mode, force)
            bundle = bundles[tic]
        outcome = registry_report(store, artifacts, c, bundle, code=code)
        outcomes.append({"candidate_id": c["id"], "evidence_id": outcome["id"], "state": outcome["state"],
                         "status": outcome["payload"]["status"]})
    return {"mode": mode, "targets": len(targets), "outcomes": outcomes,
            "downloaded_bytes_known": sum(b.get("downloaded_bytes_this_call") or 0 for b in bundles.values()),
            "download_byte_counts_incomplete": any(b.get("downloaded_bytes_this_call") is None for b in bundles.values()),
            "retry": "Use --force on a bounded refresh to retry missing sources; never converts failure to UNMATCHED"}
