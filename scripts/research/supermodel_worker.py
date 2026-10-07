"""Bounded, restartable v2 shadow scoring and append-only primary promotion.

The detector and retained reference scorer continue independently. This worker
consumes only completed blind proposals and never changes reviews or catalogs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import signal
import threading
import time

import numpy as np

from .artifacts import ArtifactStore
from .bounded import bounded_call
from .protocol import ROOT, ValidationError, canonical_json, digest, utc_now
from .provenance import file_sha256
from .scoring import CHECKPOINT_SHA
from .store import Store
from .supermodel import RELEASE, MODEL_NAME, MODEL_SHA256, EXPERT_NAMES, SupermodelScorer
from .vetting_worker import read_npz
from .watcher_store import WatchStore, exclusive_lock

VERSION = "blind_supermodel_worker_v1"
KIND = "supermodel_v2"
FEATURE_KEY = "blind_shared_v1:raw"


class StopRequested(Exception):
    """Leave interrupted inputs pending, rather than publishing a failed score."""


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def blind_metadata(candidate):
    if candidate["mission"] != "TESS" or candidate["cohort"] == "synthetic_fixture":
        raise ValidationError("Primary v2 is restricted to real TESS proposals")
    detection = candidate["detection"]
    if detection.get("ephemeris_origin") != "blind_search" or detection.get("used_catalog_ephemeris") is not False:
        raise ValidationError("V2 watcher inputs require blind inferred ephemerides")
    eph = candidate["ephemeris"]
    return {"candidate_id": candidate["id"], "period_days": eph["period_days"],
            "epoch_bjd_tdb": eph["epoch_bjd_tdb"], "duration_hours": eph["duration_hours"]}


def acquire_pixels(db_path, lightcurve_path, target, allow_download):
    """Use exact matching native TPF; every new GET is charged to watcher budget."""
    import requests
    from scripts.experiments.tls_pixel_pilot import _head, _download
    from .pixels import target_pixel_product

    product = target_pixel_product(lightcurve_path)
    if product["tic_id"] != target:
        raise ValidationError("TPF target and proposal disagree")
    path = ROOT / "data/raw/tess/target_pixels" / ("TIC" + target) / product["filename"]
    receipt_path = ROOT / "data/raw/tess/metadata/target_pixel_receipts" / (product["filename"] + ".json")
    if path.exists() and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("sha256") != file_sha256(path) or receipt.get("size_bytes") != path.stat().st_size
                or receipt.get("data_uri") != product["data_uri"]):
            raise ValidationError("Cached TPF receipt mismatch")
        return str(path), receipt
    if not allow_download:
        raise ValidationError("Matching target pixels are not cached; download is disabled")
    config = {"target_pixel_root": "data/raw/tess/target_pixels",
              "receipt_root": "data/raw/tess/metadata/target_pixel_receipts",
              "max_product_bytes": 320 * 1024**2}
    store = Store(db_path)
    ledger = WatchStore(store)
    with requests.Session() as session:
        plan = _head(session, {"target_id": target, "product_path": lightcurve_path}, config)
        with store.connection() as db:
            cap = db.execute("SELECT cap FROM watch_budget WHERE id=1").fetchone()[0]
            used = db.execute("SELECT COALESCE(SUM(COALESCE(used,cap)),0) FROM watch_spending").fetchone()[0]
        # Leave room for ongoing LC polling; reserve() enforces the atomic cap too.
        if used + plan["size_bytes"] + 128 * 1024**2 > cap:
            raise ValidationError("Pixel download would consume the retained 128 MiB watcher reserve")
        reservation = ledger.reserve(plan["size_bytes"], "supermodel_target_pixels")
        try:
            path, receipt, downloaded = _download(session, plan,
                {"target_id": target, "product_path": lightcurve_path}, config)
            ledger.settle(reservation, receipt["size_bytes"] if downloaded else 0, receipt)
        except Exception as exc:
            # A timeout/partial transfer is conservatively charged at its cap.
            ledger.settle(reservation, plan["size_bytes"], {"error": type(exc).__name__ + ": " + str(exc)},
                          status="failed_conservative")
            raise
    return str(path), receipt


def compute_physical(inputs, proposal, siblings, pixel_path, pixel_receipt, config):
    """Exact frozen physical transforms, substituting blind for catalog timing."""
    from scripts.experiments.physical_experts import FEATURES, _masked_for_siblings, _tls_features, _pixel_features
    from .lightcurves import read_lightcurves, detrend
    from .pixels import read_target_pixels, difference_image_diagnostics
    from .tls_search import search_tls

    selected = min(inputs["paths"], key=lambda path: Path(path).name)
    curve = read_lightcurves([selected], mission="TESS", target_id=inputs["target_id"],
                            time_system=inputs.get("time_system"), expected_hashes=inputs["sha256"])
    cadence = curve.sources[0].get("native_cadence_days")
    if cadence is None or abs(cadence * 86400 - 120) > 2:
        raise ValidationError("V2 primary requires native 120-second SPOC light curves")
    flat, _ = detrend(curve)
    candidate_flat = _masked_for_siblings(flat, proposal, siblings)
    row = {name: 0. for names in FEATURES.values() for name in names}
    row.update(tls_available=False, pixel_available=False)
    details = {"ephemeris_source": "blind_proposals_only", "used_catalog_ephemeris": False,
               "selected_lightcurve": selected, "source_sha256": inputs["sha256"][selected],
               "proposal": proposal, "siblings": siblings, "cadence_seconds": cadence * 86400,
               "physical_config": config, "pixel_receipt": pixel_receipt}
    try:
        tls = search_tls(candidate_flat, **{**config, "period_max_days": min(config["period_max_days"], float(np.ptp(candidate_flat.time)) / 2)})
        row.update(_tls_features(tls, proposal))
        details["tls"] = tls
    except Exception as exc:
        details["tls_error"] = type(exc).__name__ + ": " + str(exc)
    if pixel_path is not None:
        try:
            pixels = read_target_pixels(pixel_path, inputs["target_id"])
            if pixels.sha256 != pixel_receipt["sha256"]:
                raise ValidationError("TPF changed after acquisition")
            result = difference_image_diagnostics(pixels, {
                "period_days": proposal["period_days"], "epoch_btjd": proposal["epoch_bjd_tdb"] - 2457000.,
                "duration_hours": proposal["duration_hours"]})
            row.update(_pixel_features(result))
            details["pixels"] = {key: value for key, value in result.items() if key != "maps"}
        except Exception as exc:
            details["pixel_error"] = type(exc).__name__ + ": " + str(exc)
    else:
        details["pixel_error"] = "Matching pixel product unavailable"
    return {"features": row, "details": details}


def latest_shadow(candidate, release_id):
    rows = [e for e in candidate["evidence_history"] if e["kind"] == KIND and e["payload"].get("release_id") == release_id]
    return rows[-1] if rows else None


def primary_eligible(candidate, shadow):
    """Promotion checks do not trust a single precomputed eligibility flag."""
    payload = shadow["payload"]
    available = payload.get("expert_available", {})
    source = next((a for a in candidate["artifacts"] if a["artifact_key"] == FEATURE_KEY), None)
    return (shadow["candidate_id"] == candidate["id"] and shadow["state"] == "complete"
                and payload.get("eligible_for_primary") is True and set(available) == set(EXPERT_NAMES)
                and payload.get("model_name") == MODEL_NAME and payload.get("model_sha256") == MODEL_SHA256
                and all(value is True for value in available.values())
                and payload.get("ephemeris_source") == "blind_inferred"
                and payload.get("used_catalog_ephemeris") is False
                and candidate["mission"] == "TESS" and candidate["cohort"] != "synthetic_fixture"
                and candidate["detection"].get("ephemeris_origin") == "blind_search"
                and candidate["detection"].get("used_catalog_ephemeris") is False
                and source is not None and payload.get("input_artifact_id") == source["id"]
                and payload.get("input_sha256") == source["sha256"])


def apply_primary(store, candidate, shadow, provenance_id):
    """Append a primary score or explicit CNN fallback; never overwrite history."""
    payload = shadow["payload"]
    eligible = primary_eligible(candidate, shadow)
    key = VERSION + (":primary:" if eligible else ":fallback:") + shadow["id"]
    if any(e["evidence_key"] == key for e in candidate["evidence_history"]):
        return "already_published"
    if eligible:
        value = {**payload, "score_role": "primary", "shadow_evidence_id": shadow["id"]}
        summary = "Supermodel v2 primary ranking; eleven verified experts using blind inferred timing. Not a planet probability."
    else:
        references = [e for e in candidate["evidence_history"] if e["kind"] == "model_score" and e["state"] == "complete"
                      and e["payload"].get("model_sha256") == CHECKPOINT_SHA]
        if not references:
            return "no_reference_score"
        source = references[-1]
        reason = payload.get("reason") or "Supermodel primary input/availability checks did not pass"
        value = {**source["payload"], "score_role": "fallback", "fallback_reason": reason,
                 "reference_evidence_id": source["id"], "supermodel_evidence_id": shadow["id"]}
        summary = "Retained reference CNN fallback: supermodel inputs/inference unavailable. " + reason
    store.put_evidence(candidate_id=candidate["id"], evidence_key=key, kind="model_score", state="complete",
                       summary=summary[:3900], payload=value, provenance_id=provenance_id)
    return "primary" if eligible else "fallback"


def pending_ids(store, release_id, limit, *, mode, retry=False):
    with store.connection() as db:
        ids = [r[0] for r in db.execute("SELECT c.id FROM candidates c JOIN jobs j ON j.id=c.job_id "
              "WHERE c.mission='TESS' AND j.status='succeeded' AND j.cohort!='synthetic_fixture' "
              "ORDER BY CASE j.cohort WHEN 'archival_pilot' THEN 0 ELSE 1 END,c.created_at DESC,c.id")]
    chosen = []
    for cid in ids:
        c = store.get_candidate(cid)
        previous = latest_shadow(c, release_id)
        if previous:
            if retry and previous["state"] != "complete":
                attempts = sum(e["kind"] == KIND and e["payload"].get("release_id") == release_id for e in c["evidence_history"])
                if attempts >= 3:
                    continue
            elif mode == "primary":
                prefix = VERSION + (":primary:" if primary_eligible(c, previous) else ":fallback:")
                if any(e["evidence_key"] == prefix + previous["id"] for e in c["evidence_history"]):
                    continue
                if not any(e["kind"] == "model_score" and e["state"] == "complete" for e in c["evidence"]):
                    continue
            else:
                continue
        chosen.append(cid)
        if len(chosen) >= limit:
            break
    return chosen


def score_batch(store, artifacts, scorer, *, mode="shadow", candidate_ids=None, limit=3,
                allow_download=False, retry=False, seconds=300, heartbeat=None):
    if mode not in ("shadow", "primary") or type(limit) is not int or not 1 <= limit <= 60:
        raise ValidationError("Invalid supermodel batch mode/limit")
    if not 1 <= seconds <= 600:
        raise ValidationError("Physical worker deadline must be 1–600 seconds")
    ids = list(dict.fromkeys(candidate_ids)) if candidate_ids is not None else pending_ids(store, scorer.release_id, limit, mode=mode, retry=retry)
    if len(ids) > limit:
        raise ValidationError("Explicit supermodel batch exceeds limit")
    runtime = {name: file_sha256(ROOT / name) for name in
               ("scripts/research/supermodel.py", "scripts/research/supermodel_worker.py")}
    identity = {"manifest": scorer.manifest, "runtime": runtime}
    provenance = store.register_provenance(kind="supermodel_deployment", identity=VERSION,
        sha256_digest=digest(identity), retrieved_at=utc_now(), details=identity)["id"]
    outcomes = []
    for cid in ids:
        if heartbeat:
            heartbeat()
        c = store.get_candidate(cid)
        previous = latest_shadow(c, scorer.release_id)
        if previous and (not retry or previous["state"] == "complete"):
            action = apply_primary(store, c, previous, provenance) if mode == "primary" else "already_scored"
            outcomes.append({"candidate_id": cid, "action": action})
            continue
        attempt = 1 + sum(e["kind"] == KIND and e["payload"].get("release_id") == scorer.release_id for e in c["evidence_history"])
        if attempt > 3:
            outcomes.append({"candidate_id": cid, "action": "attempt_limit"})
            continue
        key = VERSION + ":" + scorer.release_id + ":" + str(attempt)
        try:
            proposal = blind_metadata(c)
            if c["job"]["status"] != "succeeded":
                raise ValidationError("Wait for the bounded detection/vetting job to complete")
            record = next((a for a in c["artifacts"] if a["artifact_key"] == FEATURE_KEY), None)
            arrays = read_npz(artifacts, record)
            inputs = c["job"]["inputs"]
            with store.connection() as db:
                sibling_ids = [r[0] for r in db.execute("SELECT id FROM candidates WHERE job_id=? ORDER BY id", (c["job_id"],))]
            if not 1 <= len(sibling_ids) <= 3:
                raise ValidationError("Only bounded three-proposal jobs are supported")
            siblings = [blind_metadata(store.get_candidate(other)) for other in sibling_ids]
            selected = min(inputs["paths"], key=lambda path: Path(path).name)
            signature = digest({"inputs": inputs["sha256"], "proposal": proposal, "siblings": siblings,
                                "array_sha256": record["sha256"], "release": scorer.release_id, "runtime": runtime})
            cache = store.path.parent / "supermodel" / "features" / (signature + ".json")
            if cache.exists():
                physical = json.loads(cache.read_text())
                if physical.get("input_signature") != signature or digest(physical["result"]) != physical.get("result_sha256"):
                    raise ValidationError("Cached supermodel features failed identity check")
                physical = physical["result"]
            else:
                pixel_path, pixel_receipt, pixel_error = None, None, None
                try:
                    pixel_path, pixel_receipt = bounded_call(acquire_pixels, str(store.path), selected,
                        c["target_id"], allow_download, seconds=180, heartbeat=heartbeat)
                except StopRequested:
                    raise
                except Exception as exc:
                    pixel_error = type(exc).__name__ + ": " + str(exc)
                physical = bounded_call(compute_physical, inputs, proposal, siblings, pixel_path, pixel_receipt,
                    scorer.release["physical"], seconds=seconds, heartbeat=heartbeat)
                physical["details"]["pixel_acquisition_error"] = pixel_error
                # Missing inputs can be retried later; only complete features are cached.
                if physical["features"]["tls_available"] and physical["features"]["pixel_available"]:
                    atomic_json(cache, {"input_signature": signature, "result": physical, "result_sha256": digest(physical)})
            meta = {"period": proposal["period_days"], "duration_hours": proposal["duration_hours"]}
            value = scorer.predict(arrays, [meta], [physical["features"]])[0]
            receipt = artifacts.put_bytes((canonical_json(physical) + "\n").encode(), candidate_id=cid,
                artifact_key=key + ":physical", kind="data", filename="supermodel-physical-inputs.json",
                media_type="application/json", metadata={"input_signature": signature, "ephemeris_source": "blind_inferred"})
            value.update(input_artifact_id=record["id"], input_sha256=record["sha256"],
                         physical_artifact_id=receipt["id"], physical_sha256=receipt["sha256"],
                         input_signature=signature, ephemeris_source="blind_inferred", used_catalog_ephemeris=False,
                         cohort=c["cohort"], runtime_sources=runtime,
                         domain_warning="Labelled benchmarks use catalog ephemerides and different coverage. This operational ranking is not validated as a planet probability.")
            state = "complete" if value["eligible_for_primary"] else "incomplete"
            if state != "complete":
                value["reason"] = "Missing experts: " + ", ".join(value["missing_experts"])
            summary = "Frozen supermodel v2 shadow score; primary eligibility requires every expert input."
        except StopRequested:
            raise
        except Exception as exc:
            state = "failed"
            value = {"release_id": scorer.release_id, "eligible_for_primary": False,
                     "reason": type(exc).__name__ + ": " + str(exc)[:1800], "ml_hard_veto": False}
            summary = "Supermodel unavailable; reference scoring and human review retained."
        shadow = store.put_evidence(candidate_id=cid, evidence_key=key, kind=KIND, state=state,
                                    summary=summary, payload=value, provenance_id=provenance)
        action = apply_primary(store, store.get_candidate(cid), shadow, provenance) if mode == "primary" else "shadow"
        outcomes.append({"candidate_id": cid, "state": state, "action": action,
                         "score": value.get("score"), "reason": value.get("reason")})
        if heartbeat:
            heartbeat()
    return {"mode": mode, "release_id": scorer.release_id, "outcomes": outcomes, "count": len(outcomes)}


def rollback(store):
    """Append original reference scores for active v2 rows; reviews are untouched."""
    with store.connection() as db:
        ids = [r[0] for r in db.execute("SELECT DISTINCT candidate_id FROM evidence WHERE kind=?", (KIND,))]
    changed = []
    for cid in ids:
        c = store.get_candidate(cid)
        model = next((e for e in c["evidence"] if e["kind"] == "model_score"), None)
        if not model or model["payload"].get("score_role") != "primary" or model["payload"].get("model_name") != "crossfit_nonlinear_supermodel_v2":
            continue
        reference = next((e for e in reversed(c["evidence_history"]) if e["kind"] == "model_score"
                          and e["state"] == "complete" and e["payload"].get("model_sha256") == CHECKPOINT_SHA), None)
        if reference:
            store.put_evidence(candidate_id=cid, evidence_key=VERSION + ":rollback:" + model["id"], kind="model_score",
                state="complete", summary="Operator rollback to retained reference CNN; previous v2 evidence preserved.",
                payload={**reference["payload"], "score_role": "fallback", "fallback_reason": "operator_rollback",
                         "reference_evidence_id": reference["id"], "rolled_back_evidence_id": model["id"]},
                provenance_id=reference["provenance_id"])
            changed.append(cid)
    return {"rolled_back": changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "outputs/research/research.sqlite3")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "outputs/research/artifacts")
    parser.add_argument("--release", type=Path, default=RELEASE)
    parser.add_argument("--mode", choices=("shadow", "primary", "rollback"), default="shadow")
    parser.add_argument("--candidate-id", action="append")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)
    if not 30 <= args.interval <= 3600 or args.watch and (args.candidate_id or args.mode == "rollback" or args.retry):
        parser.error("Use --watch for pending batches; explicit IDs/retries/rollback are one-shot")
    store = Store(args.db).initialize()
    folder = store.path.parent / "supermodel"
    folder.mkdir(parents=True, exist_ok=True)
    state = {"version": VERSION, "mode": args.mode, "state": "starting", "started_at": utc_now(), "error": None}
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    last = [0.]
    def heartbeat(force=False):
        if stop.is_set() and not force:
            raise StopRequested()
        if force or time.monotonic() - last[0] >= 10:
            state["heartbeat_at"] = utc_now()
            atomic_json(folder / "service.json", state)
            last[0] = time.monotonic()
    with exclusive_lock(folder / "worker.lock"):
        try:
            heartbeat(True)
            if args.mode == "rollback":
                result = rollback(store)
                state.update(state="rolled_back", result=result)
                print(json.dumps(result), flush=True)
                return
            import torch
            torch.set_num_threads(1)
            scorer = SupermodelScorer(args.release)
            state.update(release_id=scorer.release_id, model_name=scorer.manifest["model_name"],
                         model_sha256=scorer.manifest["model_sha256"], state="running")
            artifacts = ArtifactStore(args.artifacts, store)
            heartbeat(True)
            while not stop.is_set():
                result = score_batch(store, artifacts, scorer, mode=args.mode, candidate_ids=args.candidate_id,
                    limit=args.limit, allow_download=args.allow_download, retry=args.retry, seconds=args.seconds,
                    heartbeat=heartbeat)
                state.update(last_result=result, last_batch_at=utc_now(), state="running" if args.watch else "complete")
                heartbeat(True)
                print(json.dumps(result), flush=True)
                if not args.watch:
                    break
                state["phase"] = "waiting"
                for _ in range(args.interval):
                    if stop.wait(1):
                        break
                    heartbeat()
                state["phase"] = "scoring"
        except StopRequested:
            state["state"] = "stopped"
        except Exception as exc:
            state.update(state="failed", error=type(exc).__name__ + ": " + str(exc))
            raise
        finally:
            if stop.is_set():
                state["state"] = "stopped"
            heartbeat(True)


if __name__ == "__main__":
    main()
