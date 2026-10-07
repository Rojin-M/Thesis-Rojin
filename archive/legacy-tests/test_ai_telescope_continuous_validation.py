import unittest

import numpy as np

from scripts.experiments.ai_telescope_continuous_validation import (
    condition_schedule, inject_transits, inverted_residual_control,
    select_threshold, validate_config,
)
from scripts.research.pixels import TargetPixels


def pixels():
    count = 1200
    time = np.arange(count) / 720.
    flux = np.full((count, 3, 3), 100., dtype=float)
    flux[:, 1, 1] = 1000. + np.sin(np.arange(count) / 20)
    return TargetPixels(time=time, flux=flux, quality=np.zeros(count, dtype=int),
                        aperture=np.asarray([[0, 0, 0], [0, 2, 0], [0, 0, 0]]),
                        target_id="42", sector=1, sha256="x", path="x",
                        position_correction=None, background_flux=None, context={})


class ContinuousValidationTests(unittest.TestCase):
    def test_spatial_injection_has_requested_aperture_depth(self):
        original = pixels()
        condition = {"depth": .01, "duration_hours": 2., "mode": "single"}
        injected, profile, realized = inject_transits(original, condition, [.8], .15)
        self.assertAlmostEqual(realized, .01, places=7)
        self.assertLess(injected.flux[profile == 1, 1, 1].mean(),
                        original.flux[profile == 1, 1, 1].mean())
        self.assertTrue(np.array_equal(injected.flux[profile == 0], original.flux[profile == 0]))

    def test_residual_inversion_preserves_pixel_medians(self):
        original = pixels()
        control = inverted_residual_control(original)
        self.assertTrue(np.allclose(np.median(control.flux, axis=0),
                                    np.median(original.flux, axis=0)))
        self.assertLess(np.corrcoef(original.flux[:, 1, 1], control.flux[:, 1, 1])[0, 1], -.99)

    def test_condition_schedule_covers_factorial_and_is_deterministic(self):
        config = {"depths": [.001, .002], "durations_hours": [1., 2.],
                  "event_modes": ["single", "periodic"], "seed": 7}
        ids = [str(x) for x in range(16)]
        first = condition_schedule(ids, config, "calibration")
        second = condition_schedule(ids[::-1], config, "calibration")
        self.assertEqual(first, second)
        combinations = {(x["depth"], x["duration_hours"], x["mode"]) for x in first.values()}
        self.assertEqual(len(combinations), 8)

    def test_threshold_selection_uses_control_rate(self):
        rows = [{"exposure_days": 27., "control": {
            "0.80000000": {"candidate_like_events": 3},
            "0.90000000": {"candidate_like_events": 1}}}]
        chosen = select_threshold(rows, [.8, .9], 1.)
        self.assertEqual(chosen["selected_threshold"], .9)
        self.assertTrue(chosen["target_met"])

    def test_config_rejects_role_order_changes(self):
        with self.assertRaises(ValueError):
            validate_config({"schema_version": 1})


if __name__ == "__main__":
    unittest.main()
