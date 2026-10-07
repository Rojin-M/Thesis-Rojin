import unittest

import numpy as np
import torch

from scripts.experiments.behavioral_supermodel_v5 import (
    DiagnosticRouter, apply_routers, train_router, validate_config,
)


class DiagnosticRouterTests(unittest.TestCase):
    def config(self):
        return validate_config({"router_seeds": [7], "steps": 300,
                                "shrinkage_grid": [0., 1.], "prior_kl_grid": [.01]})

    def test_router_learns_which_expert_owns_a_diagnostic_regime(self):
        rng = np.random.default_rng(8)
        context = rng.normal(size=(300, 2)).astype(np.float32)
        labels = (context[:, 0] > 0).astype(np.float32)
        signed = labels * 2 - 1
        first = np.where(context[:, 1] < 0, signed * 5, -signed * 5)
        second = np.where(context[:, 1] >= 0, signed * 5, -signed * 5)
        logits = np.column_stack([first, second]).astype(np.float32)
        available = np.ones_like(logits, dtype=bool)
        model = train_router(context, logits, available, labels, np.array([.5, .5], np.float32),
                             np.ones((2, 2), np.float32), self.config(), 1., .01, 7)
        fused, weights = apply_routers([model], context, logits, available)
        self.assertGreater(np.mean((fused >= 0) == labels), .95)
        self.assertGreater(weights[context[:, 1] < 0, 0].mean(), .7)
        self.assertGreater(weights[context[:, 1] >= 0, 1].mean(), .7)

    def test_static_router_reproduces_prior_and_masks_missing_expert(self):
        prior = np.array([.8, .2], dtype=np.float32)
        model = DiagnosticRouter(prior, np.ones((2, 1), np.float32), 0.)
        context = np.zeros((2, 1), dtype=np.float32)
        logits = np.array([[1., 3.], [1., 3.]], dtype=np.float32)
        available = np.array([[True, True], [False, True]])
        fused, weights = apply_routers([model], context, logits, available)
        np.testing.assert_allclose(weights[0], prior, atol=1e-6)
        np.testing.assert_allclose(weights[1], [0., 1.], atol=1e-6)
        np.testing.assert_allclose(fused, [1.4, 3.], atol=1e-6)

    def test_forbidden_feature_cannot_change_routes(self):
        model = DiagnosticRouter(np.array([.5, .5], np.float32),
                                 np.array([[1., 0.], [1., 0.]], np.float32), 1.)
        with torch.no_grad():
            model.coefficient[:, 1] = torch.tensor([100., -100.])
        logits = np.ones((2, 2), dtype=np.float32)
        available = np.ones_like(logits, dtype=bool)
        _, a = apply_routers([model], np.array([[0., -10.], [0., 10.]], np.float32), logits, available)
        np.testing.assert_allclose(a[0], a[1], atol=1e-6)

    def test_invalid_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_config({"unknown": 1})
        with self.assertRaises(ValueError):
            validate_config({"shrinkage_grid": [.1, 1.]})


if __name__ == "__main__":
    unittest.main()
