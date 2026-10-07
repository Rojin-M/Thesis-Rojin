"""Blind search behavior, real format/time contracts, restart and persisted outputs."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

from scripts.research.artifacts import ArtifactStore
from scripts.research.detection import SearchConfig, bounded_search, event_diagnostics, harmonic_relation, search
from scripts.research.detection_controls import evaluate_proposals
from scripts.research.detection_worker import run_local_detection
from scripts.research.lightcurves import LightCurve, detrend, read_lightcurves
from scripts.research.local_selection import cached_tess_paths
from scripts.research.protocol import ConflictError, ValidationError, load_protocol
from scripts.research.store import Store


def curve(period=3.22, epoch=1501.1, depth=.01, duration=.12, seed=123):
    t = np.arange(1500, 1527, .02)
    f = 1 + np.random.default_rng(seed).normal(0, .001, len(t))
    if depth:
        f -= depth * (np.abs((t - epoch + .5 * period) % period - .5 * period) < duration / 2)
    return LightCurve(t, f, np.full(len(t), .001), np.zeros(len(t), int), [], {"time_system": "BTJD"})


def write_npz(path, value):
    np.savez(path, time=value.time, flux=value.flux, flux_err=value.error, quality=np.zeros(len(value.time), int))


def write_fits(path, mission="TESS", timezero=.125):
    value = curve()
    q = np.zeros(len(value.time), np.int32)
    q[5] = 1
    times = value.time.copy()
    if mission == "Kepler":
        times += 2457000 - 2454833
    times -= timezero
    names = ("TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", "QUALITY" if mission == "TESS" else "SAP_QUALITY")
    columns = [fits.Column(name=n, format="J" if n in ("QUALITY", "SAP_QUALITY") else "D", array=a)
               for n, a in zip(names, (times, value.flux, value.error, q))]
    primary = fits.PrimaryHDU()
    primary.header["TICID" if mission == "TESS" else "KEPLERID"] = 123
    table = fits.BinTableHDU.from_columns(columns)
    table.header.update(TIMESYS="TDB", TIMEREF="SOLARSYSTEM", TIMEUNIT="d", BJDREFI=2457000 if mission == "TESS" else 2454833,
                        BJDREFF=0, TIMEZERO=timezero, TIMEDEL=.02)
    fits.HDUList([primary, table]).writeto(path, checksum=True)


def blocked_search_child(connection, value, config):
    # Simulate a stuck compiled call in our OWN child, verifying hard cleanup.
    time.sleep(10)


class LightCurveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_native_mission_headers_convert_same_absolute_times_and_keep_dips(self):
        for mission in ("TESS", "Kepler"):
            path = self.root / (mission + ".fits")
            write_fits(path, mission)
            loaded = read_lightcurves([path], mission=mission, target_id="123")
            np.testing.assert_allclose(loaded.time, np.delete(curve().time, 5), atol=1e-9)
            self.assertEqual(loaded.sources[0]["n_quality_rejected"], 1)
            self.assertEqual(loaded.sources[0]["timezero_days"], .125)
            self.assertLess(loaded.flux.min(), .993)
            with self.assertRaises(ValidationError):
                read_lightcurves([path], mission=mission, target_id="999")

    def test_fits_corruption_and_non_tdb_rejected(self):
        path = self.root / "bad.fits"
        write_fits(path)
        with fits.open(path, mode="update") as hdus:
            hdus[1].header["TIMESYS"] = "UTC"
        with self.assertRaisesRegex(ValidationError, "TDB"):
            read_lightcurves([path], mission="TESS", target_id="123")
        path.unlink()
        write_fits(path)
        data = bytearray(path.read_bytes())
        data[-10] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValidationError, "CHECKSUM|DATASUM"):
            read_lightcurves([path], mission="TESS", target_id="123")

    def test_explicit_npz_time_conversion_quality_and_duplicate_handling(self):
        value = curve()
        path = self.root / "curve.npz"
        np.savez(path, time=np.r_[value.time, value.time[0], np.nan] + 2457000,
                 flux=np.r_[value.flux, 1., 1.], flux_err=np.r_[value.error, .001, .001],
                 quality=np.r_[np.zeros(len(value.time)), 0, 0])
        with self.assertRaisesRegex(ValidationError, "time-system"):
            read_lightcurves([path], mission="TESS", target_id="local")
        loaded = read_lightcurves([path], mission="TESS", target_id="local", time_system="BJD_TDB")
        np.testing.assert_allclose(loaded.time, value.time)
        self.assertEqual(loaded.metadata["n_duplicate_times"], 1)
        self.assertEqual(loaded.sources[0]["n_invalid_samples"], 1)
        with self.assertRaisesRegex(ValidationError, "changed"):
            read_lightcurves([path], mission="TESS", target_id="local", time_system="BJD_TDB", expected_hashes={str(path): "0" * 64})

    def test_native_checksum_without_datasum_and_unchanged_input_bytes(self):
        path = self.root / "checksum-only.fits"
        write_fits(path, "Kepler")
        with fits.open(path, memmap=False) as hdus:
            for hdu in hdus:
                del hdu.header["DATASUM"]
                hdu.add_checksum(override_datasum=True)
            buffer = io.BytesIO()
            hdus.writeto(buffer)
        path.write_bytes(buffer.getvalue())
        before = path.read_bytes()
        loaded = read_lightcurves([path], mission="Kepler", target_id="123")
        self.assertTrue(loaded.sources[0]["fits_integrity"][1]["checksum_present"])
        self.assertFalse(loaded.sources[0]["fits_integrity"][1]["datasum_present"])
        self.assertEqual(before, path.read_bytes())
        corrupt = bytearray(before)
        corrupt[-10] ^= 1
        path.write_bytes(corrupt)
        with self.assertRaisesRegex(ValidationError, "CHECKSUM"):
            read_lightcurves([path], mission="Kepler", target_id="123")

    def test_detrend_does_not_bridge_gaps_or_product_offsets(self):
        value = curve()
        keep = (value.time < 1510) | (value.time > 1512)
        value = LightCurve(value.time[keep], value.flux[keep], value.error[keep], value.segment[keep], [], {})
        late = value.time > 1512
        value.flux[late] *= 3
        value.error[late] *= 3
        flat, _ = detrend(value)
        self.assertEqual(flat.metadata["detrending"]["segments"], 2)
        self.assertLess(abs(np.median(flat.flux[flat.time > 1512]) - 1), .001)
        self.assertLess(flat.flux.min(), .993)
        self.assertFalse(flat.metadata["detrending"]["catalog_masks"])

    def test_manifest_adapter_bounds_and_path_safety(self):
        raw = self.root / "data/raw/tess"
        (raw / "metadata").mkdir(parents=True)
        (raw / "one.fits").write_bytes(b"fixture")
        manifest = raw / "metadata/manifest.csv"
        manifest.write_text("tic_id,sector,relative_path\n123,2,one.fits\n")
        self.assertEqual(cached_tess_paths(self.root, "123"), [raw / "one.fits"])
        with self.assertRaises(ValidationError):
            cached_tess_paths(self.root, "123", 21)
        manifest.write_text("tic_id,sector,relative_path\n123,1,../../../../outside.fits\n")
        with self.assertRaisesRegex(ValidationError, "escapes"):
            cached_tess_paths(self.root, "123")


class BlindSearchTests(unittest.TestCase):
    config = SearchConfig(max_period_grid=6000, max_signals=2, max_seconds=30)

    def test_recovers_unseeded_period_epoch_and_coverage(self):
        result = search(curve(), self.config)
        p = result["proposals"][0]
        self.assertLess(abs(p["period_days"] - 3.22), .003)
        self.assertLess(abs((p["epoch_btjd"] - 1501.1 + 1.61) % 3.22 - 1.61), .03)
        self.assertGreaterEqual(p["diagnostics"]["n_covered_events"], 7)
        self.assertFalse(result["used_catalog_ephemeris"])
        self.assertTrue(all(r["evaluated_periods"] <= self.config.max_period_grid for r in result["rounds"]))
        self.assertEqual(result["tls"]["state"], "not_run")

    def test_iterative_masking_recovers_second_distinct_signal(self):
        value = curve()
        value.flux -= .006 * (np.abs((value.time - 1500.8 + 2.585) % 5.17 - 2.585) < .08)
        result = search(value, self.config)
        self.assertEqual(len(result["proposals"]), 2)
        for period in (3.22, 5.17):
            self.assertTrue(any(abs(p["period_days"] - period) < .01 for p in result["proposals"]))

    def test_noise_proposals_are_retained_without_claiming_significance(self):
        result = search(curve(depth=0), self.config)
        self.assertGreater(len(result["proposals"]), 0)
        self.assertIn("not a false-alarm", result["score_semantics"])
        self.assertLess(max(p["depth_snr_white"] for p in result["proposals"]), 7.1)

    def test_single_event_is_not_coverage_pass(self):
        value = curve()
        diag = event_diagnostics(value, 28., 1501., .1, self.config)
        self.assertLess(diag["n_covered_events"], 2)
        self.assertFalse(diag["sampling_gate_passed"])
        self.assertIn("insufficient_covered_events", diag["warnings"])

    def test_real_event_odd_even_depths_and_secondary(self):
        value = curve(depth=0)
        phase = (value.time - 1501 + 1.5) % 3 - 1.5
        cycles = np.rint((value.time - 1501) / 3).astype(int)
        value.flux -= np.where(cycles % 2 == 0, .012, .004) * (abs(phase) < .06)
        value.flux -= .004 * (abs(abs(phase) - 1.5) < .06)
        d = event_diagnostics(value, 3., 1501., .12, self.config)
        self.assertGreater(d["odd_even_difference_sigma"], 10)
        self.assertGreater(d["secondary_at_phase_half"]["snr"], 10)

    def test_harmonics_require_aligned_epochs(self):
        a = {"period_days": 6., "epoch_btjd": 1501., "duration_hours": 3.}
        b = {"period_days": 3., "epoch_btjd": 1501., "duration_hours": 3.}
        self.assertEqual(harmonic_relation(a, b, 27)["period_ratio"], 2)
        self.assertIsNone(harmonic_relation({**a, "epoch_btjd": 1502.}, b, 27))

    def test_unbounded_grid_and_invalid_duration_rejected(self):
        for change in ({"max_period_grid": 20001}, {"max_seconds": 301}, {"max_signals": 4}, {"durations_hours": (12.,)}):
            with self.assertRaises(ValidationError):
                replace(self.config, **change)

    def test_actual_subprocess_deadline_terminates_stuck_search(self):
        began = time.monotonic()
        with patch("scripts.research.detection._child", blocked_search_child):
            with self.assertRaises(TimeoutError):
                bounded_search(curve(), replace(self.config, max_seconds=1))
        self.assertLess(time.monotonic() - began, 4)

    def test_evaluation_requires_phase_and_does_not_call_an_alias_direct_recovery(self):
        truth = {"period_days": 3., "epoch_bjd_tdb": 2458501., "duration_hours": 3.}
        proposal = {"rank": 1, "period_days": 3., "epoch_btjd": 1502., "duration_hours": 3.,
                    "depth_snr_white": 100., "diagnostics": {"sampling_gate_passed": True}}
        self.assertFalse(evaluate_proposals([proposal], truth, 1500., 27.)["direct_recovery"])
        proposal.update(epoch_btjd=1501., period_days=6.)
        result = evaluate_proposals([proposal], truth, 1500., 27.)
        self.assertFalse(result["direct_recovery"])
        self.assertEqual(result["proposals"][0]["harmonic_relation"]["period_ratio"], 2)
        proposal["period_days"] = 3.
        self.assertTrue(evaluate_proposals([proposal], truth, 1500., 27.)["direct_recovery"])


class DetectionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "store.sqlite3").initialize()
        self.artifacts = ArtifactStore(self.root / "artifacts", self.store)
        self.protocol = self.store.register_protocol(load_protocol())
        self.path = self.root / "input.npz"
        write_npz(self.path, curve())
        self.kwargs = {"paths": [self.path], "mission": "TESS", "target_id": "SYNTHETIC-TEST",
                       "cohort": "synthetic_fixture", "time_system": "BTJD", "job_key": "test-blind-v1",
                       "config": SearchConfig(max_period_grid=3000, max_signals=1, max_seconds=30)}

    def run_worker(self):
        return run_local_detection(self.store, self.artifacts, self.protocol["id"], **self.kwargs)

    def test_actual_subprocess_persists_arrays_plots_ephemeris_and_idempotent_restart(self):
        first = self.run_worker()
        self.assertEqual(first["proposal_count"], 1)
        self.store = Store(self.store.path).initialize()
        self.artifacts = ArtifactStore(self.artifacts.root, self.store)
        with patch("scripts.research.detection_worker.bounded_search", side_effect=AssertionError("must not rerun")):
            second = self.run_worker()
        self.assertEqual(first, second)
        candidate = self.store.get_candidate(first["candidate_ids"][0])
        self.assertFalse(candidate["detection"]["used_catalog_ephemeris"])
        self.assertIn("model_score", candidate["incomplete_evidence"])
        self.assertIn("shared_inputs", candidate["incomplete_evidence"])
        self.assertGreaterEqual(len(candidate["artifacts"]), 6)
        arrays = next(a for a in candidate["artifacts"] if a["kind"] == "data")
        _, payload = self.artifacts.read(arrays["id"])
        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            self.assertEqual(data["flux"].shape, data["time_btjd"].shape)
            self.assertTrue(np.isfinite(data["flux_err"]).all())
        stages = {s["name"]: s for s in self.store.get_job(first["job_id"])["stages"]}
        self.assertEqual(stages["detection"]["attempts"], 1)
        self.assertEqual(stages["features"]["status"], "queued")

    def test_timeout_is_visible_and_explicit_retry_recovers(self):
        with patch("scripts.research.detection_worker.bounded_search", side_effect=TimeoutError("bounded test timeout")):
            with self.assertRaises(TimeoutError):
                self.run_worker()
        job = self.store.list_records("jobs")[0]
        detection = next(s for s in self.store.get_job(job["id"])["stages"] if s["name"] == "detection")
        self.assertEqual(detection["status"], "failed")
        self.assertEqual(detection["error"]["code"], "TimeoutError")
        self.store.retry_stage(job["id"], "detection", actor="test", reason="Retry after controlled transient failure")
        result = self.run_worker()
        self.assertEqual(result["job_id"], job["id"])
        self.assertEqual(result["proposal_count"], 1)

    def test_partial_publication_retry_deduplicates_immutable_candidate(self):
        original = self.artifacts.put_plot
        calls = [0]
        def interrupted(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("interrupted artifact write")
            return original(*args, **kwargs)
        with patch.object(self.artifacts, "put_plot", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_worker()
        job = self.store.list_records("jobs")[0]
        self.assertEqual(len(self.store.list_records("candidates")), 1)
        self.store.retry_stage(job["id"], "detection", actor="test", reason="Resume after simulated publication interruption")
        result = self.run_worker()
        self.assertEqual(result["proposal_count"], 1)
        self.assertEqual(len(self.store.list_records("candidates")), 1)

    def test_corrupt_fits_has_persisted_acquisition_failure(self):
        bad = self.root / "broken.fits"
        bad.write_bytes(b"not FITS")
        self.kwargs["paths"] = [bad]
        with self.assertRaises(ValidationError):
            self.run_worker()
        job = self.store.list_records("jobs")[0]
        acquisition = next(s for s in self.store.get_job(job["id"])["stages"] if s["name"] == "acquisition")
        self.assertEqual(acquisition["status"], "failed")
        self.assertFalse(acquisition["error"]["retryable"])
        self.assertEqual(self.store.list_records("candidates"), [])

    def test_same_key_changed_bytes_rejected_without_overwriting(self):
        self.run_worker()
        write_npz(self.path, curve(seed=456))
        with self.assertRaises(ConflictError):
            self.run_worker()
        self.assertEqual(len(self.store.list_records("jobs")), 1)


if __name__ == "__main__":
    unittest.main()
