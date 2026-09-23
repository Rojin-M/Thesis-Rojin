"""Verified experimental model scores alongside the retained candidate scorer.

These models never replace model_score evidence or change catalog/review labels.
Only already saved blind-search features are consumed; no training or downloads.
"""
import io
import json

import numpy as np

from .contracts import validate_shared_inputs
from .experiments import _bytes, _folder, _json, verified_summary
from .protocol import ROOT, ValidationError, digest, utc_now
from .provenance import code_snapshot
from .scoring import NORMALIZER, NORMALIZER_SHA, verified_bytes

VERSION = "blind_model_comparison_v1"
ARMS = ("tess_only", "kepler_only", "fine_tuned", "pooled", "dann")


class ComparisonScorer:
    """Load only a sealed, explicitly identified experiment and model receipts."""
    def __init__(self, root, run_id, spec_sha256):
        import torch
        from training.cnn.mission_adaptation import MissionAdaptationCNN

        folder = _folder(root, run_id)
        summary, receipt = verified_summary(folder)
        if receipt["spec_sha256"] != spec_sha256:
            raise ValidationError("Comparison experiment specification differs from the explicit pin")
        spec = _json(folder / "spec.json")
        if spec["data"].get("normalizer_sha256") != NORMALIZER_SHA:
            raise ValidationError("Comparison requires the frozen shared_v1 normalizer")
        if set(summary["config"]["arms"]) != set(ARMS):
            raise ValidationError("Comparison requires all five completed experiment arms")
        # The architecture used for inference must match the archived training source.
        for name in ("training/cnn/mission_adaptation.py", "training/cnn/train_kepler_cnn.py",
                     "scripts/data/tess_dataset.py"):
            verified_bytes(ROOT / name, spec["source_files"][name])
        with np.load(io.BytesIO(verified_bytes(NORMALIZER, NORMALIZER_SHA)), allow_pickle=False) as z:
            self.stats = {key: z[key] for key in z.files}
        self.models, records = [], []
        for arm in ARMS:
            for seed in summary["config"]["seeds"]:
                arm_folder = _folder(folder, f"{arm}-seed{seed}")
                complete = _json(arm_folder / "complete.json")
                if complete.get("spec_sha256") != spec_sha256 or set(complete.get("files", {})) != {
                        "best_model.pt", "result.json", "predictions.json"}:
                    raise ValidationError("Invalid comparison model receipt")
                for name, checksum in complete["files"].items():
                    verified_bytes(arm_folder / name, checksum)
                result = _json(arm_folder / "result.json")
                checkpoint_sha = complete["files"]["best_model.pt"]
                payload = _bytes(arm_folder / "best_model.pt", cap=64 * 1024**2)
                import hashlib
                if hashlib.sha256(payload).hexdigest() != checkpoint_sha:
                    raise ValidationError("Comparison checkpoint changed during load")
                checkpoint = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
                if (checkpoint.get("spec_sha256") != spec_sha256 or checkpoint.get("arm") != arm
                        or checkpoint.get("seed") != seed or checkpoint.get("input_contract") != "shared_v1"
                        or result.get("checkpoint_sha256") != checkpoint_sha):
                    raise ValidationError("Comparison checkpoint identity mismatch")
                model = MissionAdaptationCNN(adversarial=arm == "dann")
                model.load_state_dict(checkpoint["model_state"], strict=True)
                model.eval()
                record = {"arm": arm, "seed": seed, "checkpoint_path": str(arm_folder / "best_model.pt"),
                          "model_sha256": checkpoint_sha, "selected_update": checkpoint["step"]}
                self.models.append((record, model))
                records.append(record)
        self.manifest = {"version": VERSION, "run_id": run_id, "spec_sha256": spec_sha256,
                         "models": records, "input_contract": "shared_v1",
                         "normalization_path": str(NORMALIZER), "normalization_sha256": NORMALIZER_SHA,
                         "training_scope": "supervised_labelled_Kepler_and_TESS_comparison",
                         "aggregation": "arithmetic_mean_of_raw_sigmoid_scores_across_all_prespecified_seeds",
                         "calibration": "not_calibrated_for_blind_search",
                         "uncertainty": "seed_range_is_not_a_probability_confidence_interval",
                         "promotion": "comparison_only_reference_scorer_retained"}

    def predict(self, arrays):
        import torch
        from scripts.data.tess_dataset import apply_normalization
        validate_shared_inputs(arrays)
        normalized = apply_normalization(arrays, self.stats)
        inputs = [torch.from_numpy(normalized[k]) for k in ("x_global", "x_local", "x_scalar", "x_flat")]
        per_row = [{arm: [] for arm in ARMS} for _ in range(len(inputs[0]))]
        with torch.inference_mode():
            for record, model in self.models:
                values = model(*inputs)
                if values.shape != (len(per_row),) or not torch.isfinite(values).all():
                    raise ValidationError("Invalid comparison model output")
                for row, logit, score in zip(per_row, values.tolist(), torch.sigmoid(values).tolist()):
                    row[record["arm"]].append({"seed": record["seed"], "logit": logit, "score": score,
                                              "model_sha256": record["model_sha256"]})
        return [{arm: {"mean_score": float(np.mean([x["score"] for x in seeds])),
                       "min_score": min(x["score"] for x in seeds),
                       "max_score": max(x["score"] for x in seeds), "seeds": seeds}
                 for arm, seeds in row.items()} for row in per_row]


