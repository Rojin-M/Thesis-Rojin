import unittest
from types import SimpleNamespace

import numpy as np
import torch

from scripts.experiments.ai_telescope_v2 import (
    CONTEXT_FEATURES,
    context_vector,
    grouped_contrastive,
    normalize_instrument,
    symmetric_contrastive,
    validate_config,
)
from training.ai_telescope import ExtendedEventLocalizer, ExtendedMultimodalPretrainer


class AITelescopeV2Tests(unittest.TestCase):
    def test_context_vector_preserves_missingness_for_later_encoding(self):
        value = context_vector({"TESSMAG": 11, "TEFF": 5700, "RADIUS": 1.2,
                                "RA_OBJ": 90, "DEC_OBJ": 0, "SECTOR": 10,
                                "CAMERA": 2, "CCD": 4, "CROWDSAP": .8,
                                "FLFRCSAP": .7})
        self.assertEqual(value.shape, (len(CONTEXT_FEATURES),))
        self.assertAlmostEqual(value[1], np.log(5700), places=5)
        self.assertAlmostEqual(value[7], 1, places=5)
        self.assertTrue(np.isnan(value[4]))

    def test_instrument_normalization_is_finite_and_robust(self):
        count = 300
        pixels = SimpleNamespace(
            time=np.arange(count, dtype=float), quality=np.zeros(count, dtype=int),
            position_correction=np.column_stack([np.linspace(-1, 1, count),
                                                  np.linspace(2, 5, count)]),
            background_flux=np.linspace(100, 120, count))
        pixels.position_correction[5, 0] = np.nan
        result = normalize_instrument(pixels)
        self.assertEqual(result.shape, (3, count))
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(result[0, 5], 0)

    def test_contrastive_losses_reward_correct_pairs_and_groups(self):
        embedding = torch.eye(4)
        wrong = embedding[[1, 0, 3, 2]]
        self.assertLess(symmetric_contrastive(embedding, embedding, .1),
                        symmetric_contrastive(embedding, wrong, .1))
        groups = torch.tensor([0, 0, 1, 1])
        same_group = embedding[[1, 0, 3, 2]]
        cross_group = embedding[[2, 3, 0, 1]]
        self.assertLess(grouped_contrastive(embedding, same_group, groups, .1),
                        grouped_contrastive(embedding, cross_group, groups, .1))

    def test_extended_models_obey_tensor_contracts(self):
        batch, length, context_dim = 3, 64, 32
        flux = torch.randn(batch, length)
        valid = torch.ones(batch, length)
        hidden = torch.zeros(batch, length)
        pixel = torch.randn(batch, 8, 11, 11)
        instrument = torch.randn(batch, 3, length)
        context = torch.randn(batch, context_dim)
        pretrainer = ExtendedMultimodalPretrainer(context_dim, 24, 3)
        outputs = pretrainer(flux, valid, hidden, pixel, instrument, context)
        self.assertEqual(outputs[0].shape, (batch, length))
        self.assertTrue(all(x.shape == (batch, 24) for x in outputs[1:]))
        localizer = ExtendedEventLocalizer(context_dim, 24, 3)
        self.assertEqual(localizer(flux, valid, pixel, instrument, context).shape,
                         (batch, length))
        self.assertEqual(localizer(flux, valid, pixel, instrument, context,
                                   use_instrument=False, use_context=False).shape,
                         (batch, length))

    def test_config_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            validate_config({"schema_version": 1, "surprise": True})


if __name__ == "__main__":
    unittest.main()
