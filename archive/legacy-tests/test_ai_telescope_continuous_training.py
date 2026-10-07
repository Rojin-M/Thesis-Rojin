import unittest

import numpy as np

from scripts.experiments.ai_telescope_continuous_training import (
    factorial_schedule, training_center, validate_config,
)
from scripts.research.pixels import TargetPixels


class ContinuousTrainingTests(unittest.TestCase):
    def test_factorial_schedule_is_deterministic_and_covers_grid(self):
        config = {"depths": [.001, .002], "durations_hours": [1., 2.], "seed": 3}
        ids = [str(x) for x in range(12)]
        first = factorial_schedule(ids, config, "train")
        second = factorial_schedule(ids[::-1], config, "train")
        self.assertEqual(first, second)
        combinations = {(x["depth"], x["duration_hours"]) for x in first.values()}
        self.assertEqual(combinations, {(.001, 1.), (.001, 2.), (.002, 1.), (.002, 2.)})

    def test_role_changes_schedule_without_losing_grid(self):
        config = {"depths": [.001, .002], "durations_hours": [1., 2.], "seed": 3}
        ids = [str(x) for x in range(8)]
        train = factorial_schedule(ids, config, "train")
        selection = factorial_schedule(ids, config, "selection")
        self.assertNotEqual(train, selection)
        self.assertEqual(set((x["depth"], x["duration_hours"]) for x in train.values()),
                         set((x["depth"], x["duration_hours"]) for x in selection.values()))

    def test_config_rejects_unknown_contract(self):
        with self.assertRaises(ValueError):
            validate_config({"schema_version": 1})

    def test_training_center_avoids_large_data_gap(self):
        count = 1000
        quality = np.zeros(count, dtype=int)
        quality[300:750] = 1
        pixels = TargetPixels(np.arange(count)/720., np.ones((count, 2, 2)), quality,
                              np.asarray([[2, 0], [0, 0]]), "42", 1, "x", "x")
        center, start = training_center(pixels, {"window_length": 256, "stride": 128}, 3)
        self.assertGreaterEqual(np.sum(quality[start:start+256] == 0), 128)
        self.assertEqual(quality[np.argmin(np.abs(pixels.time-center))], 0)


if __name__ == "__main__":
    unittest.main()
