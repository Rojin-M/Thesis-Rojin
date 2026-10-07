"""Exercise resumable star caches without FITS processing, BLS, or network I/O."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.data import tess_prepare_features as preparation
from scripts.data.tess_preprocessing import TessPrepConfig


class TessPreparationCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tess_preparation_cache_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw_root = self.root / "raw"
        self.cache_dir = self.root / "cache"
        self.cache_dir.mkdir()
        self.raw_path = self.raw_root / "lightcurves/TIC42/sector1.fits"
        self.raw_path.parent.mkdir(parents=True)
        self.payload = b"immutable raw product fixture; flux processing is mocked"
        self.raw_path.write_bytes(self.payload)
        self.products = [{"tic_id": 42, "sector": 1,
                          "relative_path": "lightcurves/TIC42/sector1.fits",
                          "sha256": hashlib.sha256(self.payload).hexdigest(),
                          "size_bytes": len(self.payload)}]
        self.candidates = [{"candidate_id": "TOI-42.01", "tic_id": 42, "period": 3.,
                            "epoch_bjd": 2459000., "duration_hours": 2., "y": 1}]
        self.companions = self.candidates + [
            {"candidate_id": "TOI-42.02", "tic_id": 42, "period": 5.,
             "epoch_bjd": 2459001., "duration_hours": 3., "tfopwg_disp": "PC"}]
        self.cfg = TessPrepConfig()

    def task(self, *, products=None, candidates=None, companions=None):
        return (self.raw_root, self.cache_dir, "fixed-science-signature",
                deepcopy(self.products if products is None else products),
                deepcopy(self.candidates if candidates is None else candidates),
                deepcopy(self.companions if companions is None else companions), self.cfg)

    @staticmethod
    def results():
        return [
            {"candidate_id": "TOI-42.01", "status": "accepted", "reason": "",
             "diagnostics": {"n_covered_transit_events": 4, "sectors": [1]},
             "X_global": np.arange(12, dtype=np.float32).reshape(3, 4),
             "X_scalar": np.array([.01, .02, .03], dtype=np.float32),
             "preview_phase": np.array([-.02, 0., .02], dtype=np.float64)},
            {"candidate_id": "TOI-42.02", "status": "rejected",
             "reason": "insufficient_transit_events", "diagnostics": {"events": 1}},
        ]

    def assert_results_equal(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for restored, original in zip(actual, expected):
            self.assertEqual(set(restored), set(original))
            for key, value in original.items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(restored[key], value)
                    self.assertEqual(restored[key].dtype, value.dtype)
                else:
                    self.assertEqual(restored[key], value)

    def test_identical_task_reuses_arrays_and_metadata_without_reprocessing(self):
        expected = self.results()
        with patch.object(preparation, "prepare_star", return_value=deepcopy(expected)) as prepare:
            built, was_cached = preparation.cached_star(self.task())
            restored, was_reused = preparation.cached_star(self.task())
        self.assertFalse(was_cached)
        self.assertTrue(was_reused)
        prepare.assert_called_once()
        self.assert_results_equal(built, expected)
        self.assert_results_equal(restored, expected)
        self.assertEqual(self.raw_path.read_bytes(), self.payload)
        self.assertEqual(len(list(self.cache_dir.glob("*.npz"))), 1)
        self.assertEqual(len(list(self.cache_dir.glob("*.json"))), 1)
        self.assertFalse(list(self.cache_dir.glob("*.part")))

    def test_changed_candidate_ephemeris_companion_or_product_gets_a_new_cache(self):
        candidate_update = deepcopy(self.candidates)
        candidate_update[0]["epoch_bjd"] += .02
        companion_update = deepcopy(self.companions)
        companion_update[1]["duration_hours"] += .5
        product_update = deepcopy(self.products)
        product_update[0]["sector"] = 2
        tasks = [self.task(), self.task(candidates=candidate_update),
                 self.task(companions=companion_update), self.task(products=product_update)]
        with patch.object(preparation, "prepare_star", side_effect=lambda *args: self.results()) as prepare:
            for task in tasks:
                _, cached = preparation.cached_star(task)
                self.assertFalse(cached)
            self.assertEqual(prepare.call_count, len(tasks))
            for task in tasks:
                _, cached = preparation.cached_star(task)
                self.assertTrue(cached)
            self.assertEqual(prepare.call_count, len(tasks))
        self.assertEqual(len(list(self.cache_dir.glob("*.json"))), len(tasks))

    def test_corrupted_array_archive_is_rejected_without_recompute_or_record_rewrite(self):
        with patch.object(preparation, "prepare_star", return_value=self.results()):
            preparation.cached_star(self.task())
        array_path = next(self.cache_dir.glob("*.npz"))
        record_path = next(self.cache_dir.glob("*.json"))
        original_record = record_path.read_bytes()
        corrupted = bytearray(array_path.read_bytes())
        corrupted[len(corrupted) // 2] ^= 1
        array_path.write_bytes(corrupted)
        with patch.object(preparation, "prepare_star") as prepare:
            with self.assertRaisesRegex(ValueError, "Cached star TIC42.*checksum"):
                preparation.cached_star(self.task())
            prepare.assert_not_called()
        self.assertEqual(record_path.read_bytes(), original_record)
        self.assertEqual(array_path.read_bytes(), bytes(corrupted))

    def test_raw_mutation_during_processing_never_publishes_a_reusable_record(self):
        def mutate_raw(*args):
            self.raw_path.write_bytes(self.payload + b" changed while preparing")
            return self.results()

        with patch.object(preparation, "prepare_star", side_effect=mutate_raw):
            with self.assertRaisesRegex(ValueError, "Raw input changed during preparation"):
                preparation.cached_star(self.task())
        self.assertFalse(list(self.cache_dir.glob("*.json")))
        # An orphan array file from an interrupted/failed attempt cannot count
        # as a hit. Restoring the input must trigger one fresh preparation.
        self.raw_path.write_bytes(self.payload)
        with patch.object(preparation, "prepare_star", return_value=self.results()) as prepare:
            _, cached = preparation.cached_star(self.task())
            self.assertFalse(cached)
            prepare.assert_called_once()
            _, cached = preparation.cached_star(self.task())
            self.assertTrue(cached)
            prepare.assert_called_once()

    def test_transient_fatal_failure_is_retried_then_successfully_cached(self):
        failed = [{"candidate_id": "TOI-42.01", "status": "rejected",
                   "reason": "preprocessing_error", "diagnostics": {"error": "temporary I/O failure"}}]
        expected = self.results()
        with patch.object(preparation, "prepare_star", side_effect=[failed, deepcopy(expected)]) as prepare:
            first, cached = preparation.cached_star(self.task())
            self.assertFalse(cached)
            self.assertEqual(first, failed)
            self.assertFalse(list(self.cache_dir.iterdir()))
            recovered, cached = preparation.cached_star(self.task())
            self.assertFalse(cached)
            self.assert_results_equal(recovered, expected)
            self.assertEqual(prepare.call_count, 2)
            restored, cached = preparation.cached_star(self.task())
            self.assertTrue(cached)
            self.assert_results_equal(restored, expected)
            self.assertEqual(prepare.call_count, 2)

    def test_changed_raw_bytes_reject_an_existing_cache(self):
        with patch.object(preparation, "prepare_star", return_value=self.results()):
            preparation.cached_star(self.task())
        self.raw_path.write_bytes(self.payload + b" modified after cache creation")
        with patch.object(preparation, "prepare_star") as prepare:
            with self.assertRaisesRegex(ValueError, "Raw product changed"):
                preparation.cached_star(self.task())
            prepare.assert_not_called()

    def test_changed_mtime_with_identical_content_still_reuses_cache(self):
        with patch.object(preparation, "prepare_star", return_value=self.results()):
            preparation.cached_star(self.task())
        original = self.raw_path.stat()
        os.utime(self.raw_path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(self.raw_path.stat().st_mtime_ns, original.st_mtime_ns)
        with patch.object(preparation, "prepare_star") as prepare:
            restored, cached = preparation.cached_star(self.task())
            prepare.assert_not_called()
        self.assertTrue(cached)
        self.assert_results_equal(restored, self.results())
        record = json.loads(next(self.cache_dir.glob("*.json")).read_text())
        self.assertEqual(record["raw_stats"][self.products[0]["relative_path"]],
                         [original.st_size, original.st_mtime_ns])


if __name__ == "__main__":
    unittest.main()
