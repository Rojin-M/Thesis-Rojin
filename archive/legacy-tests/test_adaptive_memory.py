import unittest

import numpy as np

from scripts.experiments.adaptive_memory import (
    MemoryConfig, MultiTimescaleTestTimeMemory, evaluate_run, synthetic_curve,
)


class AdaptiveMemoryTests(unittest.TestCase):
    def test_protection_uses_observations_and_preserves_transit_updates(self):
        curve = synthetic_curve(12, .01)
        memory = MultiTimescaleTestTimeMemory()
        protected = memory.run(curve["flux"], "protected")
        adaptive = memory.run(curve["flux"], "adaptive")
        self.assertGreater(protected["protected"][curve["transit_mask"]].mean(), .7)
        self.assertLess(protected["protected"][~curve["transit_mask"]].mean(), .2)
        self.assertGreater(evaluate_run(curve, protected)["depth_retention_fraction"],
                           evaluate_run(curve, adaptive)["depth_retention_fraction"])

    def test_each_target_starts_from_reset_deterministic_memory(self):
        curve = synthetic_curve(4, .005)
        memory = MultiTimescaleTestTimeMemory()
        first = memory.run(curve["flux"], "adaptive")
        second = memory.run(curve["flux"], "adaptive")
        np.testing.assert_array_equal(first["prediction"], second["prediction"])

    def test_invalid_inputs_and_configuration_fail_closed(self):
        with self.assertRaises(ValueError):
            MultiTimescaleTestTimeMemory(MemoryConfig(warmup=2))
        with self.assertRaises(ValueError):
            MultiTimescaleTestTimeMemory().run(np.ones(40), "unknown")
        bad = np.ones(40); bad[2] = np.nan
        with self.assertRaises(ValueError):
            MultiTimescaleTestTimeMemory().run(bad)


if __name__ == "__main__":
    unittest.main()
