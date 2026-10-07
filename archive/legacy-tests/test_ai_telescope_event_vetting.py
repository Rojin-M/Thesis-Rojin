"""Scientific regression checks for local event evidence and catalog provenance."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
from astropy.wcs import WCS
import numpy as np
import pandas as pd

from scripts.experiments.ai_telescope_event_vetting import validate_config
from scripts.research.event_vetting import (event_masks, local_difference, parse_gaia,
    periodic_event_matches, project_gaia, review_flags, single_event_pixels)
from scripts.research.pixels import TargetPixels
from scripts.research.protocol import ValidationError


class EventVettingTests(unittest.TestCase):
    def test_single_event_does_not_fold_other_occurrences(self):
        t = np.arange(0, 10, .01)
        inside, outside = event_masks(t, np.zeros(len(t)), 3.9, 4.1)
        self.assertTrue(np.all((t[inside] >= 3.9) & (t[inside] <= 4.1)))
        self.assertFalse(inside[np.argmin(abs(t-2))])
        self.assertFalse(outside[np.argmin(abs(t-6))])

    def test_rejects_one_sided_baseline(self):
        t = np.arange(4, 6, .01)
        with self.assertRaisesRegex(ValidationError, "two-sided"):
            event_masks(t, np.zeros(len(t)), 4.05, 4.15)

    def test_masks_other_events_from_baseline(self):
        t = np.arange(3, 5, .01)
        _, outside = event_masks(t, np.zeros(len(t)), 3.9, 4.1, [(4.3, 4.5)])
        self.assertFalse(outside[(t >= 4.3) & (t <= 4.5)].any())

    def test_linear_drift_does_not_manufacture_a_depth(self):
        t = np.arange(3, 5, .01)
        inside, outside = event_masks(t, np.zeros(len(t)), 3.9, 4.1)
        y = 1000 + 150 * (t-4)
        base, depth, _, _ = local_difference(t, y, inside, outside, 4)
        self.assertAlmostEqual(float(base), 1000)
        self.assertAlmostEqual(float(depth), 0)
        y[inside] -= 10
        _, depth, _, _ = local_difference(t, y, inside, outside, 4)
        self.assertAlmostEqual(float(depth), 10)

    def test_missing_pixels_are_not_zero_filled(self):
        t = np.arange(3, 5, .01)
        inside, outside = event_masks(t, np.zeros(len(t)), 3.9, 4.1)
        y = np.ones((len(t), 2)); y[np.flatnonzero(inside)[0], 1] = np.nan
        _, depth, _, _ = local_difference(t, y, inside, outside, 4)
        self.assertTrue(np.isnan(depth[1]))
        self.assertAlmostEqual(depth[0], 0)

    def test_single_off_target_dimming_is_localized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.fits"
            wcs = WCS(naxis=2)
            wcs.wcs.crpix = [4, 4]; wcs.wcs.cdelt = [-.0058, .0058]
            wcs.wcs.crval = [20, 30]; wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
            primary = fits.PrimaryHDU(); primary.header.update(RA_OBJ=20., DEC_OBJ=30.)
            fits.HDUList([primary, fits.BinTableHDU(), fits.ImageHDU(np.zeros((7, 7)), header=wcs.to_header())]).writeto(path)
            t = np.arange(3, 5, .005)
            rng = np.random.default_rng(81)
            cube = np.full((len(t), 7, 7), 10.) + rng.normal(0, .2, (len(t), 7, 7))
            cube[:, 3, 3] += 1000; cube[:, 3, 5] += 300
            cube[(t >= 3.9) & (t <= 4.1), 3, 5] -= 50
            aperture = np.full((7, 7), 2)
            pixels = TargetPixels(t, cube, np.zeros(len(t)), aperture, "123", 1, "synthetic", str(path))
            result, _ = single_event_pixels(pixels, 3.9, 4.1)
            self.assertGreater(result["localization"]["offset_pixels"], 1.8)
            self.assertGreater(result["photometry"]["pipeline"]["depth_snr_white"], 20)
            self.assertIn("difference_source_offset_at_least_one_pixel", review_flags(result, "complete", []))

    def test_gaia_integer_identity_never_rounds_to_float(self):
        payload = b"source_id,ra,dec,ref_epoch,pmra,pmdec,phot_g_mean_mag\n3538256868047046656,20,30,2016,0,0,12\n"
        self.assertEqual(parse_gaia(payload).iloc[0].source_id, "3538256868047046656")
        with self.assertRaisesRegex(ValidationError, "truncated"):
            parse_gaia(payload, limit=0)

    def test_gaia_proper_motion_and_missing_motion_are_explicit(self):
        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [4, 4]; wcs.wcs.cdelt = [-.0058, .0058]
        wcs.wcs.crval = [20, 30]; wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        frame = pd.DataFrame([dict(source_id="123", ra=20., dec=30., ref_epoch=2016., pmra=1000., pmdec=0., phot_g_mean_mag=12.),
                              dict(source_id="456", ra=20., dec=30., ref_epoch=2016., pmra=np.nan, pmdec=np.nan, phot_g_mean_mag=13.)])
        rows = project_gaia(frame, wcs, 2460676.5-2457000, (7, 7), (20, 30))
        self.assertTrue(rows[0]["proper_motion_applied"])
        self.assertFalse(rows[1]["proper_motion_applied"])
        self.assertGreater(abs(rows[0]["pixel_x"]-rows[1]["pixel_x"]), .3)

    def test_periodic_match_uses_interval_overlap(self):
        searches = {"tls": {"status": "complete", "peaks": [{"period_days": 2., "epoch_btjd": 4., "duration_hours": 2.}]}}
        self.assertEqual(len(periodic_event_matches(5.98, 6.1, searches)), 1)
        self.assertEqual(periodic_event_matches(5.1, 5.2, searches), [])

    def test_config_rejects_unbounded_paths_and_time(self):
        config = json.loads(Path("configs/ai_telescope_event_vetting_v1.json").read_text())
        validate_config(config)
        for key, value in (("output", "../outside"), ("search_timeout_seconds", 999999)):
            bad = copy.deepcopy(config); bad[key] = value
            with self.assertRaises(ValueError):
                validate_config(bad)


if __name__ == "__main__":
    unittest.main()
