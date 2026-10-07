"""Deployment behavior on real temporary SQLite, independent of large checkpoints."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from scripts.research.artifacts import ArtifactStore
from scripts.research.protocol import ValidationError
from scripts.research.reports import dossier, markdown_report
from scripts.research.scoring import CHECKPOINT_SHA, NORMALIZER_SHA
from scripts.research.supermodel import load_release, MODEL_SHA256, EXPERT_NAMES
from scripts.research.supermodel_status import deployment_status
from scripts.research.supermodel_worker import (apply_primary, blind_metadata, latest_shadow,
    pending_ids, primary_eligible, rollback, score_batch, StopRequested, VERSION, KIND, FEATURE_KEY)
from tests.test_research_sorting import SortingFixture


class DeploymentTests(SortingFixture):
    def setUp(self):
        super().setUp()
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)
        self.release = "f" * 64

    def prepared(self):
        cid = self.candidate()
        with self.store.connection(True) as db:
            db.execute("UPDATE jobs SET status='succeeded'")
        reference = self.store.put_evidence(candidate_id=cid, evidence_key="original_reference",
            kind="model_score", state="complete", summary="Fixture reference", provenance_id=self.provenance,
            payload={"score": .2, "logit": -1.38629436112, "model_name": "frozen_Kepler_shared_v1_CNN_seed42",
                     "model_sha256": CHECKPOINT_SHA, "normalization_sha256": NORMALIZER_SHA, "input_contract": "shared_v1"})
        arrays = {"X_global": np.zeros((1, 200, 3), dtype=np.float32),
                  "X_local": np.zeros((1, 100, 3), dtype=np.float32),
                  "X_scalar": np.zeros((1, 7), dtype=np.float32), "X": np.zeros((1, 907), dtype=np.float32)}
        out = io.BytesIO(); np.savez(out, **arrays)
        artifact = self.artifacts.put_bytes(out.getvalue(), candidate_id=cid, artifact_key=FEATURE_KEY,
            kind="data", filename="fixture.npz")
        return cid, reference, artifact

    def shadow(self, cid, artifact, *, state="complete", **changes):
        self.evidence_serial += 1
        payload = {"model_name": "crossfit_nonlinear_supermodel_v2", "model_sha256": MODEL_SHA256,
                   "normalization_sha256": NORMALIZER_SHA, "input_contract": "shared_v1", "release_id": self.release,
                   "score": .8, "logit": 1., "eligible_for_primary": True,
                   "expert_available": dict.fromkeys(EXPERT_NAMES, True),
                   "input_artifact_id": artifact["id"], "input_sha256": artifact["sha256"],
                   "ephemeris_source": "blind_inferred", "used_catalog_ephemeris": False, **changes}
        return self.store.put_evidence(candidate_id=cid, evidence_key="shadow-" + str(self.evidence_serial),
            kind=KIND, state=state, summary="Fixture v2 shadow", payload=payload, provenance_id=self.provenance)

    def test_shadow_does_not_change_primary_then_promotion_changes_sort_and_keeps_history(self):
        cid, reference, artifact = self.prepared()
        other, _, _ = self.prepared()
        self.score(other, .5)
        shadow = self.shadow(cid, artifact)
        self.assertEqual(self.store.get_candidate(cid)["assessment"]["score"], .2)
        self.assertEqual(self.ids(sort="score_desc")[0], other)
        c = self.store.get_candidate(cid)
        self.assertEqual(apply_primary(self.store, c, shadow, self.provenance), "primary")
        c = self.store.get_candidate(cid)
        self.assertEqual(c["assessment"]["score"], .8)
        self.assertEqual(c["assessment"]["score_role"], "primary")
        self.assertEqual(self.ids(sort="score_desc")[0], cid)
        self.assertIn(reference, c["evidence_history"])
        self.assertEqual(c["review_status"], "unreviewed")
        self.assertFalse(c["review_triage"]["automatic_rejection"])
        self.assertIsNone(c["probability"]["planet_probability"])
        self.assertEqual(c["probability"]["benchmark"]["status"], "unavailable")
        self.assertEqual(apply_primary(self.store, c, shadow, self.provenance), "already_published")
        self.assertEqual(deployment_status(self.store)["score_counts"]["primary"], 1)
        self.assertIn("Supermodel v2 deployment", markdown_report(dossier(self.store, cid)))

    def test_missing_expert_or_wrong_input_cannot_promote_even_with_eligible_flag(self):
        for changes in ({"expert_available": {name: i != 3 for i, name in enumerate(EXPERT_NAMES)}},
                        {"input_sha256": "1" * 64}, {"used_catalog_ephemeris": True}, {"model_sha256": "d" * 64}):
            cid, reference, artifact = self.prepared()
            shadow = self.shadow(cid, artifact, **changes)
            self.assertFalse(primary_eligible(self.store.get_candidate(cid), shadow))
            self.assertEqual(apply_primary(self.store, self.store.get_candidate(cid), shadow, self.provenance), "fallback")
            c = self.store.get_candidate(cid)
            self.assertEqual(c["assessment"]["score"], reference["payload"]["score"])
            self.assertEqual(c["assessment"]["score_role"], "fallback")
            self.assertTrue(c["assessment"]["fallback_reason"])
            self.assertNotIn(cid, pending_ids(self.store, self.release, 60, mode="primary"))

    def test_incomplete_inputs_keep_fallback_and_can_retry_with_attempt_cap(self):
        cid, _, artifact = self.prepared()
        shadow = self.shadow(cid, artifact, state="incomplete", eligible_for_primary=False,
                             reason="Matching target pixels unavailable")
        apply_primary(self.store, self.store.get_candidate(cid), shadow, self.provenance)
        self.assertNotIn(cid, pending_ids(self.store, self.release, 60, mode="shadow"))
        self.assertIn(cid, pending_ids(self.store, self.release, 60, mode="shadow", retry=True))
        self.shadow(cid, artifact, state="failed")
        self.shadow(cid, artifact, state="failed")
        self.assertNotIn(cid, pending_ids(self.store, self.release, 60, mode="shadow", retry=True))

    def test_missing_arrays_records_failure_without_network_or_fake_primary(self):
        cid = self.candidate()
        with self.store.connection(True) as db: db.execute("UPDATE jobs SET status='succeeded'")
        scorer = SimpleNamespace(release_id=self.release, manifest={"test": True})
        with patch("scripts.research.supermodel_worker.bounded_call") as work:
            result = score_batch(self.store, self.artifacts, scorer, candidate_ids=[cid], limit=1)
        work.assert_not_called()
        self.assertEqual(result["outcomes"][0]["state"], "failed")
        c = self.store.get_candidate(cid)
        self.assertIsNone(c["assessment"]["score"])
        self.assertIn("artifact", latest_shadow(c, self.release)["payload"]["reason"])

    def test_rollback_is_append_only_idempotent_and_preserves_review(self):
        cid, reference, artifact = self.prepared()
        self.store.review_candidate(cid, status="on_hold", reviewer="fixture", note="Keep this review", expected_revision=0)
        shadow = self.shadow(cid, artifact)
        apply_primary(self.store, self.store.get_candidate(cid), shadow, self.provenance)
        before = self.store.get_candidate(cid)
        self.assertEqual(rollback(self.store)["rolled_back"], [cid])
        after = self.store.get_candidate(cid)
        self.assertEqual(after["assessment"]["score"], .2)
        self.assertEqual(after["review_status"], "on_hold")
        self.assertEqual(after["reviews"], before["reviews"])
        self.assertEqual(len(after["evidence_history"]), len(before["evidence_history"]) + 1)
        self.assertEqual(rollback(self.store)["rolled_back"], [])

    def test_catalog_timing_and_synthetic_inputs_rejected(self):
        cid, _, _ = self.prepared(); c = self.store.get_candidate(cid)
        self.assertEqual(set(blind_metadata(c)), {"candidate_id", "period_days", "epoch_bjd_tdb", "duration_hours"})
        c["detection"]["used_catalog_ephemeris"] = True
        with self.assertRaises(ValidationError): blind_metadata(c)
        c["detection"]["used_catalog_ephemeris"] = False; c["cohort"] = "synthetic_fixture"
        with self.assertRaises(ValidationError): blind_metadata(c)

    def test_operator_stop_leaves_work_pending_without_failed_scientific_evidence(self):
        cid, _, _ = self.prepared()
        scorer = SimpleNamespace(release_id=self.release, manifest={"test": True})
        before = self.store.get_candidate(cid)["evidence_history"]
        def stop():
            raise StopRequested()
        with self.assertRaises(StopRequested):
            score_batch(self.store, self.artifacts, scorer, candidate_ids=[cid], limit=1, heartbeat=stop)
        self.assertEqual(self.store.get_candidate(cid)["evidence_history"], before)

    def test_release_checksums_fail_before_model_deserialization(self):
        target = self.root / "weights"; target.write_bytes(b"changed")
        release = self.root / "release.json"
        release.write_text(json.dumps({"version": "watcher_supermodel_v2_release1",
            "runs": dict.fromkeys(["cnn", "transformer", "diagnostic", "physical", "supermodel"], {}),
            "files": {"weights": "0" * 64}}))
        with patch("scripts.research.supermodel.ROOT", self.root):
            with self.assertRaisesRegex(ValidationError, "checksum mismatch"): load_release(release)

    def test_stale_heartbeat_is_visible_without_loading_models(self):
        folder = self.store.path.parent / "supermodel"; folder.mkdir()
        (folder / "service.json").write_text(json.dumps({"state": "running", "mode": "primary", "heartbeat_at": "2020-01-01T00:00:00Z"}))
        self.assertEqual(deployment_status(self.store)["state"], "stale")


if __name__ == "__main__":
    unittest.main()
