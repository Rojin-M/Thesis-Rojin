"""Real feature/model boundaries, diagnostic behavior, cache state and restart tests."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

from scripts.data.shared_preprocessing import SharedConfig, candidate_features, ephemeris
from scripts.data.tess_dataset import apply_normalization
from scripts.data.tess_preprocessing import detrend_sector
from scripts.data.kepler_pipeline_lib import compute_bls_features
from scripts.research.artifacts import ArtifactStore
from scripts.research.bounded import bounded_call
from scripts.research.detection import SearchConfig, event_diagnostics
from scripts.research.detection_worker import run_local_detection
from scripts.research.diagnostics import native_evidence, transit_diagnostics
from scripts.research.features import build_features
from scripts.research.fixtures import seed_fixture
from scripts.research.lightcurves import read_lightcurves
from scripts.research.protocol import ConflictError, ValidationError, digest, load_protocol, utc_now
from scripts.research.registry_cache import fetch_bundle, MAX_RESPONSE, BoundedCatalogClient
from scripts.research.scoring import CHECKPOINT, NORMALIZER, CHECKPOINT_SHA, FrozenScorer
from scripts.research.store import Store
from scripts.research.vetting_worker import run_vetting, registry_report, read_npz, refresh_registry, _catalog_bundle
from scripts.vetting.registry import CatalogRecord, CatalogSnapshot, SourceState, Candidate, assess_candidate
from tests.test_research_detection import curve, write_npz, write_fits


def snapshots(tic="123", period=3.22, epoch=2458501.1):
    """Explicit test catalog records, never loaded into the operational store."""
    raw = b'[{"test_fixture":true}]'
    result = []
    for source in ("exofop_toi", "exofop_ctoi", "nasa_ps", "nasa_toi"):
        record = CatalogRecord(source, "TEST ONLY", "TEST-PLANET", tic, "CP", period, epoch, 2.88, None,
                               "https://example.invalid/test-only", {"fixture": True})
        result.append(CatalogSnapshot(source, "TEST ONLY", "https://example.invalid/test-only", source != "nasa_toi",
            SourceState.OK, utc_now(), [record], payload_sha256=hashlib.sha256(raw).hexdigest(), raw_payload=raw))
    return result


def slow_operation():
    time.sleep(10)


def io_failure():
    raise OSError("transient test I/O failure")


class FeatureDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "input.npz"
        write_npz(self.path, curve())
        self.inputs = {"paths": [str(self.path)], "mission": "TESS", "target_id": "123", "time_system": "BTJD",
                       "sha256": {str(self.path): hashlib.sha256(self.path.read_bytes()).hexdigest()}}
        self.candidate = {"id": "synthetic", "ephemeris": {"period_days": 3.22, "epoch_bjd_tdb": 2458501.1, "duration_hours": 2.88},
                          "detection": {"ephemeris_origin": "blind_search", "used_catalog_ephemeris": False}}

    def test_adapter_exactly_reuses_shared_contract_and_legacy_scalars(self):
        result = build_features(self.inputs, [self.candidate])
        cfg = replace(SharedConfig(), cadence_seconds=1728.)
        row = {"candidate_id": "synthetic", "period": 3.22, "epoch_bjd": 2458501.1, "duration_hours": 2.88}
        loaded = read_lightcurves(**{k: v for k, v in self.inputs.items() if k not in ("sha256",)}, expected_hashes=self.inputs["sha256"])
        t, f, _ = detrend_sector(loaded.time, loaded.flux, [ephemeris(row)], cfg)
        bls = compute_bls_features(t, f, cfg)
        reference = candidate_features(t, f, row, {"synthetic": ephemeris(row)}, cfg, bls)
        actual = result["candidates"][0]
        self.assertEqual(actual["status"], "accepted")
        for key, value in reference["arrays"].items():
            np.testing.assert_array_equal(actual["arrays"][key][0], value)
        self.assertEqual(result["legacy_bls"], bls)
        self.assertEqual(actual["arrays"]["X_scalar"][0, 3], np.float32(bls["bls_snr"]))
        self.assertEqual(result["duration_unit"], "hour")
        self.assertEqual(result["legacy_scalar_semantics"]["bls_duration"], "hours")

    def test_bkjd_and_btjd_native_inputs_build_same_features(self):
        second = self.root / "bkjd.npz"
        v = curve(); v.time += 2167
        write_npz(second, v)
        inputs = {**self.inputs, "paths": [str(second)], "time_system": "BKJD",
                  "sha256": {str(second): hashlib.sha256(second.read_bytes()).hexdigest()}}
        a = build_features(self.inputs, [self.candidate])["candidates"][0]["arrays"]
        b = build_features(inputs, [self.candidate])["candidates"][0]["arrays"]
        for key in a:
            np.testing.assert_allclose(a[key], b[key], rtol=1e-5, atol=1e-5)

    def test_feature_failure_does_not_construct_fabricated_inputs(self):
        c = deepcopy(self.candidate); c["ephemeris"]["period_days"] = 100
        result = build_features(self.inputs, [c])["candidates"][0]
        self.assertEqual(result["reason"], "insufficient_sampled_transit_events")
        self.assertNotIn("arrays", result)
        c["detection"]["used_catalog_ephemeris"] = True
        with self.assertRaises(ValidationError):
            build_features(self.inputs, [c])

    def test_actual_hard_deadline_cleans_up_owned_worker(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            bounded_call(slow_operation, seconds=1)
        self.assertLess(time.monotonic() - start, 5)

    def test_owned_worker_preserves_retryable_io_failure_type(self):
        with self.assertRaisesRegex(OSError, "transient test"):
            bounded_call(io_failure, seconds=10)

    def test_secondary_away_from_half_and_real_event_odd_even(self):
        v = curve(depth=.015)
        cycles = np.rint((v.time - 1501.1) / 3.22).astype(int)
        primary = np.abs((v.time - 1501.1 + 1.61) % 3.22 - 1.61) < .06
        v.flux[primary & (cycles % 2 == 0)] -= .01
        v.flux[np.abs((v.time - (1501.1 + .32 * 3.22) + 1.61) % 3.22 - 1.61) < .06] -= .006
        old = event_diagnostics(v, 3.22, 1501.1, .12, SearchConfig())
        state, result = transit_diagnostics(self.candidate,
            {"time_btjd": v.time, "flux": v.flux, "flux_err": v.error, "segment": v.segment}, {"proposal": {"diagnostics": old}})
        self.assertEqual(state, "complete")
        self.assertGreater(result["odd_even_by_covered_event"]["difference_sigma_with_event_scatter_floor"], 5)
        self.assertAlmostEqual(result["secondary_scan"]["best"]["phase"], .32, delta=.02)
        self.assertFalse(result["secondary_scan"]["false_alarm_calibrated"])
        self.assertEqual(len(result["aliases"]["fixed_epoch_comparisons"]), 4)

    def test_missing_native_diagnostics_remain_incomplete(self):
        evidence = native_evidence(self.inputs, self.candidate)
        self.assertEqual(evidence["centroid"]["state"], "incomplete")
        self.assertEqual(evidence["contamination"]["products"][0]["reason"], "input_has_no_native_crowding_headers")

    def test_native_centroid_shift_and_crowding_not_declared_validation(self):
        path = self.root / "native.fits"
        write_fits(path)
        with fits.open(path) as hdus:
            old = hdus[1]
            t = curve().time
            inside = np.abs((t - 1501.1 + 1.61) % 3.22 - 1.61) < .06
            x = 10 + np.random.default_rng(11).normal(0, .0001, len(t)) + .003 * inside
            cols = old.columns + fits.ColDefs([fits.Column(name="MOM_CENTR1", format="D", array=x),
                                              fits.Column(name="MOM_CENTR2", format="D", array=x + 5)])
            table = fits.BinTableHDU.from_columns(cols, header=old.header)
            table.header["CROWDSAP"] = .82; table.header["FLFRCSAP"] = .91
            fits.HDUList([hdus[0].copy(), table]).writeto(self.root / "centroid.fits", checksum=True)
        path = self.root / "centroid.fits"
        inputs = {**self.inputs, "paths": [str(path)], "sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}}
        result = native_evidence(inputs, self.candidate)
        self.assertEqual(result["centroid"]["state"], "incomplete")
        axis = result["centroid"]["products"][0]["axes"]["MOM_CENTR1"]
        self.assertAlmostEqual(axis["shift_pixel"], .003, delta=.0001)
        self.assertGreater(axis["white_sigma"], 20)
        self.assertEqual(result["contamination"]["products"][0]["header_fractions"]["CROWDSAP"], .82)


class RegistryCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_lookup_per_tic_reused_and_stale_cannot_be_unmatched(self):
        with patch("scripts.research.registry_cache.BoundedCatalogClient.lookup", return_value=snapshots()) as lookup:
            live = fetch_bundle(self.root, "123", "live")
            cached = fetch_bundle(self.root, "123", "offline")
            self.assertEqual(lookup.call_count, 1)
            self.assertEqual(cached["cache_use"], "within_ttl")
            self.assertEqual(cached["snapshots"][0].raw_payload, live["snapshots"][0].raw_payload)
        pointer = self.root / "tic-123.json"
        envelope = json.loads(pointer.read_text())
        envelope["bundle"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        envelope["sha256"] = digest(envelope["bundle"]); pointer.write_text(json.dumps(envelope))
        stale = fetch_bundle(self.root, "123", "offline")
        self.assertTrue(all(s.state == SourceState.CACHED_STALE for s in stale["snapshots"]))
        assessment = assess_candidate(Candidate("123", 5., 2458501.1, 2.), stale["snapshots"])
        self.assertEqual(assessment["status"], "INCOMPLETE_LOOKUP")

    def test_missing_source_retry_force_recovers_without_false_unmatched(self):
        incomplete = snapshots()
        incomplete[0] = replace(incomplete[0], state=SourceState.UNAVAILABLE, raw_payload=None, payload_sha256=None, records=[], error="test outage")
        with patch("scripts.research.registry_cache.BoundedCatalogClient.lookup", side_effect=[incomplete, snapshots()]) as lookup:
            failed = fetch_bundle(self.root, "123", "live")
            self.assertEqual(assess_candidate(Candidate("123", 8., 2458501.1), failed["snapshots"])["status"], "INCOMPLETE_LOOKUP")
            fetch_bundle(self.root, "123", "live")
            self.assertEqual(lookup.call_count, 1)
            recovered = fetch_bundle(self.root, "123", "live", force=True)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(assess_candidate(Candidate("123", 8., 2458501.1), recovered["snapshots"])["status"], "UNMATCHED")

    def test_corrupted_raw_snapshot_never_reused_as_current(self):
        with patch("scripts.research.registry_cache.BoundedCatalogClient.lookup", return_value=snapshots()):
            fetch_bundle(self.root, "123", "live")
        next((self.root / "raw").iterdir()).write_bytes(b"tampered")
        with patch("scripts.research.registry_cache._legacy_offline", return_value=[]):
            bundle = fetch_bundle(self.root, "123", "offline")
        self.assertIn("checksum", bundle["cache_error"])
        self.assertEqual(bundle["snapshots"], [])

    def test_streamed_catalog_response_is_bounded(self):
        class Response:
            headers = {"Content-Length": str(MAX_RESPONSE + 1)}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
        client = BoundedCatalogClient(self.root)
        with patch.object(client.session, "get", return_value=Response()), patch("scripts.research.registry_cache.time.sleep"):
            with self.assertRaisesRegex(Exception, "16 MiB"):
                client._request("https://example.invalid/test")

    def test_hard_lookup_failure_stays_explicit_and_does_not_invent_zero_downloads(self):
        with patch("scripts.research.vetting_worker.bounded_call", side_effect=TimeoutError("test deadline")):
            result = _catalog_bundle(self.root, "123", "live")
        self.assertEqual(result["snapshots"], [])
        self.assertIsNone(result["downloaded_bytes_this_call"])
        self.assertTrue(result["lookup_failure"]["retryable"])


class ProcessingIdentityTests(unittest.TestCase):
    def test_downstream_identity_survives_restart_and_rejects_changed_weights_or_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "db.sqlite3").initialize()
            protocol = store.register_protocol(load_protocol())
            c = seed_fixture(store, ArtifactStore(root / "artifacts", store), protocol["id"])
            first = store.freeze_processing_run(c["job_id"], "test_worker", {"model": "a", "code": "version1"})
            store = Store(root / "db.sqlite3").initialize()
            self.assertEqual(first, store.freeze_processing_run(c["job_id"], "test_worker", {"model": "a", "code": "version1"}))
            with self.assertRaises(ConflictError):
                store.freeze_processing_run(c["job_id"], "test_worker", {"model": "b", "code": "version1"})
            with self.assertRaises(ConflictError):
                store.freeze_processing_run(c["job_id"], "test_worker", {"model": "a", "code": "version2"})


@unittest.skipUnless(CHECKPOINT.is_file() and NORMALIZER.is_file(), "Local frozen trained artifacts are not committed")
class TrainedWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorer = FrozenScorer(batch_size=2)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "research.sqlite3").initialize()
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)
        protocol = self.store.register_protocol(load_protocol())
        path = self.root / "source.npz"; write_npz(path, curve())
        result = run_local_detection(self.store, self.artifacts, protocol["id"], paths=[path], mission="TESS", target_id="123",
            cohort="synthetic_fixture", time_system="BTJD", config=SearchConfig(max_period_grid=2000, max_signals=1, max_seconds=30),
            experiment={"kind": "synthetic_integration_fixture"})
        self.job_id, self.cid = result["job_id"], result["candidate_ids"][0]
        self.kwargs = {"scorer": self.scorer, "cache_root": self.root / "cache", "feature_seconds": 60}

    def test_real_detector_features_normalizer_checkpoint_and_restart(self):
        result = run_vetting(self.store, self.artifacts, self.job_id, **self.kwargs)
        c = self.store.get_candidate(self.cid)
        evidence = {e["kind"]: e for e in c["evidence"]}
        self.assertEqual(c["job"]["status"], "succeeded")
        self.assertEqual(evidence["model_score"]["state"], "complete")
        self.assertEqual(evidence["model_score"]["payload"]["model_sha256"], CHECKPOINT_SHA)
        self.assertEqual(c["review_status"], "unreviewed")
        self.assertIn("centroid", c["incomplete_evidence"])
        raw = read_npz(self.artifacts, next(a for a in c["artifacts"] if a["artifact_key"].endswith(":raw")))
        normalized = read_npz(self.artifacts, next(a for a in c["artifacts"] if a["artifact_key"].endswith(":normalized")))
        expected = apply_normalization(raw, self.scorer.stats)
        for key in expected:
            np.testing.assert_array_equal(expected[key], normalized[key])
        single = self.scorer.predict(raw)["scores"][0]
        batched = self.scorer.predict({key: np.repeat(v, 3, axis=0) for key, v in raw.items()})["scores"]
        np.testing.assert_allclose(batched, single, rtol=1e-5, atol=1e-6)
        self.assertAlmostEqual(single, evidence["model_score"]["payload"]["score"], places=6)
        counts = (len(c["artifacts"]), len(c["evidence_history"]))
        replay = run_vetting(Store(self.store.path).initialize(), self.artifacts, self.job_id, **self.kwargs)
        self.assertTrue(replay["already_complete"])
        after = self.store.get_candidate(self.cid)
        self.assertEqual(counts, (len(after["artifacts"]), len(after["evidence_history"])))
        self.assertTrue(all(s["attempts"] == 1 for s in after["job"]["stages"]))

    def test_partial_score_publication_failure_and_explicit_retry_deduplicate(self):
        finish = self.store.finish_stage
        fired = [False]
        def crash(token, **kwargs):
            if not fired[0] and "scored_ids" in kwargs.get("result", {}):
                fired[0] = True
                raise OSError("injected publication boundary failure")
            return finish(token, **kwargs)
        with patch.object(self.store, "finish_stage", side_effect=crash):
            with self.assertRaises(OSError):
                run_vetting(self.store, self.artifacts, self.job_id, **self.kwargs)
        first = self.store.get_candidate(self.cid)
        score = next(e for e in first["evidence"] if e["kind"] == "model_score")
        self.assertEqual(first["job"]["status"], "failed")
        self.store.retry_stage(self.job_id, "scoring", actor="test", reason="Explicit retry after injected failure")
        run_vetting(self.store, self.artifacts, self.job_id, **self.kwargs)
        after = self.store.get_candidate(self.cid)
        self.assertEqual(next(e for e in after["evidence"] if e["kind"] == "model_score")["id"], score["id"])
        self.assertEqual(next(s for s in after["job"]["stages"] if s["name"] == "scoring")["attempts"], 2)

    def test_mismatched_checkpoint_is_visible_stage_failure_no_random_fallback(self):
        with patch("scripts.research.scoring.CHECKPOINT_SHA", "0" * 64):
            with self.assertRaisesRegex(ValidationError, "checksum"):
                run_vetting(self.store, self.artifacts, self.job_id, cache_root=self.root / "cache", feature_seconds=60)
        c = self.store.get_candidate(self.cid)
        self.assertEqual(c["job"]["status"], "failed")
        self.assertNotIn("model_score", [e["kind"] for e in c["evidence"]])
        self.assertIn("model_score_missing_review_retained", c["review_triage"]["flags"])

    def test_feature_incomplete_still_reaches_diagnostics_and_human_dossier(self):
        result = {"candidates": [{"candidate_id": self.cid, "status": "rejected",
            "reason": "insufficient_sampled_transit_events", "diagnostics": {}}], "version": "test_incomplete_fixture"}
        with patch("scripts.research.vetting_worker.bounded_call", return_value=result):
            run_vetting(self.store, self.artifacts, self.job_id, **self.kwargs)
        c = self.store.get_candidate(self.cid)
        latest = {e["kind"]: e for e in c["evidence"]}
        self.assertEqual(latest["shared_inputs"]["state"], "incomplete")
        self.assertEqual(latest["model_score"]["state"], "incomplete")
        self.assertNotIn("score", latest["model_score"]["payload"])
        self.assertEqual(c["job"]["status"], "succeeded")
        self.assertTrue(any(a["filename"] == "candidate-dossier.md" for a in c["artifacts"]))
        self.assertEqual(c["review_status"], "unreviewed")

    def test_detected_ephemeris_reaches_checker_and_refresh_remains_incomplete_on_outage(self):
        run_vetting(self.store, self.artifacts, self.job_id, **self.kwargs)
        c = self.store.get_candidate(self.cid)
        # Explicit checker fixture at the detected ephemeris. This exists only
        # in the temporary test store, never in operational candidate evidence.
        c["cohort"] = "known_object_control"
        eph = c["ephemeris"]
        bundle = {"snapshots": snapshots(period=eph["period_days"], epoch=eph["epoch_bjd_tdb"]), "checked_at": utc_now()}
        report = registry_report(self.store, self.artifacts, c, bundle)
        self.assertEqual(report["payload"]["status"], "CONFIRMED_PLANET")
        self.assertEqual(report["payload"]["candidate"]["epoch_bjd_tdb"], eph["epoch_bjd_tdb"])
        self.assertEqual(report["state"], "complete")
        bundle = {"snapshots": [], "checked_at": utc_now(), "cache_error": "test connection refused"}
        report = registry_report(self.store, self.artifacts, c, bundle)
        self.assertEqual(report["state"], "incomplete")
        self.assertEqual(report["payload"]["status"], "INCOMPLETE_LOOKUP")
        self.assertTrue(report["payload"]["retryable"])
        current = self.store.get_candidate(self.cid)
        self.assertEqual(current["review_status"], "unreviewed")
        self.assertGreaterEqual(len([e for e in current["evidence_history"] if e["kind"] == "registry"]), 3)


if __name__ == "__main__":
    unittest.main()
