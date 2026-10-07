import unittest

import numpy as np
import torch

from scripts.experiments.behavioral_supermodel_v3 import EXPERTS, collect


class BehavioralV3Tests(unittest.TestCase):
    def test_expert_contract_has_distinct_architectures(self):
        self.assertEqual(len(EXPERTS), len(set(EXPERTS)))
        self.assertIn("transformer", EXPERTS)
        self.assertIn("transit_morphology", EXPERTS)
        self.assertIn("stellar_variability", EXPERTS)

    def test_collection_accepts_unequal_models_per_expert(self):
        class Fixed(torch.nn.Module):
            def __init__(self, value): super().__init__(); self.value = value
            def forward(self, x_global, x_local, x_scalar, x_flat):
                return torch.full((len(x_global),), self.value)
        models = []
        for i, expert in enumerate(EXPERTS):
            count = 1 if expert.startswith(("transit_", "stellar_")) else 3
            models += [({"arm": expert}, Fixed(float(i + seed) / 10)) for seed in range(count)]
        n = 4
        part = {"x_global": torch.ones(n, 200, 3), "x_local": torch.ones(n, 100, 3),
                "x_scalar": torch.ones(n, 7), "x_flat": torch.ones(n, 907), "y": torch.zeros(n)}
        result = collect(models, part, core_config())
        self.assertEqual(result["base"].shape, (n, len(EXPERTS)))
        self.assertTrue(np.isfinite(result["behavior"]).all())


def core_config():
    from scripts.experiments.behavioral_supermodel_v2 import validate_config
    return validate_config({})


if __name__ == "__main__": unittest.main()
