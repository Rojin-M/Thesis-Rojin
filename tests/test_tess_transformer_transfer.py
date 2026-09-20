"""Protect frozen normalization, row identity, and saved transfer evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import torch

from scripts.data.tess_dataset import fit_normalization
from scripts.experiments import evaluate_kepler_transformer_on_tess as transfer


class ScalarModel(torch.nn.Module):
    def forward(self, global_view, local_view, scalar, flat):
        return scalar[:, 0]


class FrozenTransferTests(unittest.TestCase):
    def test_source_moments_and_requested_order_ignore_other_target_rows(self):
        rng = np.random.default_rng(12)
        source = {"X_global": rng.normal(size=(6, 200, 3)).astype(np.float32),
                  "X_local": rng.normal(size=(6, 100, 3)).astype(np.float32),
                  "X_scalar": rng.normal(size=(6, 7)).astype(np.float32),
                  "X": rng.normal(size=(6, 907)).astype(np.float32)}
        stats = fit_normalization(source, np.array([0, 2, 3]))
        target = {key: value.copy() for key, value in source.items()}
        indices = np.array([4, 1])
        normalized = transfer.source_inputs({key: value[indices] for key, value in target.items()}, stats)
        expected = torch.sigmoid(torch.from_numpy(normalized["x_scalar"][:, 0])).numpy()
        actual = transfer.predict(ScalarModel(), target, indices, stats, 1, torch.device("cpu"))
        np.testing.assert_allclose(actual, expected)
        for key in target:
            np.testing.assert_array_equal(target[key], source[key])
            target[key][[0, 2, 3, 5]] += 10000
        repeated = transfer.predict(ScalarModel(), target, indices, stats, 2, torch.device("cpu"))
        np.testing.assert_array_equal(actual, repeated)

    def fixture(self, root):
        prepared, output = root / "prepared", root / "evaluation"
        prepared.mkdir(); output.mkdir()
        manifest = pd.DataFrame({"candidate_id": ["TOI-1.01", "TOI-2.01", "TOI-3.01", "TOI-4.01"],
                                 "tic_id": [1, 2, 3, 4], "y": [0, 1, 1, 0]})
        manifest.to_csv(prepared / "manifest_tess_v0.csv", index=False)
        indices = np.array([3, 1])
        np.savez(prepared / "splits_tess_v0_seed42.npz", test_idx=indices)
        protocol = {"prepared": {"directory": str(prepared)}, "input_sha256": {
            str(path): transfer._sha(path) for path in prepared.iterdir()}}
        protocol["signature"] = hashlib.sha256(transfer._json_bytes(protocol)).hexdigest()
        transfer._write_json(output / "protocol.json", protocol)
        frame = manifest.iloc[indices].copy()
        frame["probability"] = np.array([.6, .9], dtype=np.float32)
        frame["prediction"] = [0, 1]
        frame.to_csv(output / "kepler_transformer_predictions.csv", index=False)
        record = {"threshold": .7, "metrics": transfer._checked_predictions(frame, manifest, indices, .7)}
        completion = {"status": "complete", "protocol_signature": protocol["signature"],
                      "arms": {transfer.ARM: record}, "artifacts": {
                          path.name: transfer._sha(path) for path in output.iterdir()}}
        transfer._write_json(output / "completion.json", completion)
        return prepared, output

    def test_verification_reconstructs_metrics_and_detects_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared, output = self.fixture(Path(directory))
            report = transfer.verify(output)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["metrics"]["accuracy"], 1.)
            with (prepared / "manifest_tess_v0.csv").open("a") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "input changed"):
                transfer.verify(output)

    def test_reordered_predictions_fail_even_with_updated_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output = self.fixture(Path(directory))
            path = output / "kepler_transformer_predictions.csv"
            pd.read_csv(path).iloc[::-1].to_csv(path, index=False)
            completion = json.loads((output / "completion.json").read_text())
            completion["artifacts"][path.name] = transfer._sha(path)
            transfer._write_json(output / "completion.json", completion)
            with self.assertRaisesRegex(ValueError, "order differs"):
                transfer.verify(output)


if __name__ == "__main__":
    unittest.main()
