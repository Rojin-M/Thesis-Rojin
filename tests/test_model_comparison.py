"""Real checkpoint inference, immutable evidence, receipt failure and service bounds."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.experiments.mission_adaptation import run_suite
from scripts.research.artifacts import ArtifactStore
from scripts.research.model_comparison import ComparisonScorer, compare_candidates, serve_comparisons, ARMS
from scripts.research.protocol import load_protocol
from scripts.research.reports import dossier, markdown_report
from scripts.research.scoring import NORMALIZER, NORMALIZER_SHA
from scripts.research.store import Store
from tests.test_mission_adaptation import synthetic_data


@unittest.skipUnless(NORMALIZER.exists(), "Requires the retained shared_v1 normalizer")
class ModelComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.output = cls.root / "model_experiments" / "test-five-arms"
        result = run_suite({"seeds": [42], "arms": list(ARMS), "steps": 2, "pretrain_steps": 1,
            "eval_every": 2, "batch_size": 4, "bootstrap_repeats": 20,
            "max_seconds": 90, "invocation_seconds": 90}, cls.output, synthetic_data(),
            {"cohort": "synthetic_training_fixture", "normalizer_sha256": NORMALIZER_SHA})
        cls.spec = result["spec_sha256"]
        cls.scorer = ComparisonScorer(cls.root / "model_experiments", "test-five-arms", cls.spec)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / "research.sqlite3").initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.artifacts = ArtifactStore(self.folder / "artifacts", self.store)
        source = self.store.register_provenance(kind="fixture", identity="comparison-test",
            sha256_digest="a" * 64, retrieved_at="2000-01-01T00:00:00Z")
        job = self.store.create_job(job_key="comparison-test", cohort="synthetic_fixture",
            protocol_id=self.protocol["id"], code_provenance_id=source["id"], inputs={"synthetic": True})
        for name in self.protocol["document"]["stages"]:
            claim = self.store.claim_stage(job["id"], name, worker="fixture")
            self.store.finish_stage(claim["lease_token"], result={"synthetic": True})
        candidate = self.store.put_candidate(job_id=job["id"], signal_key="synthetic-comparison",
            target_id="SYNTHETIC-001", mission="TESS", period_days=3., epoch=1500., epoch_system="BTJD",
            duration_hours=3., detection={"method": "synthetic", "ephemeris_origin": "synthetic_fixture"},
            provenance_id=source["id"])
        self.cid = candidate["id"]
        self.store.put_evidence(candidate_id=self.cid, evidence_key="fixture-score", kind="model_score",
            state="complete", summary="Synthetic reference value, not a real model inference", provenance_id=source["id"],
            payload={"score": .27, "model_sha256": "a" * 64, "normalization_sha256": NORMALIZER_SHA,
                     "input_contract": "shared_v1"})
        rng = np.random.default_rng(91)
        g = rng.normal(size=(1, 200, 3)).astype(np.float32)
        l = rng.normal(size=(1, 100, 3)).astype(np.float32)
        g[:, :, 2] = 1.; l[:, :, 2] = 1.
        s = rng.normal(size=(1, 7)).astype(np.float32)
        self.arrays = {"X_global": g, "X_local": l, "X_scalar": s,
                       "X": np.concatenate([g.transpose(0, 2, 1).reshape(1, -1),
                                            l.transpose(0, 2, 1).reshape(1, -1), s], axis=1)}
        stream = io.BytesIO(); np.savez_compressed(stream, **self.arrays)
        self.artifacts.put_bytes(stream.getvalue(), candidate_id=self.cid,
            artifact_key="blind_shared_v1:raw", kind="data", filename="fixture-input.npz")

    def test_actual_five_arm_inference_preserves_reference_review_and_replay(self):
        before = self.store.get_candidate(self.cid)
        self.store.review_candidate(self.cid, status="on_hold", reviewer="test reviewer",
                                    note="Await pixel checks", expected_revision=0)
        outcome = compare_candidates(self.store, self.artifacts, self.scorer, [self.cid])
        self.assertEqual(outcome["compared"], [self.cid])
        candidate = self.store.get_candidate(self.cid)
        e = next(e for e in candidate["evidence"] if e["kind"] == "model_comparison")
        self.assertEqual(set(e["payload"]["by_arm"]), set(ARMS))
        for row in e["payload"]["by_arm"].values():
            self.assertTrue(0 <= row["mean_score"] <= 1)
            self.assertEqual(row["mean_score"], row["seeds"][0]["score"])
        self.assertEqual(candidate["assessment"], before["assessment"])
        self.assertEqual(candidate["review_status"], "on_hold")
        again = compare_candidates(self.store, self.artifacts, self.scorer, [self.cid])
        self.assertEqual(again, {"compared": [], "already_complete": [self.cid]})
        self.assertEqual(len(self.store.get_candidate(self.cid)["evidence_history"]), len(candidate["evidence_history"]))
        report = markdown_report(dossier(self.store, self.cid))
        self.assertIn("Experimental model comparison", report)
        self.assertIn("not planet probabilities", report)

    def test_pending_selection_does_not_repeat_completed_comparison(self):
        self.assertIn(self.cid, compare_candidates(self.store, self.artifacts, self.scorer)["compared"])
        self.assertEqual(compare_candidates(self.store, self.artifacts, self.scorer)["compared"], [])

    def test_wrong_pin_and_changed_checkpoint_fail_before_inference(self):
        with self.assertRaisesRegex(ValueError, "explicit pin"):
            ComparisonScorer(self.root / "model_experiments", "test-five-arms", "0" * 64)
        path = self.output / "dann-seed42" / "best_model.pt"
        original = path.read_bytes()
        try:
            path.write_bytes(original[:-1])
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                ComparisonScorer(self.root / "model_experiments", "test-five-arms", self.spec)
        finally:
            path.write_bytes(original)

    def test_corrupt_feature_is_not_scored_or_recorded(self):
        record = next(a for a in self.store.get_candidate(self.cid)["artifacts"]
                      if a["artifact_key"] == "blind_shared_v1:raw")
        self.artifacts._path(record["sha256"]).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            compare_candidates(self.store, self.artifacts, self.scorer, [self.cid])
        self.assertFalse(any(e["kind"] == "model_comparison" for e in self.store.get_candidate(self.cid)["evidence"]))

    def test_batch_bound_rejected(self):
        with self.assertRaisesRegex(ValueError, "1–60"):
            compare_candidates(self.store, self.artifacts, self.scorer, limit=61)

    def test_concurrent_manual_batch_cannot_duplicate_service_writes(self):
        import fcntl
        with self.store.path.with_suffix(".model-comparison-batch.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "Another comparison batch"):
                compare_candidates(self.store, self.artifacts, self.scorer, [self.cid])

    def test_newly_finished_job_is_picked_up_by_next_pending_pass(self):
        job_id = self.store.get_candidate(self.cid)["job_id"]
        # Simulate the database states either side of the existing worker's completion.
        with self.store.connection(True) as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        self.assertEqual(compare_candidates(self.store, self.artifacts, self.scorer)["compared"], [])
        with self.store.connection(True) as db:
            db.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (job_id,))
        self.assertEqual(compare_candidates(self.store, self.artifacts, self.scorer)["compared"], [self.cid])

    def test_service_stops_after_three_failures_and_records_error(self):
        with patch("threading.Event.wait", return_value=False), patch(
                "scripts.research.model_comparison.compare_candidates", side_effect=RuntimeError("fixture inference failure")) as compute:
            with self.assertRaisesRegex(RuntimeError, "three failed"):
                serve_comparisons(self.store, self.artifacts, self.scorer)
        self.assertEqual(compute.call_count, 3)
        state = json.loads((self.folder / "model-comparison-service.json").read_text())
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["consecutive_failures"], 3)
        self.assertIn("fixture inference failure", state["error"]["message"])