def compare_candidates(store, artifacts, scorer, candidate_ids=None, limit=60):
    import fcntl
    with store.path.with_suffix(".model-comparison-batch.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValidationError("Another comparison batch owns this database") from exc
        return _compare_candidates(store, artifacts, scorer, candidate_ids, limit)


def _compare_candidates(store, artifacts, scorer, candidate_ids=None, limit=60):
    """Append one immutable comparison per input/model identity; replay is a no-op."""
    from .features import VERSION as FEATURE_VERSION
    from .vetting_worker import read_npz
    if type(limit) is not int or not 1 <= limit <= 60:
        raise ValidationError("Comparison batch limit must be 1–60")
    manifest = scorer.manifest
    key_prefix = VERSION + ":" + digest(manifest) + ":"
    if candidate_ids is None:
        with store.connection() as db:
            candidate_ids = [r[0] for r in db.execute(
                "SELECT c.id FROM candidates c JOIN artifacts a ON a.candidate_id=c.id "
                "JOIN jobs j ON j.id=c.job_id WHERE a.artifact_key=? AND j.status='succeeded' "
                "AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.candidate_id=c.id AND e.evidence_key=?) "
                "ORDER BY c.created_at,c.id LIMIT ?", (FEATURE_VERSION + ":raw", key_prefix, limit))]
    candidate_ids = list(dict.fromkeys(candidate_ids))
    if len(candidate_ids) > limit:
        raise ValidationError("Too many explicit comparison candidates")
    rows, batches, skipped = [], [], []
    for cid in candidate_ids:
        candidate = store.get_candidate(cid)
        if any(e["evidence_key"] == key_prefix for e in candidate["evidence_history"]):
            skipped.append(cid)
            continue
        source = next((a for a in candidate["artifacts"] if a["artifact_key"] == FEATURE_VERSION + ":raw"), None)
        if source is None:
            raise ValidationError("Candidate has no recorded blind shared_v1 features: " + cid)
        values = read_npz(artifacts, source)
        validate_shared_inputs(values)
        if len(values["X"]) != 1:
            raise ValidationError("Each candidate must have exactly one input row")
        rows.append((candidate, source)); batches.append(values)
    if not rows:
        return {"compared": [], "already_complete": skipped}
    arrays = {k: np.concatenate([b[k] for b in batches]) for k in ("X_global", "X_local", "X_scalar", "X")}
    predictions = scorer.predict(arrays)
    if len(predictions) != len(rows):
        raise ValidationError("Comparison output count differs from candidates")
    # Register exact model identities and code once, after successful inference.
    source = {"manifest": manifest, "code": code_snapshot()}
    provenance = store.register_provenance(kind="model_comparison", identity=manifest["run_id"],
        sha256_digest=digest(source), retrieved_at=utc_now(), details=source)
    for (candidate, source), prediction in zip(rows, predictions):
        payload = {**manifest, "by_arm": prediction, "input_artifact_id": source["id"],
                   "input_sha256": source["sha256"], "cohort": candidate["cohort"],
                   "interpretation": "Experimental rankings, not planet probabilities. Known-object and synthetic controls do not establish discovery performance."}
        store.put_evidence(candidate_id=candidate["id"], evidence_key=key_prefix, kind="model_comparison",
                           state="complete", summary="Five trained model arms applied to the same saved blind-search input; reference score retained.",
                           payload=payload, provenance_id=provenance["id"])
    return {"compared": [c["id"] for c, _ in rows], "already_complete": skipped}


def serve_comparisons(store, artifacts, scorer, interval=60, limit=60):
    """Poll completed jobs locally; retain visible heartbeat/errors and a failure cap."""
    import fcntl
    import signal
    import threading
    from scripts.experiments.mission_adaptation import atomic_json

    if type(interval) is not int or not 60 <= interval <= 3600:
        raise ValidationError("Comparison poll interval must be 60–3600 seconds")
    stop = threading.Event()
    state_path = store.path.parent / "model-comparison-service.json"
    previous = {}
    with store.path.with_suffix(".model-comparison.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValidationError("A model comparison service already owns this database") from exc
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        failures = 0
        state = {"run_id": scorer.manifest["run_id"], "spec_sha256": scorer.manifest["spec_sha256"],
                 "mode": "comparison_only", "interval_seconds": interval}
        try:
            while not stop.is_set():
                state.update(state="running", heartbeat_at=utc_now(), error=None)
                atomic_json(state_path, state)
                try:
                    outcome = compare_candidates(store, artifacts, scorer, limit=limit)
                    state.update(state="waiting", result=outcome)
                    failures = 0
                except Exception as exc:
                    failures += 1
                    state.update(state="failed" if failures >= 3 else "retry_wait",
                                 error={"type": type(exc).__name__, "message": str(exc)[:1000]})
                state.update(heartbeat_at=utc_now(), consecutive_failures=failures)
                atomic_json(state_path, state)
                print(json.dumps(state), flush=True)
                if failures >= 3:
                    raise RuntimeError("Comparison service stopped after three failed batches")
                stop.wait(interval)
        finally:
            if state.get("state") != "failed":
                state.update(state="stopped", heartbeat_at=utc_now())
                atomic_json(state_path, state)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
