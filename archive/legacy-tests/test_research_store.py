"""Offline store integration: restarts, fencing, identities, time and evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from scripts.research.artifacts import ArtifactStore, render_plot, validate_plot
from scripts.research.contracts import validate_shared_inputs
from scripts.research.fixtures import seed_fixture
from scripts.research.protocol import (ConflictError, ValidationError, STAGES, digest,
                                       ephemeris, load_protocol, validate_protocol)
from scripts.research.reports import dossier, markdown_report
from scripts.research.store import Store


class ResearchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "research.sqlite3").initialize()
        self.protocol = self.store.register_protocol(load_protocol())
        self.provenance = self.store.register_provenance(kind="code", identity="test-source-v1",
            sha256_digest="a" * 64, retrieved_at="2026-01-01T00:00:00Z", details={"fixture": True})
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)

    def job(self, key="job-1", **kwargs):
        return self.store.create_job(job_key=key, cohort=kwargs.pop("cohort", "synthetic_fixture"),
            protocol_id=self.protocol["id"], code_provenance_id=self.provenance["id"], **kwargs)

    def candidate(self, **kwargs):
        job_id = kwargs.pop("job_id", None) or self.job()["id"]
        values = dict(job_id=job_id, signal_key="signal-1", target_id="SYNTHETIC-001", mission="TESS",
                      period_days=3., epoch=1500.25, epoch_system="BTJD", duration_hours=2.,
                      detection={"method": "box_fixture", "ephemeris_origin": "synthetic_fixture"},
                      provenance_id=self.provenance["id"])
        values.update(kwargs)
        return self.store.put_candidate(**values)

    def fail(self, job_id, retryable=True):
        claim = self.store.claim_stage(job_id, "metadata", worker="test")
        return self.store.finish_stage(claim["lease_token"], error={"code": "network_failure", "message": "Fixture source unavailable", "retryable": retryable})

    def plot(self, **kwargs):
        value = dict(kind="time_series", title="Fixture plot", x_label="Time (BTJD)", y_label="Relative flux",
                     time_system="BTJD", x=[1500., 1501., 1502.], y=[1., .99, 1.])
        value.update(kwargs)
        return value

    def test_empty_database_is_honest_and_initialization_is_repeatable(self):
        self.store.initialize()
        self.assertEqual(self.store.summary()["candidates_by_cohort"], {})
        self.assertEqual(self.store.summary()["jobs_by_status"], {})
        self.assertEqual(self.store.summary()["release_count"], 0)
        with self.store.connection() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_protocol_is_content_addressed_and_frozen(self):
        cfg = load_protocol()
        original = self.store.register_protocol(cfg)
        cfg["hypothesis"] = "Changed version"
        changed = self.store.register_protocol(cfg)
        self.assertNotEqual(original["id"], changed["id"])
        self.assertEqual(original, self.store.get_protocol(original["id"]))
        self.assertEqual(self.store.register_protocol(load_protocol())["id"], original["id"])

    def test_job_candidate_survive_restart_and_deduplicate(self):
        job = self.job(inputs={"product": "fixture.fits"})
        same = self.job(inputs={"product": "fixture.fits"})
        self.assertEqual(job["id"], same["id"])
        with self.assertRaises(ConflictError):
            self.job(inputs={"product": "different.fits"})
        c = self.candidate(job_id=self.job("candidate-job")["id"])
        self.assertEqual(c["id"], self.candidate(job_id=self.job("candidate-job")["id"])["id"])
        restarted = Store(self.store.path).initialize()
        self.assertEqual(restarted.get_candidate(c["id"])["ephemeris"]["epoch_bjd_tdb"], 2458500.25)
        with self.assertRaises(ConflictError):
            self.candidate(job_id=self.job("candidate-job")["id"], period_days=4.)

    def test_concurrent_duplicate_jobs_and_claims_are_atomic(self):
        barrier = threading.Barrier(4)
        def create(_):
            barrier.wait()
            return self.job()["id"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(create, range(4)))
        self.assertEqual(len(set(ids)), 1)
        def claim(i):
            barrier.wait()
            try:
                return self.store.claim_stage(ids[0], "metadata", worker=str(i))["lease_token"]
            except ConflictError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            tokens = list(pool.map(claim, range(4)))
        self.assertEqual(sum(token is not None for token in tokens), 1)
        self.assertEqual(len(self.store.get_job(ids[0])["attempt_history"]), 1)

    def test_prerequisites_completion_and_idempotent_finish(self):
        job = self.job()
        with self.assertRaises(ConflictError):
            self.store.claim_stage(job["id"], "scoring", worker="test")
        for name in STAGES:
            claim = self.store.claim_stage(job["id"], name, worker="test")
            one = self.store.finish_stage(claim["lease_token"], result={"count": 0})
            self.assertEqual(one, self.store.finish_stage(claim["lease_token"], result={"count": 0}))
            self.assertIsNone(self.store.claim_stage(job["id"], name, worker="test"))
            with self.assertRaises(ConflictError):
                self.store.finish_stage(claim["lease_token"], result={"count": 1})
        self.assertEqual(self.store.get_job(job["id"])["status"], "succeeded")
        self.assertEqual(self.job()["id"], job["id"])

    def test_restart_preserves_active_worker_then_recovers_expired_lease(self):
        job = self.job()
        claim = self.store.claim_stage(job["id"], "metadata", worker="lost-worker")
        restarted = Store(self.store.path).initialize()
        self.assertEqual(restarted.recover_expired(), 0)
        self.assertEqual(restarted.get_job(job["id"])["status"], "running")
        with restarted.connection(True) as db:
            db.execute("UPDATE stages SET lease_until='2000-01-01T00:00:00Z' WHERE lease_token=?", (claim["lease_token"],))
        with self.assertRaises(ConflictError):
            restarted.finish_stage(claim["lease_token"], result={"too_late": True})
        self.assertEqual(restarted.recover_expired(), 1)
        self.assertEqual(restarted.recover_expired(), 0)
        second = restarted.claim_stage(job["id"], "metadata", worker="replacement")
        self.assertNotEqual(claim["lease_token"], second["lease_token"])
        with self.assertRaises(ConflictError):
            restarted.finish_stage(claim["lease_token"])
        with self.assertRaises(ConflictError):
            self.candidate(lease_token=claim["lease_token"])
        restarted.finish_stage(second["lease_token"], result={"recovered": True})
        self.assertEqual([a["status"] for a in restarted.get_job(job["id"])["attempt_history"]], ["abandoned", "succeeded"])

    def test_heartbeat_and_cross_job_publication_fence(self):
        first, second = self.job(), self.job("second")
        claim = self.store.claim_stage(first["id"], "metadata", worker="test", lease_seconds=1)
        until = self.store.heartbeat(claim["lease_token"], 100)
        self.assertGreater(until, claim["lease_until"])
        with self.assertRaises(ConflictError):
            self.candidate(job_id=second["id"], lease_token=claim["lease_token"])
        c = self.candidate(lease_token=claim["lease_token"])
        self.store.finish_stage(claim["lease_token"])
        with self.assertRaises(ConflictError):
            self.store.put_evidence(candidate_id=c["id"], evidence_key="stale", kind="controls", state="not_run",
                                    summary="Stale worker should not publish", lease_token=claim["lease_token"])

    def test_failures_are_visible_and_retry_budget_survives_restart(self):
        job = self.job()
        for attempt in range(3):
            self.fail(job["id"])
            self.store = Store(self.store.path).initialize()
            j = self.store.get_job(job["id"])
            self.assertEqual(j["status"], "failed")
            self.assertEqual(j["stages"][0]["error"]["code"], "network_failure")
            if attempt < 2:
                self.store.retry_stage(job["id"], "metadata", actor="reviewer", reason="Source restored")
        with self.assertRaises(ConflictError):
            self.store.retry_stage(job["id"], "metadata", actor="reviewer", reason="No unlimited loop")
        self.assertEqual(len(self.store.get_job(job["id"])["attempt_history"]), 3)

    def test_nonretryable_failures_and_skips_cannot_be_silently_overridden(self):
        job = self.job()
        self.fail(job["id"], retryable=False)
        with self.assertRaises(ConflictError):
            self.store.retry_stage(job["id"], "metadata", actor="test", reason="invalid")
        with self.assertRaises(ConflictError):
            self.store.skip_stage(job["id"], "metadata", actor="test", reason="invalid")
        other = self.job("other")
        with self.assertRaises(ConflictError):
            self.store.skip_stage(other["id"], "detection", actor="test", reason="missing prerequisites")
        self.store.skip_stage(other["id"], "metadata", actor="test", reason="Archival local control")
        self.assertEqual(self.store.get_job(other["id"])["stages"][0]["result"]["reason"], "Archival local control")

    def test_missing_catalogs_are_incomplete_and_unmatched_is_not_novelty(self):
        c = self.candidate()
        args = dict(candidate_id=c["id"], evidence_key="registry-v1", kind="registry", state="complete",
                    summary="No matching object in fixture catalogs", provenance_id=self.provenance["id"])
        with self.assertRaises(ValidationError):
            self.store.put_evidence(**args, payload={"status": "UNMATCHED", "required_sources_complete": False})
        self.store.put_evidence(**args, payload={"status": "UNMATCHED", "required_sources_complete": True})
        detail = self.store.get_candidate(c["id"])
        self.assertEqual(detail["review_status"], "unreviewed")
        self.assertIn("centroid", detail["incomplete_evidence"])
        self.assertTrue(any("not proof of novelty" in warning for warning in detail["warnings"]))
        with self.assertRaises(ValidationError):
            self.store.put_evidence(**{**args, "evidence_key": "registry-v2"}, payload={"status": "INCOMPLETE_LOOKUP", "required_sources_complete": True})
        self.store.put_evidence(**{**args, "evidence_key": "registry-v2", "state": "failed", "summary": "Source timed out"})
        detail = self.store.get_candidate(c["id"])
        self.assertIn("registry", detail["incomplete_evidence"])
        self.assertEqual(len(detail["evidence_history"]), 2)
        self.assertEqual(detail["review_status"], "unreviewed")

    def test_evidence_dedup_and_score_requires_model_and_normalizer_hash(self):
        c = self.candidate()
        args = dict(candidate_id=c["id"], evidence_key="model-v1", kind="model_score", state="complete",
                    summary="Fixture score, not a probability of confirmation", provenance_id=self.provenance["id"])
        with self.assertRaises(ValidationError):
            self.store.put_evidence(**args, payload={"score": .9})
        payload = {"score": .7, "input_contract": "shared_v1", "model_sha256": "b" * 64, "normalization_sha256": "c" * 64}
        one = self.store.put_evidence(**args, payload=payload)
        self.assertEqual(one["id"], self.store.put_evidence(**args, payload=payload)["id"])
        with self.assertRaises(ConflictError):
            self.store.put_evidence(**args, payload={**payload, "score": .8})
        with self.assertRaises(ValidationError):
            self.store.put_evidence(**{**args, "evidence_key": "bad"}, payload={**payload, "score": float("nan")})

    def test_reviews_preserve_audit_and_prevent_lost_update_or_confirmation(self):
        c = self.candidate()
        review = self.store.review_candidate(c["id"], status="follow_up", reviewer="Astronomer", note="Centroid evidence is needed", expected_revision=0)
        self.assertEqual(review["revision"], 1)
        with self.assertRaises(ConflictError):
            self.store.review_candidate(c["id"], status="rejected", reviewer="Other", note="Stale tab", expected_revision=0)
        with self.assertRaises(ValidationError):
            self.store.review_candidate(c["id"], status="confirmed", reviewer="Other", note="Not supported", expected_revision=1)
        self.assertEqual(self.candidate()["review_status"], "follow_up")
        self.assertTrue(self.store.get_candidate(c["id"])["incomplete_evidence"])
        self.assertEqual(len(self.store.get_candidate(c["id"])["reviews"]), 1)

    def test_release_product_identity_and_source_receipts_are_immutable(self):
        args = dict(mission="TESS", release_key="synthetic-s0001", available_at="2026-01-01T00:00:00Z",
                    provenance_id=self.provenance["id"], metadata={"synthetic": True})
        release = self.store.register_release(**args)
        self.assertEqual(release["id"], self.store.register_release(**args)["id"])
        with self.assertRaises(ConflictError):
            self.store.register_release(**{**args, "metadata": {"changed": True}})
        with self.assertRaises(ValidationError):
            self.store.register_release(**{**args, "available_at": "2999-01-01T00:00:00Z"})
        product = self.store.register_product(release_id=release["id"], product_key="fixture-product", target_id="SYNTHETIC-001",
                                              source_uri="fixture://no-download", provenance_id=self.provenance["id"])
        with self.assertRaises(ValidationError):
            self.job(product_id=product["id"])
        job = self.job(release_id=release["id"], product_id=product["id"])
        with self.assertRaises(ValidationError):
            self.candidate(job_id=job["id"], target_id="different")
        c = self.candidate(job_id=job["id"])
        exported = dossier(self.store, c["id"])
        self.assertEqual(exported["candidate"]["release"]["release_key"], "synthetic-s0001")
        self.assertEqual(exported["candidate"]["product"]["source_uri"], "fixture://no-download")

    def test_cohorts_are_enforced_and_known_period_is_not_blind_detection(self):
        with self.assertRaises(ValidationError):
            self.job(cohort="prospective_search")
        archival = self.job("archival", cohort="archival_pilot")
        with self.assertRaises(ValidationError):
            self.candidate(job_id=archival["id"])
        with self.assertRaises(ValidationError):
            self.candidate(job_id=archival["id"], detection={"method": "BLS", "ephemeris_origin": "catalog_control"})
        with self.assertRaises(ValidationError):
            self.candidate(job_id=archival["id"], detection={"method": "BLS", "ephemeris_origin": "blind_search"})
        c = self.candidate(job_id=archival["id"], detection={"method": "BLS", "ephemeris_origin": "blind_search", "used_catalog_ephemeris": False})
        self.assertEqual(self.store.get_candidate(c["id"])["cohort"], "archival_pilot")

    def test_plot_and_report_export_retain_values_units_and_provenance(self):
        c = self.candidate()
        artifact = self.artifacts.put_plot(self.plot(), candidate_id=c["id"], artifact_key="curve", filename="curve.json")
        record, payload = self.artifacts.read(artifact["id"])
        self.assertEqual(json.loads(payload)["time_system"], "BTJD")
        svg = render_plot(json.loads(payload)).decode()
        self.assertEqual(svg.count("<circle"), 3)
        self.assertIn("Time (BTJD)", svg)
        self.assertEqual(record["id"], artifact["id"])
        document = dossier(self.store, c["id"])
        self.assertIn(self.provenance["id"], {r["id"] for r in document["candidate"]["provenance"]})
        report = markdown_report(document)
        self.assertIn("synthetic_fixture", report)
        self.assertIn("BJD TDB", report)
        self.assertIn("not proof of novelty", report)
        self.assertIn(artifact["sha256"], report)

    def test_artifacts_reject_tampering_traversal_active_content_and_bad_plots(self):
        c = self.candidate()
        args = dict(candidate_id=c["id"], artifact_key="curve", filename="curve.json")
        with self.assertRaises(ValidationError):
            self.artifacts.put_bytes(b"<script>alert(1)</script>", media_type="text/html", kind="report", **args)
        with self.assertRaises(ValidationError):
            self.artifacts.put_plot(self.plot(), **{**args, "filename": "../../secrets.json"})
        with self.assertRaises(ValidationError):
            validate_plot(self.plot(time_system="UTC"))
        with self.assertRaises(ValidationError):
            validate_plot(self.plot(y=[1., float("nan"), 1.]))
        with self.assertRaises(ValidationError):
            validate_plot(self.plot(x=[1., 3., 2.]))
        unsafe = render_plot(self.plot(title='<script>alert("x")</script>')).decode()
        self.assertNotIn("<script>", unsafe)
        a = self.artifacts.put_plot(self.plot(), **args)
        path = self.artifacts._path(a["sha256"])
        path.write_bytes(b"corrupt")
        with self.assertRaises(ConflictError):
            self.artifacts.read(a["id"])
        path.unlink()
        path.symlink_to(self.root / "outside.json")
        with self.assertRaises(ValidationError):
            self.artifacts.read(a["id"])

    def test_seed_fixture_is_restartable_and_never_scores_or_queries_catalogs(self):
        c = seed_fixture(self.store, self.artifacts, self.protocol["id"])
        second = seed_fixture(self.store, self.artifacts, self.protocol["id"])
        self.assertEqual(c["id"], second["id"])
        self.assertEqual(self.store.summary()["candidates_by_cohort"], {"synthetic_fixture": 1})
        self.assertEqual(c["job"]["status"], "failed")
        self.assertIn("model_score", c["incomplete_evidence"])
        self.assertIn("registry", c["incomplete_evidence"])
        self.assertEqual(len(c["artifacts"]), 2)

    def test_database_version_is_not_silently_downgraded(self):
        with sqlite3.connect(str(self.store.path)) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ConflictError):
            self.store.initialize()


class ResearchContractTests(unittest.TestCase):
    def test_time_systems_convert_explicitly_and_preserve_original(self):
        for epoch, system in ((2458500.25, "BJD_TDB"), (1500.25, "BTJD"), (3667.25, "BKJD")):
            e = ephemeris(3., epoch, system, 2.)
            self.assertEqual(e["epoch_bjd_tdb"], 2458500.25)
            self.assertEqual(e["epoch_original"], epoch)
        for epoch, system in ((1500., "BJD_TDB"), (2458500., "BTJD"), (1500., "UTC"), (float("nan"), "BTJD")):
            with self.assertRaises(ValidationError):
                ephemeris(3., epoch, system, 2.)
        with self.assertRaises(ValidationError):
            ephemeris(1., 1500., "BTJD", 24.)

    def test_protocol_enforces_resource_and_scientific_bounds(self):
        for parent, key, value in (("limits", "download_bytes_total", 3 * 1024 ** 3),
                                  ("limits", "cpu_workers", 5), ("limits", "download_workers", 3),
                                  ("limits", "initial_products", 21), ("limits", "stage_max_attempts", 100),
                                  ("search", "max_period_grid", 1000000),
                                  ("search", "known_ephemerides_in_blind_search", True),
                                  ("watcher", "automatic_downloads", True),
                                  ("review", "prospective_search_ready", True),
                                  ("inputs", "offset_days", {"BTJD": 0}),
                                  ("inputs", "scalar_names", ["reordered"]),
                                  ("research", "selection_data", "test"),
                                  ("research", "ml_hard_veto", True)):
            cfg = load_protocol()
            cfg[parent][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_protocol(cfg)

    def test_shared_feature_shapes_channels_dtype_and_flat_order(self):
        import numpy as np
        arrays = {"X_global": np.arange(1200, dtype=np.float32).reshape(2, 200, 3),
                  "X_local": np.arange(600, dtype=np.float32).reshape(2, 100, 3),
                  "X_scalar": np.ones((2, 7), dtype=np.float32)}
        arrays["X"] = np.concatenate([arrays["X_global"].transpose(0, 2, 1).reshape(2, -1),
                                      arrays["X_local"].transpose(0, 2, 1).reshape(2, -1), arrays["X_scalar"]], axis=1)
        self.assertEqual(validate_shared_inputs(arrays)["n_candidates"], 2)
        for key, value in (("X_global", arrays["X_global"].transpose(0, 2, 1)),
                           ("X_scalar", np.ones((2, 8), dtype=np.float32)),
                           ("X", np.concatenate([arrays["X_global"].reshape(2, -1), arrays["X_local"].reshape(2, -1), arrays["X_scalar"]], axis=1)),
                           ("X_global", arrays["X_global"].astype(np.float64))):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_shared_inputs({**arrays, key: value})


if __name__ == "__main__":
    unittest.main()
