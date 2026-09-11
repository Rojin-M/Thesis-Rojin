"""Exercise the legacy feature contract and independent-inference safeguards."""
import copy
import unittest

import numpy as np
import pandas as pd

from scripts.data.tess_dataset import (
    apply_normalization, feature_names, fit_normalization, validate_dataset,
)


class TessDatasetTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(124)
        global_view = rng.normal(size=(6, 200, 3)).astype(np.float32)
        local_view = rng.normal(size=(6, 100, 3)).astype(np.float32)
        for view in (global_view, local_view):
            view[:, :, 1] = np.abs(view[:, :, 1])
            view[:, :, 2] = rng.integers(0, 2, size=view.shape[:2])
        scalar = rng.normal(size=(6, 7)).astype(np.float32)
        flat = np.concatenate([view[:, :, channel] for view in (global_view, local_view)
                               for channel in range(3)] + [scalar], axis=1)
        flat_names, scalar_names = feature_names()
        self.arrays = {"X_global": global_view, "X_local": local_view, "X_scalar": scalar,
                       "X": flat, "y": np.array([0, 1, 0, 1, 0, 1]),
                       "feature_names": flat_names, "scalar_feature_names": scalar_names}
        self.manifest = pd.DataFrame({"candidate_id": [f"TOI-{i}.01" for i in range(6)],
                                      "tic_id": np.arange(100, 106), "y": self.arrays["y"],
                                      "split_group": ["a", "b", "c", "d", "e", "f"]})
        self.splits = {"train_idx": np.array([0, 1]), "val_idx": np.array([2, 3]),
                       "test_idx": np.array([4, 5])}

    def test_schema_order_and_valid_dataset(self):
        names, scalar = feature_names()
        self.assertEqual(names.dtype.kind, "U")
        self.assertEqual(scalar.dtype.kind, "U")
        self.assertEqual(len(names), 907)
        self.assertEqual(names[[0, 199, 200, 400, 600, 700, 800, 900, 906]].tolist(),
                         ["g_mean_0", "g_mean_199", "g_std_0", "g_mask_0", "l_mean_0",
                          "l_std_0", "l_mask_0", "feat_depth", "bls_period"])
        result = validate_dataset(self.arrays, self.manifest, self.splits, train_only_groups=["a"])
        self.assertEqual(result["n_candidates"], 6)
        self.assertEqual(result["splits"]["test"]["class_counts"], {"0": 1, "1": 1})
        self.assertEqual(validate_dataset(self.arrays, self.manifest, None)["splits"], {})

    def test_reject_wrong_feature_or_flat_order(self):
        for key in ("feature_names", "scalar_feature_names"):
            wrong = copy.deepcopy(self.arrays)
            wrong[key][[0, 1]] = wrong[key][[1, 0]]
            with self.assertRaisesRegex(ValueError, "column order"):
                validate_dataset(wrong, self.manifest, self.splits)
        wrong = copy.deepcopy(self.arrays)
        wrong["X"][:, :600] = wrong["X_global"].reshape(6, -1)
        with self.assertRaisesRegex(ValueError, "channel-major"):
            validate_dataset(wrong, self.manifest, self.splits)

    def test_reject_row_star_group_overlap_and_inspected_groups(self):
        wrong = copy.deepcopy(self.splits)
        wrong["test_idx"][0] = 0
        with self.assertRaisesRegex(ValueError, "exactly once"):
            validate_dataset(self.arrays, self.manifest, wrong)
        wrong_manifest = self.manifest.copy()
        wrong_manifest.loc[2, ["tic_id", "split_group"]] = [100, "a"]
        with self.assertRaisesRegex(ValueError, "overlapping TIC"):
            validate_dataset(self.arrays, wrong_manifest, self.splits)
        wrong_manifest = self.manifest.copy()
        wrong_manifest.loc[2, "split_group"] = "a"
        with self.assertRaisesRegex(ValueError, "overlapping split groups"):
            validate_dataset(self.arrays, wrong_manifest, self.splits)
        with self.assertRaisesRegex(ValueError, "pilot groups"):
            validate_dataset(self.arrays, self.manifest, self.splits, train_only_groups=["c"])
        with self.assertRaisesRegex(ValueError, "forbidden TIC"):
            validate_dataset(self.arrays, self.manifest, self.splits, forbidden_tic_ids=[100])

    def test_reject_bad_labels_ids_masks_and_single_class_splits(self):
        manifest = self.manifest.copy()
        manifest.loc[1, "candidate_id"] = manifest.loc[0, "candidate_id"]
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_dataset(self.arrays, manifest, self.splits)
        wrong = copy.deepcopy(self.arrays)
        wrong["y"][0] = 2
        with self.assertRaisesRegex(ValueError, "binary"):
            validate_dataset(wrong, self.manifest, self.splits)
        wrong = copy.deepcopy(self.arrays)
        wrong["X_global"][0, 0, 2] = 0.5
        with self.assertRaisesRegex(ValueError, "masks"):
            validate_dataset(wrong, self.manifest, self.splits)
        single_class = {"train_idx": np.array([0, 2]), "val_idx": np.array([1, 3]),
                        "test_idx": np.array([4, 5])}
        with self.assertRaisesRegex(ValueError, "both classes"):
            validate_dataset(self.arrays, self.manifest, single_class)

    def test_moments_match_legacy_float32_and_do_not_fit_target_rows(self):
        # Constant source features exercise the original 1e-6 scale floor.
        self.arrays["X_scalar"][:2, 0] = 7
        self.arrays["X"][:2, 0] = 5
        stats = fit_normalization(self.arrays, self.splits["train_idx"])
        target = copy.deepcopy(self.arrays)
        for key in ("X", "X_scalar", "X_global", "X_local"):
            if target[key].ndim == 3:
                target[key][2:, :, :2] += 100
            else:
                target[key][2:] += 100
        repeated = fit_normalization(target, self.splits["train_idx"])
        for key in stats:
            self.assertEqual(stats[key].dtype, np.float32)
            np.testing.assert_array_equal(stats[key], repeated[key])
        np.testing.assert_array_equal(stats["scalar_std"][0, 0], np.float32(1e-6))
        before = {key: value.copy() for key, value in target.items()}
        normalized = apply_normalization(target, stats)
        for prefix, raw_key, output_key in (("g", "X_global", "x_global"),
                                             ("l", "X_local", "x_local"),
                                             ("scalar", "X_scalar", "x_scalar"),
                                             ("flat", "X", "x_flat")):
            training = self.arrays[raw_key][:2]
            expected = target[raw_key].copy()
            if training.ndim == 3:
                mean = training[:, :, :2].mean(axis=(0, 1), keepdims=True)
                std = np.clip(training[:, :, :2].std(axis=(0, 1), keepdims=True), 1e-6, None)
                expected[:, :, :2] = (expected[:, :, :2] - mean) / std
                np.testing.assert_array_equal(normalized[output_key][:, :, 2], target[raw_key][:, :, 2])
            else:
                mean = training.mean(axis=0, keepdims=True)
                std = np.clip(training.std(axis=0, keepdims=True), 1e-6, None)
                expected = (expected - mean) / std
            np.testing.assert_array_equal(normalized[output_key], expected)
            np.testing.assert_array_equal(stats[prefix + "_mean"], mean)
            np.testing.assert_array_equal(stats[prefix + "_std"], std)
        for key in target:
            np.testing.assert_array_equal(target[key], before[key])
        # A new mission can have a completely different row count.
        one_target = {key: value[-1:] for key, value in target.items()
                      if key in ("X_global", "X_local", "X_scalar", "X")}
        actual = apply_normalization(one_target, stats)
        np.testing.assert_array_equal(actual["x_scalar"], normalized["x_scalar"][-1:])
        self.assertGreater(float(actual["x_scalar"][0, 1]), 10)

    def test_reject_bad_normalization_indices_or_stats(self):
        with self.assertRaisesRegex(ValueError, "training indices"):
            fit_normalization(self.arrays, np.array([0.0, 1.0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            fit_normalization(self.arrays, np.array([0, 0]))
        stats = fit_normalization(self.arrays, self.splits["train_idx"])
        stats["g_std"][:] = 0
        with self.assertRaisesRegex(ValueError, "floor"):
            apply_normalization(self.arrays, stats)


if __name__ == "__main__":
    unittest.main()
