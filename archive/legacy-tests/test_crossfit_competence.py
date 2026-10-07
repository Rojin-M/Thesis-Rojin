import unittest

import numpy as np
import torch

from scripts.experiments.crossfit_competence import (
    fit_competence, make_folds, predicted_loss, route, validate_config,
)


class CrossfitCompetenceTests(unittest.TestCase):
    def test_groups_never_cross_fold_and_every_row_is_held_out(self):
        labels = np.tile([0., 1.], 30)
        part = {"y": torch.tensor(labels),
                "metadata": [{"split_group": f"g{i}"} for i in range(len(labels))]}
        folds = make_folds(part, 5, 11)
        heldout = np.concatenate([test for _, test in folds])
        np.testing.assert_array_equal(np.sort(heldout), np.arange(len(labels)))
        for train, test in folds:
            self.assertFalse(set(train) & set(test))

    def test_competence_regression_routes_different_regimes(self):
        x = np.linspace(-2, 2, 400, dtype=np.float32)[:, None]
        labels = (np.arange(len(x)) % 2).astype(np.float32)
        signed = labels * 2 - 1
        base = np.column_stack([
            np.where(x[:, 0] < 0, signed * 5, -signed * 5),
            np.where(x[:, 0] >= 0, signed * 5, -signed * 5),
        ]).astype(np.float32)
        available = np.ones_like(base, dtype=bool)
        coefficient, intercept = fit_competence(x, base, available, labels, 1., 10.)
        expected = predicted_loss(x, coefficient, intercept, 10.)
        fused, weights = route(base, available, np.array([.5, .5]), expected, 4.)
        self.assertGreater(np.mean((fused >= 0) == labels), .9)
        self.assertGreater(weights[x[:, 0] < 0, 0].mean(), weights[x[:, 0] < 0, 1].mean())
        self.assertGreater(weights[x[:, 0] >= 0, 1].mean(), weights[x[:, 0] >= 0, 0].mean())

    def test_missing_expert_gets_zero_weight(self):
        base = np.ones((2, 2), dtype=np.float32)
        available = np.array([[True, False], [True, True]])
        _, weights = route(base, available, np.array([.5, .5]), np.zeros_like(base), 1.)
        self.assertEqual(weights[0, 1], 0.)
        self.assertEqual(weights[0, 0], 1.)

    def test_invalid_config_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_config({"unknown": 1})
        with self.assertRaises(ValueError):
            validate_config({"folds": 2})


if __name__ == "__main__":
    unittest.main()
