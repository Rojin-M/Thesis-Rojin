"""Synthetic contracts for TLS behavior and target-pixel diagnostics."""
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
import numpy as np

from scripts.experiments.tls_pixel_pilot import validate_config
from scripts.research.pixels import (difference_image_diagnostics, read_target_pixels,
                                     target_pixel_product)
from scripts.research.protocol import ValidationError
from scripts.research.tls_search import ephemeris_agreement


def write_tpf(path, target="123"):
    rng = np.random.default_rng(7)
    time = np.arange(1500, 1508, .02)
    cube = np.full((len(time), 5, 5), 10., np.float32)
    cube[:, 2, 2] += 1000
    cube[:, 1, 3] += 200
    cube += rng.normal(0, .5, cube.shape)
    phase = (time - 1500.5 + 1) % 2 - 1
    cube[np.abs(phase) <= .06, 1, 3] -= 40
    columns = [fits.Column(name="TIME", format="D", array=time),
               fits.Column(name="FLUX", format="25E", dim="(5,5)", array=cube),
               fits.Column(name="QUALITY", format="J", array=np.zeros(len(time), np.int32))]
    primary = fits.PrimaryHDU()
    primary.header.update(TICID=int(target), SECTOR=1)
    pixels = fits.BinTableHDU.from_columns(columns, name="PIXELS")
    pixels.header.update(TIMESYS="TDB", TIMEREF="SOLARSYSTEM", TIMEUNIT="d",
                         BJDREFI=2457000, BJDREFF=0., TIMEZERO=0.)
    aperture = np.zeros((5, 5), np.int16); aperture[1:4, 1:4] = 2
    fits.HDUList([primary, pixels, fits.ImageHDU(aperture, name="APERTURE")]).writeto(path, checksum=True)


class TargetPixelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "tess2020000000000-s0001-0000000000000123-0001-s_tp.fits"
        write_tpf(self.path)

    def test_product_derivation_is_strict_and_public(self):
        product = target_pixel_product("tess2020000000000-s0001-0000000000000123-0001-s_lc.fits")
        self.assertEqual(product["tic_id"], "123")
        self.assertTrue(product["filename"].endswith("_tp.fits"))
        self.assertIn("/0000/0000/0000/0123/", product["url"])
        with self.assertRaises(ValidationError):
            target_pixel_product("untrusted.fits")

    def test_difference_image_localizes_off_target_dimming(self):
        pixels = read_target_pixels(self.path, "123")
        result = difference_image_diagnostics(pixels, {"period_days": 2., "epoch_btjd": 1500.5,
                                                        "duration_hours": 2.88})
        self.assertGreater(result["source_localization"]["offset_pixels"], .5)
        self.assertGreater(result["source_localization"]["peak_difference_snr"], 20)
        self.assertEqual(result["source_localization"]["peak_difference_pixel_yx"], [1, 3])
        self.assertGreaterEqual(result["cadences"]["in_transit"], 10)
        self.assertEqual(result["maps"]["difference"].shape, (5, 5))

    def test_identity_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "identity"):
            read_target_pixels(self.path, "999")


class PilotContractTests(unittest.TestCase):
    def test_period_alias_behavior_is_explicit(self):
        bls = {"period_days": 4., "epoch_btjd": 1500., "duration_hours": 3.}
        tls = {"period_days": 2., "epoch_btjd": 1500., "duration_hours": 2.}
        result = ephemeris_agreement(bls, tls)
        self.assertEqual(result["tls_period_multiplier"], 2.)
        self.assertTrue(result["agrees_within_one_duration"])

    def test_config_rejects_unbounded_product(self):
        import json
        config = json.loads(Path("configs/tls_pixel_pilot_v1.json").read_text())
        self.assertEqual(validate_config(config), config)
        config["max_product_bytes"] = 10 ** 12
        with self.assertRaises(ValueError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
