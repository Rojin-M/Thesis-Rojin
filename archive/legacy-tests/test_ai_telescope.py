import unittest

import numpy as np
import torch

from scripts.experiments.ai_telescope import (
    center_crop_or_pad, event_metrics, validate_config, window_starts,
)
from training.ai_telescope import EventLocalizer, MultimodalPretrainer


class AITelescopeTests(unittest.TestCase):
    def config(self):
        return validate_config({
            "schema_version": 1, "cohort": "a", "physical_run": "b", "output": "c",
            "window_length": 64, "pixel_frames": 8, "spatial_size": 11,
            "random_windows_per_target": 2, "event_windows_per_candidate": 1,
            "embedding_dim": 16, "pretrain_epochs": 1, "localization_epochs": 1,
            "batch_size": 4, "learning_rate": .001, "weight_decay": .001,
            "mask_fraction": .2, "contrastive_temperature": .1, "contrastive_weight": .25,
            "maximum_positive_weight": 20., "calibration_fpr_target": .01,
            "seed": 1, "cpu_threads": 1})

    def test_model_contracts(self):
        batch, length, frames, size = 4, 64, 8, 11
        flux, valid = torch.randn(batch, length), torch.ones(batch, length)
        hidden, pixels = torch.zeros(batch, length), torch.randn(batch, frames, size, size)
        pretrainer = MultimodalPretrainer(16)
        reconstructed, light, image = pretrainer(flux, valid, hidden, pixels)
        self.assertEqual(reconstructed.shape, flux.shape)
        self.assertEqual(light.shape, (batch, 16)); self.assertEqual(image.shape, (batch, 16))
        localizer = EventLocalizer(16); localizer.load_pretrained(pretrainer)
        self.assertEqual(localizer(flux, valid, pixels).shape, flux.shape)

    def test_crop_and_pad_is_centered(self):
        small = np.ones((2, 5, 7), dtype=np.float32)
        padded = center_crop_or_pad(small, 11)
        self.assertEqual(padded.shape, (2, 11, 11)); self.assertEqual(padded.sum(), 70)
        large = np.arange(2 * 15 * 15).reshape(2, 15, 15)
        np.testing.assert_array_equal(center_crop_or_pad(large, 11), large[:, 2:13, 2:13])

    def test_windows_include_event_and_random_samples(self):
        config = self.config(); event = np.zeros(500, dtype=bool); event[240:245] = True
        starts = window_starts(500, event, [{}], np.arange(500), config, "123")
        self.assertTrue(any(start <= 242 < start + 64 for start in starts))
        self.assertGreaterEqual(len(starts), 2)

    def test_event_metrics_ignore_invalid_cadences(self):
        labels = np.array([[0, 1, 1, 0]], dtype=np.uint8)
        logits = np.array([[-4, 4, -4, 4]], dtype=np.float32)
        valid = np.array([[1, 1, 0, 1]], dtype=np.uint8)
        result = event_metrics(labels, logits, valid, .5)
        self.assertEqual(result["positive_cadences"], 1)
        self.assertEqual(result["threshold"]["recall"], 1.)

    def test_invalid_config_fails_closed(self):
        config = self.config(); config["window_length"] = 65
        with self.assertRaises(ValueError): validate_config(config)


if __name__ == "__main__":
    unittest.main()
