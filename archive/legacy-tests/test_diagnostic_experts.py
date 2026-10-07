import unittest

import numpy as np
import torch

from scripts.experiments.diagnostic_experts import DiagnosticExpert, extract_features, validate_config


class DiagnosticExpertTests(unittest.TestCase):
    def inputs(self, n=4):
        g, l = torch.randn(n, 200, 3), torch.randn(n, 100, 3)
        g[:, :, 2] = 1; l[:, :, 2] = 1
        return g, l, torch.randn(n, 7), torch.randn(n, 907)

    def test_both_feature_families_are_finite_and_distinct(self):
        g, l, s, _ = self.inputs()
        physical = extract_features(g, l, s, "transit_morphology")
        variability = extract_features(g, l, s, "stellar_variability")
        self.assertEqual(len(physical), 4); self.assertEqual(len(variability), 4)
        self.assertTrue(np.isfinite(physical).all() and np.isfinite(variability).all())
        self.assertNotEqual(physical.shape[1], variability.shape[1])

    def test_safe_linear_artifact_forward(self):
        g, l, s, flat = self.inputs()
        features = extract_features(g, l, s, "transit_morphology")
        model = DiagnosticExpert("transit_morphology", np.zeros(features.shape[1]),
                                 np.ones(features.shape[1]), np.ones(features.shape[1]), 0.)
        result = model(g, l, s, flat)
        self.assertEqual(result.shape, (4,)); self.assertTrue(torch.isfinite(result).all())

    def test_fully_missing_view_has_finite_explicit_features(self):
        g, l, s, _ = self.inputs()
        g[:] = 0; l[:] = 0
        for kind in ("transit_morphology", "stellar_variability"):
            self.assertTrue(np.isfinite(extract_features(g, l, s, kind)).all())

    def test_config_validation(self):
        self.assertEqual(validate_config({})["max_iterations"], 2000)
        with self.assertRaises(ValueError): validate_config({"c_grid": [0.]})


if __name__ == "__main__": unittest.main()
