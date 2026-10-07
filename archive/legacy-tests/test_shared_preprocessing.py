"""Scientific invariants for the shared Kepler/TESS rebuild."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astropy.io import fits
import numpy as np
import pandas as pd

from scripts.data.shared_preprocessing import (
    SharedConfig, read_kepler, ephemeris, candidate_features, prepare_shared_star,
)
from scripts.data.tess_preprocessing import detrend_sector, transit_mask, _coverage
from scripts.data.prepare_shared_features import pilot_selection, cached_star, validate, plot_pilot, KEPLER_NAME
from scripts.data.tess_dataset import feature_names


class SharedPreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SharedConfig()
        self.candidate = {"candidate_id": "K00001.01", "period": 3.,
                          "epoch_bjd": 2457001., "duration_hours": 3.}
        self.bls = {"bls_snr": 10., "bls_depth": .01, "bls_duration": 3., "bls_period": 3.}

    def test_deep_transits_survive_at_both_native_cadences(self):
        for cadence in (120., 1765.46):
            with self.subTest(cadence=cadence):
                cfg = replace(self.cfg, cadence_seconds=cadence)
                time = np.arange(0., 20., cadence / 86400)
                target = ephemeris(self.candidate)
                inside = transit_mask(time, target)
                flux = np.ones(len(time))
                flux[inside] -= .01
                kept, corrected, _ = detrend_sector(time, flux, [target], cfg)
                depth = 1. - np.median(corrected[transit_mask(kept, target)])
                self.assertAlmostEqual(depth, .01, places=10)
                result = candidate_features(kept, corrected, self.candidate,
                                            {self.candidate["candidate_id"]: target}, cfg, self.bls)
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["arrays"]["X"].shape, (907,))
                self.assertTrue(np.isfinite(result["arrays"]["X"]).all())

    def test_gaps_and_segment_offsets_do_not_set_transit_depth(self):
        target = ephemeris(self.candidate)
        time = np.r_[np.arange(0., 7., 120 / 86400), np.arange(12., 19., 120 / 86400)]
        flux = np.where(time < 10, 100., 500.)
        flux[transit_mask(time, target)] *= .99
        kept, corrected, info = detrend_sector(time, flux, [target], self.cfg)
        self.assertEqual(info["n_segments"], 2)
        np.testing.assert_allclose(corrected[~transit_mask(kept, target)], 1.)
        np.testing.assert_allclose(corrected[transit_mask(kept, target)], .99)

    def test_coverage_uses_physical_duration_and_native_cadence(self):
        target = ephemeris(self.candidate)
        empty = np.array([], dtype=float)
        self.assertEqual(_coverage(empty, target, self.cfg)["required_points_per_event"], 45)
        self.assertEqual(_coverage(empty, target, replace(self.cfg, cadence_seconds=1765.46))
                         ["required_points_per_event"], 4)

    def test_companion_samples_are_removed_before_target_folding(self):
        target = ephemeris(self.candidate)
        other = (5., 2., .1)
        time = np.arange(0., 20., 120 / 86400)
        result = candidate_features(time, np.ones(len(time)), self.candidate,
                                    {self.candidate["candidate_id"]: target, "other": other}, self.cfg, self.bls)
        self.assertEqual(result["diagnostics"]["n_other_transit_masked"], int(transit_mask(time, other).sum()))
        self.assertEqual(len(result["folded"]["phase"]), int((~transit_mask(time, other)).sum()))

    def test_unknown_companion_ephemeris_is_audited_before_reading(self):
        other = {**self.candidate, "candidate_id": "other", "duration_hours": None}
        results, _, _ = prepare_shared_star(Path("/missing"), "kepler", 1, [],
                                             [self.candidate], [other], self.cfg)
        self.assertEqual(results[0]["reason"], "companion_missing_or_invalid_ephemeris")

    def test_kepler_time_reference_quality_and_duplicate_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "quarter.fits"
            primary = fits.PrimaryHDU()
            primary.header.update(KEPLERID=1, QUARTER=2, OBSMODE="long cadence")
            table = fits.BinTableHDU.from_columns([
                fits.Column(name="TIME", format="D", array=[1., 2., 2., 3.]),
                fits.Column(name="PDCSAP_FLUX", format="E", array=[100., 99., 99., 100.]),
                fits.Column(name="PDCSAP_FLUX_ERR", format="E", array=[1.] * 4),
                fits.Column(name="SAP_QUALITY", format="J", array=[1, 0, 0, 0]),
            ])
            table.header.update(TIMESYS="TDB", TIMEUNIT="d", TIMEREF="SOLARSYSTEM",
                                BJDREFI=2454833, BJDREFF=0., TIMEZERO=.125, TIMEDEL=1765.46 / 86400)
            fits.HDUList([primary, table]).writeto(path)
            time, flux, cadence, info = read_kepler(path, 1)
            np.testing.assert_array_equal(time, np.array([2., 3.]) - 2167. + .125)
            np.testing.assert_array_equal(flux, [99., 100.])
            self.assertAlmostEqual(cadence, 1765.46)
            self.assertEqual(info["n_duplicate_times"], 1)
            self.assertEqual(info["n_quality_rejected"], 1)
            with self.assertRaisesRegex(ValueError, "Wrong Kepler star"):
                read_kepler(path, 2)

    def test_pilot_contains_training_stars_and_all_their_siblings(self):
        parent = pd.DataFrame({"star_id": np.repeat(np.arange(20), 2),
                               "y": [0, 1] * 20, "split": ["train"] * 32 + ["test"] * 8})
        pilot = pilot_selection(parent)
        self.assertTrue(pilot.split.eq("train").all())
        self.assertTrue(pilot.groupby("star_id").size().eq(2).all())
        pd.testing.assert_frame_equal(pilot, pilot_selection(parent))

    def test_cached_star_rejects_modified_output(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for directory in ("stars", "bls", "folded", "views"):
                (base / "data/interim/kepler/shared_v1" / directory).mkdir(parents=True)
            task = (base, "kepler", 1, [], [self.candidate], [], self.cfg, "frozen")
            results = ([{"candidate_id": self.candidate["candidate_id"], "status": "rejected",
                         "reason": "no_native_lightcurves", "diagnostics": {}}], {}, [])
            with patch("scripts.data.prepare_shared_features.prepare_shared_star", return_value=results):
                self.assertFalse(cached_star(task)[1])
            self.assertTrue(cached_star(task)[1])
            (base / "data/interim/kepler/shared_v1/bls/1.json").write_text("changed")
            with self.assertRaisesRegex(ValueError, "Cached output changed"):
                cached_star(task)

    def test_preview_reads_numeric_views_without_legacy_object_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "data/processed/kepler/v0"
            source.mkdir(parents=True)
            arrays = {"X_global": np.zeros((1, 200, 3)), "X_local": np.zeros((1, 100, 3))}
            np.savez(source / KEPLER_NAME, **arrays, legacy_metadata=np.array([{"unused": True}], dtype=object))
            manifest = pd.DataFrame({"candidate_id": ["K00001.01"], "y": [1], "parent_row_index": [0]})
            plot_pilot(base, "kepler", manifest, arrays, base)
            self.assertTrue((base / "training_preview.png").is_file())

    def test_survivors_keep_original_split_membership(self):
        parent = pd.DataFrame({"candidate_id": [f"K{i}" for i in range(8)], "star_id": range(1, 9),
                               "y": [0, 1] * 4, "split_group": [f"KIC-{i}" for i in range(1, 9)],
                               "parent_row_index": range(8), "split": ["train"] * 4 + ["val"] * 2 + ["test"] * 2,
                               "period": [3.] * 8, "epoch_bjd": [2457001.] * 8, "duration_hours": [3.] * 8})
        manifest = parent.iloc[[2, 3, 4, 5, 6, 7]].copy()
        arrays = {"X_global": np.zeros((6, 200, 3), np.float32), "X_local": np.zeros((6, 100, 3), np.float32),
                  "X_scalar": np.zeros((6, 7), np.float32), "X": np.zeros((6, 907), np.float32),
                  "y": manifest.y.to_numpy()}
        arrays["feature_names"], arrays["scalar_feature_names"] = feature_names()
        splits = {"train_idx": np.array([0, 1]), "val_idx": np.array([2, 3]), "test_idx": np.array([4, 5])}
        validate(arrays, manifest, splits, parent)
        manifest.loc[manifest.index[0], "split"] = "test"
        with self.assertRaisesRegex(ValueError, "Parent mapping changed"):
            validate(arrays, manifest, splits, parent)


if __name__ == "__main__":
    unittest.main()
