"""Check two-arm transfer protocol with synthetic data and mocked model work."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import torch

from scripts.data.tess_dataset import feature_names, fit_normalization
from scripts.experiments import run_tess_baseline as baseline


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


class TessBaselineProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tess_baseline_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prepared = self.root / "prepared"
        self.source_run = self.root / "source_run"
        self.output = self.root / "comparison"
        self.prepared.mkdir()
        rng = np.random.default_rng(82)
        self.arrays = {}
        for key, bins in (("X_global", 200), ("X_local", 100)):
            view = rng.normal(size=(6, bins, 3)).astype(np.float32)
            view[:, :, 1] = abs(view[:, :, 1])
            view[:, :, 2] = rng.integers(0, 2, size=(6, bins))
            self.arrays[key] = view
        self.arrays["X_scalar"] = rng.normal(size=(6, 7)).astype(np.float32)
        self.arrays["X"] = np.concatenate(
            [self.arrays[key][:, :, channel] for key in ("X_global", "X_local") for channel in range(3)]
            + [self.arrays["X_scalar"]], axis=1)
        names, scalars = feature_names()
        self.arrays.update(y=np.array([0, 1, 0, 1, 0, 1]), feature_names=names,
                           scalar_feature_names=scalars, preprocessing_version=np.array("tess_v0"))
        self.splits = {"train_idx": np.array([0, 1]), "val_idx": np.array([2, 3]),
                       "test_idx": np.array([4, 5])}
        self.manifest = pd.DataFrame({"candidate_id": [f"TOI-{i}.01" for i in range(6)],
                                      "tic_id": np.arange(100, 106), "y": self.arrays["y"],
                                      "split_group": [f"TIC-{i}" for i in range(100, 106)]})
        source_arrays = deepcopy(self.arrays)
        for key in ("X", "X_scalar"):
            source_arrays[key] += 20
        for key in ("X_global", "X_local"):
            source_arrays[key][:, :, :2] += 20
        source_arrays["preprocessing_version"] = np.array("v0")
        source_manifest = self.manifest.rename(columns={"tic_id": "kepid"}).copy()
        source_manifest["candidate_id"] = [f"K{i:05d}.01" for i in range(6)]
        source_dataset = self.root / "dataset_kepler_v0_fixture.npz"
        source_splits = self.root / "splits_kepler_v0_seed42.npz"
        source_manifest_path = self.root / "manifest_kepler_v0.csv"
        np.savez_compressed(source_dataset, **source_arrays)
        np.savez_compressed(source_splits, **self.splits)
        source_manifest.to_csv(source_manifest_path, index=False)
        self.source_stats = fit_normalization(source_arrays, self.splits["train_idx"])
        self.target_stats = fit_normalization(self.arrays, self.splits["train_idx"])
        np.savez_compressed(self.prepared / "dataset_tess_v0.npz", **self.arrays)
        np.savez_compressed(self.prepared / "splits_tess_v0_seed42.npz", **self.splits)
        self.manifest.to_csv(self.prepared / "manifest_tess_v0.csv", index=False)
        np.savez_compressed(self.prepared / "kepler_train_normalization.npz", **self.source_stats)
        np.savez_compressed(self.prepared / "tess_train_normalization.npz", **self.target_stats)
        self.provenance = {"inputs": {str(path): checksum(path)
                                      for path in (source_dataset, source_splits, source_manifest_path)},
                           "science": {"seed": 42, "version": "tess_v0"}}
        write_json(self.prepared / "provenance.json", self.provenance)
        write_json(self.prepared / "preparation_summary.json",
                   {"status": "complete", "outputs": {path.name: checksum(path)
                    for path in self.prepared.iterdir() if path.suffix in {".npz", ".csv"}}})
        self.source_cfg = baseline.trainer.TrainConfig(
            base_dir=str(self.root), dataset_path=str(source_dataset), splits_path=str(source_splits),
            manifest_path=str(source_manifest_path), output_root=str(self.root / "source"),
            device="cpu", epochs=1, batch_size=2, num_workers=0, prepare_version="v0",
            threshold_grid_size=19)
        self.model_config = {"scalar_features": 7, "flat_features": 907, "dropout": .2,
                             "scalar_dropout": .1, "wide_dropout": .15, "use_wide_branch": False,
                             "use_aux_branch": False, "aux_features": 0, "aux_dropout": .1}
        self.source_checkpoint = self.training_record(
            self.source_run, self.source_cfg, source_manifest, [.65, .9])

    def training_record(self, directory, cfg, manifest, validation_probabilities, test_probabilities=None):
        """Write the real trainer artifact contract, without training a model."""
        directory.mkdir(parents=True, exist_ok=True)
        validation = manifest.iloc[self.splits["val_idx"]].copy()
        probabilities = np.asarray(validation_probabilities, dtype=np.float32)
        threshold = baseline.trainer.build_threshold(validation.y.to_numpy(), probabilities, cfg.threshold_grid_size)
        validation["probability"] = probabilities
        validation["prediction"] = (probabilities >= threshold).astype(np.int64)
        metrics = baseline.trainer.compute_metrics(validation.y.to_numpy(), probabilities, threshold)
        checkpoint = {"config": asdict(cfg), "model_config": self.model_config, "model_state": {},
                      "aux_preprocessing": None, "epoch": 1, "val_threshold": threshold,
                      "val_pr_auc": metrics["pr_auc"]}
        summary = {"best_epoch": 1, "best_threshold": threshold, "val_metrics": metrics}
        if test_probabilities is not None:
            test = manifest.iloc[self.splits["test_idx"]].copy()
            test["probability"] = np.asarray(test_probabilities, dtype=np.float32)
            test["prediction"] = (test.probability.to_numpy() >= threshold).astype(np.int64)
            summary["test_metrics"] = baseline.trainer.compute_metrics(test.y.to_numpy(),
                                                                       test.probability.to_numpy(), threshold)
            test.to_csv(directory / "test_predictions.csv", index=False)
        validation.to_csv(directory / "val_predictions.csv", index=False)
        pd.DataFrame([{"epoch": 1, "val_pr_auc": metrics["pr_auc"], "val_threshold": threshold}]).to_csv(
            directory / "history.csv", index=False)
        write_json(directory / "config.json", asdict(cfg))
        write_json(directory / "model_config.json", self.model_config)
        write_json(directory / "summary.json", summary)
        torch.save(checkpoint, directory / "best_model.pt")
        return checkpoint

    def train_target(self, cfg):
        directory = Path(cfg.output_root) / "fixture_completed_run"
        self.training_record(directory, cfg, self.manifest, [.2, .8], [.35, .75])
        return directory

    def frozen_predictions(self, source_run, checkpoint, arrays, manifest, splits, stats, device):
        for key, expected in self.source_stats.items():
            np.testing.assert_array_equal(stats[key], expected)
        self.assertEqual(checkpoint["val_threshold"], self.source_checkpoint["val_threshold"])
        frame = manifest.iloc[splits["test_idx"]].copy()
        frame["probability"] = np.array([.55, .65], dtype=np.float32)
        frame["prediction"] = (frame.probability.to_numpy() >= checkpoint["val_threshold"]).astype(np.int64)
        return frame, baseline.trainer.compute_metrics(frame.y.to_numpy(), frame.probability.to_numpy(),
                                                       checkpoint["val_threshold"])

    def run_comparison(self):
        return baseline.run_comparison(self.root, self.prepared, self.output, self.source_run, device="cpu")

    def test_source_inputs_use_saved_source_moments_without_target_refitting(self):
        original = deepcopy(self.arrays)
        with patch.object(baseline, "fit_normalization", side_effect=AssertionError("Target refit forbidden")):
            normalized = baseline.source_inputs(self.arrays, self.source_stats)
        expected_scalar = (self.arrays["X_scalar"] - self.source_stats["scalar_mean"]) / self.source_stats["scalar_std"]
        np.testing.assert_array_equal(normalized["x_scalar"], expected_scalar)
        target_refitted = (self.arrays["X_scalar"] - self.target_stats["scalar_mean"]) / self.target_stats["scalar_std"]
        self.assertFalse(np.allclose(normalized["x_scalar"], target_refitted))
        for key, output, prefix in (("X_global", "x_global", "g"), ("X_local", "x_local", "l")):
            np.testing.assert_array_equal(normalized[output][:, :, 2], self.arrays[key][:, :, 2])
            np.testing.assert_array_equal(normalized[output][:, :, :2],
                (self.arrays[key][:, :, :2] - self.source_stats[prefix + "_mean"]) / self.source_stats[prefix + "_std"])
        for key in self.arrays:
            np.testing.assert_array_equal(self.arrays[key], original[key])

    def test_frozen_evaluation_uses_only_test_rows_and_unchanged_kepler_threshold(self):
        model = Mock()
        model.to.return_value = model
        model.return_value = torch.logit(torch.tensor([.55, .65], dtype=torch.float32))
        with patch.object(baseline.trainer, "ExoMinerStyleCNN", return_value=model), \
                patch.object(baseline, "fit_normalization", side_effect=AssertionError("No target fit")), \
                patch.object(baseline.trainer, "build_threshold", side_effect=AssertionError("No target threshold tuning")):
            predictions, metrics = baseline.evaluate_frozen_source(
                self.source_run, self.source_checkpoint, self.arrays, self.manifest,
                self.splits, self.source_stats, "cpu")
        self.assertEqual(predictions.candidate_id.tolist(), self.manifest.iloc[self.splits["test_idx"]].candidate_id.tolist())
        self.assertEqual(predictions.prediction.tolist(), [0, 0])
        self.assertEqual(metrics["f1"], 0.)
        expected_scalar = (self.arrays["X_scalar"][self.splits["test_idx"]]
                           - self.source_stats["scalar_mean"]) / self.source_stats["scalar_std"]
        np.testing.assert_array_equal(model.call_args.args[2].numpy(), expected_scalar)
        model.load_state_dict.assert_called_once_with(self.source_checkpoint["model_state"], strict=True)
        model.eval.assert_called_once()

    def test_interruption_reuses_completed_target_and_completion_reuses_both_arms(self):
        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "full"}), \
                patch.object(baseline.trainer, "train_model", side_effect=self.train_target) as train, \
                patch.object(baseline, "evaluate_frozen_source", side_effect=RuntimeError("temporary evaluator failure")) as evaluate:
            with self.assertRaisesRegex(RuntimeError, "temporary evaluator failure"):
                self.run_comparison()
            self.assertEqual(train.call_count, 1)
            self.assertTrue((self.output / "target_run.json").is_file())
            self.assertFalse((self.output / "completion.json").exists())
            evaluate.side_effect = self.frozen_predictions
            completed = self.run_comparison()
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(train.call_count, 1)
            self.assertEqual(evaluate.call_count, 2)
            repeated = self.run_comparison()
            self.assertEqual(repeated, completed)
            self.assertEqual(train.call_count, 1)
            self.assertEqual(evaluate.call_count, 2)
        source = completed["arms"]["kepler_frozen"]
        target = completed["arms"]["tess_trained"]
        self.assertEqual(source["threshold"], self.source_checkpoint["val_threshold"])
        self.assertEqual(source["threshold_fit_split"], "Kepler validation")
        self.assertEqual(target["threshold_fit_split"], "TESS validation")
        self.assertNotEqual(source["threshold"], target["threshold"])
        self.assertEqual(source["test_size"], target["test_size"])
        trained = train.call_args.args[0]
        self.assertEqual(trained.learning_rate, self.source_cfg.learning_rate)
        self.assertEqual(trained.dropout, self.source_cfg.dropout)
        self.assertFalse(trained.use_aux_branch)
        self.assertFalse(trained.use_wide_branch)
        target_rows = pd.read_csv(self.output / "tess_trained_predictions.csv")
        source_rows = pd.read_csv(self.output / "kepler_frozen_predictions.csv")
        pd.testing.assert_frame_equal(target_rows[["candidate_id", "tic_id", "y"]],
                                      source_rows[["candidate_id", "tic_id", "y"]])

    def test_source_input_bytes_must_match_the_frozen_preparation_before_training(self):
        path = Path(self.source_cfg.manifest_path)
        path.write_bytes(path.read_bytes() + b"changed source metadata")
        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "full"}), \
                patch.object(baseline.trainer, "train_model") as train, \
                patch.object(baseline, "evaluate_frozen_source") as evaluate:
            with self.assertRaisesRegex(ValueError, "Source training input differs.*provenance"):
                self.run_comparison()
            train.assert_not_called()
            evaluate.assert_not_called()

    def test_protocol_changes_reject_resume_before_either_arm_runs_again(self):
        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "full"}), \
                patch.object(baseline.trainer, "train_model", side_effect=self.train_target) as train, \
                patch.object(baseline, "evaluate_frozen_source", side_effect=self.frozen_predictions) as evaluate:
            self.run_comparison()
            self.provenance["additional_frozen_input"] = "a changed prepared-data contract"
            write_json(self.prepared / "provenance.json", self.provenance)
            with self.assertRaisesRegex(ValueError, "protocol differs"):
                self.run_comparison()
            self.assertEqual(train.call_count, 1)
            self.assertEqual(evaluate.call_count, 1)

    def test_target_test_predictions_cannot_use_a_test_tuned_threshold(self):
        def bad_train(cfg):
            directory = self.train_target(cfg)
            predictions = pd.read_csv(directory / "test_predictions.csv")
            # Test-optimal predictions differ from the fixed validation threshold.
            predictions["prediction"] = [0, 1]
            predictions.to_csv(directory / "test_predictions.csv", index=False)
            return directory

        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "full"}), \
                patch.object(baseline.trainer, "train_model", side_effect=bad_train), \
                patch.object(baseline, "evaluate_frozen_source") as evaluate:
            with self.assertRaisesRegex(ValueError, "frozen threshold"):
                self.run_comparison()
            evaluate.assert_not_called()
        self.assertFalse((self.output / "completion.json").exists())

    def test_source_threshold_must_be_derived_from_source_validation_predictions(self):
        threshold = .05
        checkpoint = deepcopy(self.source_checkpoint)
        checkpoint["val_threshold"] = threshold
        torch.save(checkpoint, self.source_run / "best_model.pt")
        summary_path = self.source_run / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["best_threshold"] = threshold
        write_json(summary_path, summary)
        history = pd.read_csv(self.source_run / "history.csv")
        history["val_threshold"] = threshold
        history.to_csv(self.source_run / "history.csv", index=False)
        validation = pd.read_csv(self.source_run / "val_predictions.csv")
        validation["prediction"] = 1
        validation.to_csv(self.source_run / "val_predictions.csv", index=False)
        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "full"}), \
                patch.object(baseline.trainer, "train_model") as train:
            with self.assertRaisesRegex(ValueError, "validation-only F1 selection"):
                self.run_comparison()
            train.assert_not_called()

    def test_pilot_preparation_cannot_be_used_as_the_comparison_test_set(self):
        with patch.object(baseline, "check_prepared", return_value={"status": "passed", "mode": "pilot"}), \
                patch.object(baseline.trainer, "train_model") as train:
            with self.assertRaisesRegex(ValueError, "verified full TESS preparation"):
                self.run_comparison()
            train.assert_not_called()


if __name__ == "__main__":
    unittest.main()
