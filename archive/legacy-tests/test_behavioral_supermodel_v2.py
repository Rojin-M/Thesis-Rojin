import unittest

import numpy as np
import torch

from scripts.experiments.behavioral_supermodel_v2 import ConvexStack, calibration_alpha, probe, validate_config


class BehavioralV2Tests(unittest.TestCase):
    def fixture(self):
        n = 5
        return {"x_global": torch.ones(n, 200, 3), "x_local": torch.ones(n, 100, 3),
                "x_scalar": torch.ones(n, 7), "x_flat": torch.ones(n, 907),
                "y": torch.tensor([0, 1, 0, 1, 0.])}

    def test_probes_are_deterministic_and_label_free(self):
        c = validate_config({})
        for name in ("cadence_dropout", "depth_attenuation", "small_jitter"):
            a, b = probe(self.fixture(), name, c), probe(self.fixture(), name, c)
            self.assertNotIn("y", a)
            self.assertTrue(all(torch.equal(a[key], b[key]) for key in a))

    def test_missing_experts_are_masked(self):
        model = ConvexStack(3)
        logits = torch.tensor([[1., 50., 3.]])
        availability = torch.tensor([[True, False, True]])
        result, weights = model(logits, availability)
        self.assertEqual(float(weights[0, 1]), 0.)
        self.assertAlmostEqual(float(result), 2., places=6)
        with self.assertRaises(ValueError): model(logits, torch.zeros_like(availability))

    def test_alpha_is_selected_only_from_supplied_calibration_rows(self):
        y = np.array([0., 1., 0., 1.])
        baseline = np.zeros(4)
        helpful = np.array([-2., 2., -2., 2.])
        result = calibration_alpha(y, baseline, helpful, [0., .5, 1.])
        self.assertEqual(result["selected"], 1.)
        harmful = calibration_alpha(y, baseline, -helpful, [0., .5, 1.])
        self.assertEqual(harmful["selected"], 0.)


if __name__ == "__main__": unittest.main()
