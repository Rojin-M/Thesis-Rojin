import unittest

import torch

from scripts.experiments.transformer_expert import validate_transformer_config
from training.transformer_expert import TransitTransformer


class TransformerExpertTests(unittest.TestCase):
    def test_shape_and_masked_forward(self):
        model = TransitTransformer(d_model=16, heads=4)
        inputs = [torch.randn(3, 200, 3), torch.randn(3, 100, 3), torch.randn(3, 7), torch.randn(3, 907)]
        inputs[0][:, :, 2] = 1
        inputs[1][:, :, 2] = 1
        result = model(*inputs)
        self.assertEqual(result.shape, (3,))
        self.assertTrue(torch.isfinite(result).all())

    def test_config_validation(self):
        self.assertEqual(validate_transformer_config({})["d_model"], 32)
        with self.assertRaises(ValueError):
            validate_transformer_config({"d_model": 30, "heads": 4})
        with self.assertRaises(ValueError):
            validate_transformer_config({"device": "gpu"})


if __name__ == "__main__":
    unittest.main()
