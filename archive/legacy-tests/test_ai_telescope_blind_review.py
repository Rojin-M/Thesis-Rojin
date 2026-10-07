import unittest

import numpy as np

from scripts.experiments.ai_telescope_blind_review import (
    common_mode_counts,
    duration_prior,
    known_secondary,
    validate_config,
)


class AITelescopeBlindReviewTests(unittest.TestCase):
    def test_common_mode_counts_neighboring_events_in_same_sector(self):
        sector = np.array([1, 1, 1, 2])
        time = np.array([10., 10.01, 11., 10.005])
        self.assertEqual(common_mode_counts(sector, time, .02).tolist(), [2, 2, 1, 1])

    def test_known_secondary_is_separate_from_primary(self):
        candidate = {"candidate_id": "TOI-X.01", "period_days": 10.,
                     "epoch_bjd_tdb": 2457001., "duration_hours": 4.}
        self.assertEqual(known_secondary(6., [candidate]), ["TOI-X.01"])
        self.assertEqual(known_secondary(1., [candidate]), [])

    def test_duration_prior_prefers_training_center(self):
        score, lower, upper, _, _ = duration_prior(
            np.array([2., 20.]), np.array([1., 2., 2., 3.]), .0, 1.)
        self.assertGreater(score[0], score[1])
        self.assertEqual(lower, 1.)
        self.assertEqual(upper, 3.)

    def test_config_rejects_reversed_quantiles(self):
        value = {"schema_version": 1, "scan_run": "a", "physical_run": "b", "output": "c",
                 "duration_lower_quantile": .9, "duration_upper_quantile": .1,
                 "common_mode_window_days": .02, "maximum_common_mode_targets": 2,
                 "top_events": 10}
        with self.assertRaises(ValueError):
            validate_config(value)


if __name__ == "__main__":
    unittest.main()
