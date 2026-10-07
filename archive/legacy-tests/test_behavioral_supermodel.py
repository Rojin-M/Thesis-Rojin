import numpy as np
import torch
import unittest

from scripts.experiments.behavioral_supermodel import (
    PROBES, apply_transform, diagnostic_probe, fit_transform, validate_config,
)


def part(n=4):
    return {
        "x_global": torch.ones((n, 200, 3)),
        "x_local": torch.ones((n, 100, 3)),
        "x_scalar": torch.ones((n, 7)),
        "x_flat": torch.ones((n, 907)),
        "y": torch.tensor([0, 1, 0, 1], dtype=torch.float32),
    }


class BehavioralSupermodelTests(unittest.TestCase):
    def test_probes_are_deterministic_and_never_change_labels(self):
        source = part()
        original = source["y"].clone()
        for name in PROBES:
            first = diagnostic_probe(source, name)
            second = diagnostic_probe(source, name)
            self.assertNotIn("y", first)
            for key in first:
                self.assertTrue(torch.equal(first[key], second[key]))
            self.assertTrue(torch.equal(source["y"], original))

    def test_occlusions_target_only_declared_branch(self):
        source = part()
        global_probe = diagnostic_probe(source, "global_occlusion")
        self.assertEqual(torch.count_nonzero(global_probe["x_global"]), 0)
        self.assertTrue(torch.equal(global_probe["x_local"], source["x_local"]))
        scalar_probe = diagnostic_probe(source, "scalar_occlusion")
        self.assertEqual(torch.count_nonzero(scalar_probe["x_scalar"]), 0)
        self.assertTrue(torch.equal(scalar_probe["x_global"], source["x_global"]))

    def test_feature_transform_handles_constant_columns(self):
        values = np.asarray([[1, 2], [1, 4]], dtype=np.float32)
        transform = fit_transform(values)
        result = apply_transform(values, transform)
        self.assertTrue(np.isfinite(result).all())
        self.assertTrue(np.all(result[:, 0] == 0))

    def test_config_rejects_unknown_or_unsafe_values(self):
        self.assertEqual(validate_config({})["hidden_units"], 12)
        with self.assertRaises(ValueError):
            validate_config({"jitter_std": 1.0})
        with self.assertRaises(ValueError):
            validate_config({"future_magic": True})
