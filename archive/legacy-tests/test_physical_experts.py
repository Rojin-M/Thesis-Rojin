"""Contracts for labelled physical experts and availability-aware fusion."""
from pathlib import Path
import json
import unittest

import numpy as np
import pandas as pd

from scripts.experiments.behavioral_supermodel_v4 import mean_stack, train_stack
from scripts.experiments.physical_experts import (FEATURES, _pixel_features, _tls_features,
                                                  fit_expert, validate_config)


class PhysicalFeatureTests(unittest.TestCase):
    def test_tls_and_pixel_features_are_finite(self):
        candidate = {"period_days": 4., "epoch_bjd_tdb": 2458500., "duration_hours": 3.}
        tls = {"period_days": 4.001, "epoch_btjd": 1500.01, "duration_hours": 3., "sde": 9.,
               "snr_white": 12., "odd_even_mismatch_sigma": None, "distinct_transit_count": 5,
               "diagnostics": {"sampling_gate_passed": True}}
        values = _tls_features(tls, candidate)
        self.assertTrue(values["tls_available"])
        self.assertTrue(all(np.isfinite(value) for key, value in values.items() if key != "tls_available"))
        pixel = {"aperture_photometry": {
                    "pipeline": {"depth_snr": 8., "depth_relative_flux": .01},
                    "core_3x3": {"depth_snr": 7., "depth_relative_flux": .009},
                    "expanded": {"depth_snr": 9., "depth_relative_flux": .011}},
                 "aperture_depth_coefficient_of_variation": .1,
                 "source_localization": {"offset_pixels": .2, "offset_sigma_approximate": None,
                    "peak_difference_snr": 6., "positive_flux_concentration": .5}}
        values = _pixel_features(pixel)
        self.assertTrue(values["pixel_available"])
        self.assertTrue(all(np.isfinite(value) for key, value in values.items() if key != "pixel_available"))

    def test_expert_fit_uses_declared_roles(self):
        rows = []
        roles = ["train", "selection", "calibration", "audit"]
        for index in range(80):
            label = index % 2
            row = {"candidate_id": str(index), "target_id": str(index), "role": roles[index // 20],
                   "label": label, "tls_available": True, "pixel_available": True}
            for names in FEATURES.values():
                for offset, name in enumerate(names): row[name] = label + .01 * offset
            rows.append(row)
        config = json.loads(Path("configs/physical_experts_v1.json").read_text())
        result = fit_expert("tls", pd.DataFrame(rows), config)
        self.assertEqual(result["audit_available"], 20)
        self.assertGreater(result["audit"]["average_precision"], .9)

    def test_config_rejects_unknown_fields(self):
        config = json.loads(Path("configs/physical_experts_v1.json").read_text())
        self.assertEqual(validate_config(config), config)
        config["surprise"] = True
        with self.assertRaises(ValueError): validate_config(config)


class AvailabilityFusionTests(unittest.TestCase):
    def test_unavailable_expert_is_masked(self):
        rng = np.random.default_rng(4)
        label = np.resize(np.array([0., 1.], np.float32), 40)
        base = np.column_stack([label * 3 - 1.5, rng.normal(size=40), np.full(40, 1000.)]).astype(np.float32)
        available = np.ones_like(base, dtype=bool); available[:, 2] = False
        config = {"learning_rate": .01, "stack_weight_decay": .01, "steps": 30, "max_grad_norm": 5.}
        model = train_stack(base, available, label, config, 1)
        result = mean_stack([model], base, available)
        self.assertTrue(np.isfinite(result).all())
        self.assertLess(np.max(result), 10)


if __name__ == "__main__":
    unittest.main()
