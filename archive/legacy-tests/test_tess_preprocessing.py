"""Scientific and input-integrity checks for the separate TESS transfer path."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

from scripts.data.tess_preprocessing import (
    BJD_OFFSET, TessPrepConfig, detrend_sector, prepare_star, transit_mask,
)


class TessPreprocessingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tess_preprocess_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cfg = TessPrepConfig(bls_grid_size=2, preview_points=10000)
        self.candidate = {"candidate_id": "TOI-42.01", "tic_id": "42", "period": 2.0,
                          "epoch_bjd": BJD_OFFSET + 101, "duration_hours": 2.4}
        self.time = 100 + np.arange(6 * 720) / 720
        self.ephemeris = (2.0, 101.0, 0.1)
        self.flux = np.where(transit_mask(self.time, self.ephemeris), 980.0, 1000.0)
        self.bls = {"bls_snr": 12.0, "bls_depth": 0.02, "bls_duration": 2.4, "bls_period": 2.0}
        self.bls_patch = patch("scripts.data.tess_preprocessing.compute_bls_features", return_value=self.bls)
        self.mock_bls = self.bls_patch.start()
        self.addCleanup(self.bls_patch.stop)

    def product(self, time=None, flux=None, error=None, quality=None, sector=1,
                reference=BJD_OFFSET, header=None, missing=None, timezero=0):
        time = self.time.copy() if time is None else np.asarray(time, dtype=float)
        flux = self.flux.copy() if flux is None else np.asarray(flux, dtype=float)
        error = np.ones(len(time)) if error is None else error
        quality = np.zeros(len(time), dtype=np.int32) if quality is None else quality
        primary = fits.PrimaryHDU()
        primary.header["TICID"], primary.header["SECTOR"] = 42, sector
        data = {"TIME": time - (reference - BJD_OFFSET) - timezero,
                "PDCSAP_FLUX": flux, "PDCSAP_FLUX_ERR": error, "QUALITY": quality}
        columns = [fits.Column(name=key, format="J" if key == "QUALITY" else "D", array=value)
                   for key, value in data.items() if key != missing]
        table = fits.BinTableHDU.from_columns(columns)
        table.header.update({"TIMEUNIT": "d", "TIMESYS": "TDB", "BJDREFI": reference,
                             "BJDREFF": 0.0, "TIMEREF": "SOLARSYSTEM", "TIMEDEL": 120 / 86400,
                             "TIMEZERO": timezero})
        if header:
            for key, value in header.items():
                if value is None:
                    table.header.remove(key, ignore_missing=True)
                else:
                    table.header[key] = value
        filename = f"synthetic-s{sector:04d}-s_lc.fits"
        relative = f"lightcurves/TIC42/{filename}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        fits.HDUList([primary, table]).writeto(destination, overwrite=True)
        product = {"relative_path": relative, "filename": filename, "tic_id": "42", "sector": sector,
                   "cadence_seconds": 120, "data_uri": f"mast:TESS/product/{filename}"}
        payload = destination.read_bytes()
        receipt = {**product, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
        receipt_path = self.root / "metadata" / "receipts" / (filename + ".json")
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt))
        return product

    def prepare(self, products=None, candidate=None, companions=None):
        candidate = candidate or self.candidate
        products = products if products is not None else [self.product()]
        companions = companions if companions is not None else [candidate]
        return prepare_star(self.root, products, [candidate], companions, self.cfg)[0]

    def test_geometry_channel_major_flat_scalars_and_transit_depth_preserved(self):
        result = self.prepare()
        self.assertEqual(result["status"], "accepted", result)
        for name, shape in [("X_global", (200, 3)), ("X_local", (100, 3)), ("X_scalar", (7,)), ("X", (907,))]:
            self.assertEqual(result[name].shape, shape)
            self.assertEqual(result[name].dtype, np.float32)
            self.assertTrue(np.isfinite(result[name]).all())
        expected = np.concatenate([*(result["X_global"][:, i] for i in range(3)),
                                   *(result["X_local"][:, i] for i in range(3)), result["X_scalar"]])
        np.testing.assert_array_equal(result["X"], expected)
        np.testing.assert_allclose(result["X_scalar"][3:], [12, .02, 2.4, 2])
        in_transit = abs(result["preview_phase"]) < .024
        self.assertAlmostEqual(float(np.median(result["preview_flux"][in_transit])), .98, places=6)
        self.assertAlmostEqual(float(np.median(result["preview_flux"][~in_transit])), 1, places=6)
        self.assertEqual(result["diagnostics"]["n_covered_transit_events"], 3)
        self.assertEqual(result["diagnostics"]["required_points_per_event"], 36)
        self.assertEqual(result["diagnostics"]["bls_scope"], "star_level_all_known_transits_preserved")

    def test_bjd_reference_and_timezero_are_aligned_to_catalog_absolute_epoch(self):
        first = self.prepare([self.product()])
        shifted = self.prepare([self.product(reference=2450000.0, timezero=.25)])
        self.assertEqual(shifted["status"], "accepted", shifted)
        np.testing.assert_allclose(first["preview_time_btjd"], shifted["preview_time_btjd"], atol=1e-11)
        np.testing.assert_allclose(first["preview_phase"], shifted["preview_phase"], atol=1e-7)
        np.testing.assert_allclose(first["preview_flux"], shifted["preview_flux"])
        self.assertEqual(first["diagnostics"]["epoch_btjd"], 101)

    def test_invalid_samples_and_nonzero_quality_are_removed_without_interpolation(self):
        time, flux = self.time.copy(), self.flux.copy()
        error, quality = np.ones(len(time)), np.zeros(len(time), dtype=np.int32)
        time[0], flux[1], error[2], error[3], flux[4], quality[5] = np.nan, np.nan, np.nan, 0, -1, 32
        result = self.prepare([self.product(time, flux, error, quality)])
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(len(result["preview_time_btjd"]), len(time) - 6)
        info = result["diagnostics"]["products"][0]
        self.assertEqual(info["n_invalid_samples"], 5)
        self.assertEqual(info["n_quality_rejected"], 1)
        self.assertEqual(info["n_after_quality"], len(time) - 6)
        self.assertTrue(np.isfinite(result["preview_flux"]).all())

    def test_sector_and_gap_offsets_do_not_dilute_transits_or_create_samples(self):
        time = np.r_[100 + np.arange(3 * 720) / 720, 110 + np.arange(3 * 720) / 720]
        offsets = np.where(time < 105, 1000., 3000.)
        flux = offsets * np.where(transit_mask(time, self.ephemeris), .95, 1.)
        output_time, output_flux, diagnostics = detrend_sector(time, flux, [self.ephemeris], self.cfg)
        np.testing.assert_array_equal(output_time, time)
        self.assertEqual(diagnostics["n_segments"], 2)
        np.testing.assert_allclose(output_flux, np.where(transit_mask(time, self.ephemeris), .95, 1.))
        midpoint = len(time) // 2
        result = self.prepare([self.product(time[:midpoint], flux[:midpoint], sector=1),
                               self.product(time[midpoint:], flux[midpoint:], sector=2)])
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(len(result["preview_time_btjd"]), len(time))
        self.assertFalse(np.any((result["preview_time_btjd"] > 103) & (result["preview_time_btjd"] < 110)))
        self.assertAlmostEqual(float(result["preview_flux"].min()), .95, places=6)

    def test_unsupported_segment_is_dropped_instead_of_borrowing_baseline_across_gap(self):
        time = np.r_[100 + np.arange(720) / 720, 105 + np.arange(20) / 720]
        ephemeris = (2., 105., .1)
        flux = np.where(time < 102, 1000., 800.)
        out_time, out_flux, info = detrend_sector(time, flux, [ephemeris], self.cfg)
        self.assertEqual(info["n_segments"], 2)
        self.assertEqual(info["n_unsupported_baseline_samples"], 20)
        self.assertEqual(len(out_time), 720)
        np.testing.assert_array_equal(out_flux, np.ones(720))

    def test_unknown_companion_transits_are_masked_before_target_coverage_and_folding(self):
        companion = {"candidate_id": "TOI-42.02", "tic_id": "42", "period": 3.,
                     "epoch_bjd": BJD_OFFSET + 102, "duration_hours": 2.4,
                     "disposition": "PC", "selected": False}
        other_ephemeris = (3., 102., .1)
        flux = self.flux * np.where(transit_mask(self.time, other_ephemeris), .9, 1.)
        result = self.prepare([self.product(flux=flux)], companions=[self.candidate, companion])
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(result["diagnostics"]["n_covered_transit_events"], 2)
        self.assertGreater(result["diagnostics"]["n_other_transit_masked"], 100)
        self.assertFalse(transit_mask(result["preview_time_btjd"], other_ephemeris).any())
        self.assertAlmostEqual(float(result["preview_flux"].min()), .98, places=6)
        # Star BLS intentionally retains the companion signal; target views do not.
        bls_time, bls_flux, _ = self.mock_bls.call_args.args
        self.assertEqual(len(bls_time), len(self.time))
        self.assertLess(bls_flux.min(), .9)

    def test_overlapping_companion_events_cannot_satisfy_coverage_and_skip_bls(self):
        companion = {**self.candidate, "candidate_id": "TOI-42.02", "disposition": "PC"}
        result = self.prepare(companions=[self.candidate, companion])
        self.assertEqual(result["reason"], "insufficient_sampled_transit_events")
        self.assertEqual(result["diagnostics"]["n_covered_transit_events"], 0)
        self.mock_bls.assert_not_called()

    def test_three_sample_minimum_applies_even_for_very_short_transits(self):
        short_candidate = {**self.candidate, "duration_hours": .1}
        short_window = transit_mask(self.time, (2., 101., .1 / 24))
        short_keep = ~short_window
        for center in [101., 103., 105.]:
            indices = np.flatnonzero(short_window & (abs(self.time - center) < .01))
            short_keep[indices[:2]] = True
        short_result = self.prepare([self.product(quality=np.where(short_keep, 0, 1))],
                                    candidate=short_candidate)
        self.assertEqual(short_result["reason"], "insufficient_sampled_transit_events")
        self.assertEqual(short_result["diagnostics"]["required_points_per_event"], 3)
        self.assertEqual(short_result["diagnostics"]["n_covered_transit_events"], 0)
        self.mock_bls.assert_not_called()

    def test_missing_ephemeris_of_excluded_companion_rejects_star_explicitly(self):
        companion = {**self.candidate, "candidate_id": "TOI-42.02", "period": np.nan, "selected": False}
        result = self.prepare(companions=[self.candidate, companion])
        self.assertEqual(result["reason"], "companion_missing_or_invalid_ephemeris")
        self.assertEqual(result["diagnostics"]["invalid_companion_id"], "TOI-42.02")
        self.mock_bls.assert_not_called()

    def test_full_duration_half_sampling_minimum_is_enforced(self):
        keep = ~transit_mask(self.time, self.ephemeris)
        for center in [101., 103., 105.]:
            indices = np.flatnonzero(abs(self.time - center) < .049)
            keep[indices[:35]] = True
        quality = np.where(keep, 0, 1)
        result = self.prepare([self.product(quality=quality)])
        self.assertEqual(result["reason"], "insufficient_sampled_transit_events")
        self.assertEqual(result["diagnostics"]["required_points_per_event"], 36)
        self.assertEqual(result["diagnostics"]["n_sampled_transit_events"], 3)
        self.assertEqual(result["diagnostics"]["n_covered_transit_events"], 0)
        self.mock_bls.assert_not_called()

    def test_single_transit_and_too_few_total_points_fail_without_bls(self):
        one_event = self.prepare([self.product(self.time[:1440], self.flux[:1440])])
        self.assertEqual(one_event["reason"], "insufficient_sampled_transit_events")
        too_short = self.prepare([self.product(self.time[:100], self.flux[:100])])
        self.assertEqual(too_short["reason"], "too_few_usable_points")
        self.mock_bls.assert_not_called()

    def test_constant_flux_is_finite_and_coverage_does_not_claim_detection(self):
        self.bls_patch.stop()
        result = self.prepare([self.product(flux=np.full(len(self.time), 1000.))])
        self.assertEqual(result["status"], "accepted", result)
        self.assertTrue(np.isfinite(result["X"]).all())
        self.assertTrue(result["diagnostics"]["constant_flux"])
        self.assertEqual(result["X_scalar"][0], 0)
        self.assertIn("not_signal_detection", result["diagnostics"]["coverage_interpretation"])
        self.assertEqual(result["X_scalar"][4], 0)  # Real BLS depth on a constant series.

    def test_receipt_same_size_corruption_and_identity_errors_reject_raw_product(self):
        product = self.product()
        path = self.root / product["relative_path"]
        payload = bytearray(path.read_bytes())
        payload[-2880] ^= 1
        path.write_bytes(payload)
        result = self.prepare([product])
        self.assertEqual(result["reason"], "invalid_raw_product")
        self.assertIn("receipt_integrity_mismatch", result["diagnostics"]["input_error"])
        wrong_sector = {**self.product(), "sector": 2}
        result = self.prepare([wrong_sector])
        self.assertIn("fits_identity_mismatch", result["diagnostics"]["input_error"])
        attached_hash = {**self.product(), "sha256": "wrong"}
        result = self.prepare([attached_hash])
        self.assertIn("receipt_integrity_mismatch", result["diagnostics"]["input_error"])

    def test_missing_flux_errors_or_unverifiable_time_reference_fail_closed(self):
        cases = [({"missing": "PDCSAP_FLUX_ERR"}, "missing_required_columns"),
                 ({"header": {"TIMESYS": "UTC"}}, "time_system_not_tdb"),
                 ({"header": {"TIMESYS": None}}, "time_system_not_tdb"),
                 ({"header": {"TIMEUNIT": "s"}}, "time_unit_not_days"),
                 ({"header": {"BJDREFI": None}}, "invalid_bjd_reference"),
                 ({"header": {"BJDREFI": -1}}, "invalid_bjd_reference"),
                 ({"header": {"TIMEREF": "LOCAL"}}, "time_reference_not_barycentric"),
                 ({"header": {"TIMEDEL": 1800 / 86400}}, "header_cadence_not_120_seconds"),
                 ({"time": 100 + np.arange(len(self.time)) / 48}, "measured_cadence_not_120_seconds")]
        for kwargs, expected in cases:
            with self.subTest(expected=expected, kwargs=kwargs):
                result = self.prepare([self.product(**kwargs)])
                self.assertEqual(result["reason"], "invalid_raw_product")
                self.assertIn(expected, result["diagnostics"]["input_error"])

    def test_bls_once_per_star_for_two_targets_and_no_input_writes(self):
        companion = {**self.candidate, "candidate_id": "TOI-42.02", "epoch_bjd": BJD_OFFSET + 101.5}
        product = self.product()
        before = {str(path): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                  for path in self.root.rglob("*") if path.is_file()}
        results = prepare_star(self.root, [product], [self.candidate, companion],
                               [self.candidate, companion], self.cfg)
        self.assertTrue(all(item["status"] == "accepted" for item in results), results)
        self.mock_bls.assert_called_once()
        np.testing.assert_array_equal(results[0]["X_scalar"][3:], results[1]["X_scalar"][3:])
        after = {str(path): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
