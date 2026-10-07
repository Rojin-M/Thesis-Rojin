import unittest

import numpy as np

from scripts.experiments.crossfit_supermodel_v2 import (
    blend_logits, fit_model, meta_logits, validate_config,
)


class CrossfitSupermodelV2Tests(unittest.TestCase):
    def config(self):
        return validate_config({"max_iterations": 60, "minimum_leaf_samples": 5})

    def test_nonlinear_model_learns_joint_expert_failure_pattern(self):
        rng = np.random.default_rng(4)
        context = rng.normal(size=(500, 4)).astype(np.float32)
        labels = ((context[:, 0] > 0) ^ (context[:, 1] > 0)).astype(int)
        model = fit_model(context, labels, self.config(), 7, 1.)
        logits = meta_logits(model, context)
        self.assertGreater(np.mean((logits >= 0) == labels), .9)

    def test_blend_endpoints_are_exact(self):
        static = np.array([-2., 2.], dtype=np.float32)
        meta = np.array([3., -3.], dtype=np.float32)
        np.testing.assert_array_equal(blend_logits(static, meta, 0.), static)
        np.testing.assert_array_equal(blend_logits(static, meta, 1.), meta)

    def test_invalid_config_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_config({"unknown": 1})
        with self.assertRaises(ValueError):
            validate_config({"blend_grid": [.1, 1.]})


if __name__ == "__main__":
    unittest.main()
