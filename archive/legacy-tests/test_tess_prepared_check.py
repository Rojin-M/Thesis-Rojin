"""Check artifact integrity and independently reconstructed source statistics."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.data.check_tess_prepared import _canonical_json, _digest, check_prepared
from scripts.data.tess_dataset import feature_names, fit_normalization, validate_dataset


class PreparedTessCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tess_prepared_check_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        rng = np.random.default_rng(9)
        self.arrays = {}
        for key, bins in (("X_global", 200), ("X_local", 100)):
            view = rng.normal(size=(6, bins, 3)).astype(np.float32)
            view[:, :, 1] = abs(view[:, :, 1])
            view[:, :, 2] = rng.integers(0, 2, size=(6, bins))
            self.arrays[key] = view
        self.arrays["X_scalar"] = rng.normal(size=(6, 7)).astype(np.float32)
        self.arrays["X"] = np.concatenate([self.arrays[key][:, :, channel]
                                          for key in ("X_global", "X_local") for channel in range(3)]
                                         + [self.arrays["X_scalar"]], axis=1)
        names, scalars = feature_names()
        self.arrays.update(y=np.array([0, 1, 0, 1, 0, 1]), feature_names=names,
                           scalar_feature_names=scalars, preprocessing_version=np.array("tess_v0"))
        manifest = pd.DataFrame({"candidate_id": [f"TOI-{i}.01" for i in range(6)],
                                 "tic_id": np.arange(100, 106), "y": self.arrays["y"],
                                 "split_group": list("abcdef")})
        self.splits = {"train_idx": np.array([2, 3]), "val_idx": np.array([0, 1]),
                       "test_idx": np.array([4, 5])}
        source = copy.deepcopy(self.arrays)
        for key in ("X", "X_scalar"):
            source[key] += 50
        for key in ("X_global", "X_local"):
            source[key][:, :, :2] += 50
        self.source_path = self.root / "dataset_kepler_v0_fixture.npz"
        source_split_path = self.root / "splits_kepler_v0_seed42.npz"
        np.savez_compressed(self.source_path, **source)
        np.savez_compressed(source_split_path, **self.splits)
        np.savez_compressed(self.prepared / "dataset_tess_v0.npz", **self.arrays)
        np.savez_compressed(self.prepared / "splits_tess_v0_seed42.npz", **self.splits)
        manifest.to_csv(self.prepared / "manifest_tess_v0.csv", index=False)
        pd.DataFrame(columns=["tic_id", "kepid"]).to_csv(self.prepared / "kepler_overlap.csv", index=False)
        np.savez_compressed(self.prepared / "kepler_train_normalization.npz",
                            **fit_normalization(source, self.splits["train_idx"]))
        np.savez_compressed(self.prepared / "tess_train_normalization.npz",
                            **fit_normalization(self.arrays, self.splits["train_idx"]))
        self.provenance = {"inputs": {str(path): _digest(path)
                                      for path in (self.source_path, source_split_path)},
                           "science": {"version": "tess_v0", "seed": 42,
                                       "pilot_candidates": 0, "train_only_groups": ["c"]}}
        self.provenance["signature"] = hashlib.sha256(_canonical_json(self.provenance)).hexdigest()
        (self.prepared / "provenance.json").write_bytes(_canonical_json(self.provenance))
        self.summary = {"status": "complete", "accepted_candidates": 6,
                        "pilot_groups_reserved_for_training": ["c"],
                        "validation": validate_dataset(self.arrays, manifest, self.splits, train_only_groups=["c"]),
                        "outputs": {p.name: _digest(p) for p in self.prepared.iterdir()
                                    if p.suffix in {".csv", ".npz"}}}
        self._save_summary()

    def _save_summary(self):
        (self.prepared / "preparation_summary.json").write_bytes(_canonical_json(self.summary))

    def test_verified_and_model_check_receives_only_training_rows(self):
        report = check_prepared(self.prepared)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["source_normalization"]["matches_kepler_training_rows"])
        self.assertFalse(report["model_interfaces"]["performed"])
        with patch("scripts.data.check_tess_prepared._check_model_interfaces", return_value={"performed": True}) as check:
            check_prepared(self.prepared, check_models=True)
        np.testing.assert_array_equal(check.call_args.args[2], self.splits["train_idx"])
        self.assertEqual(check.call_args.args[3], "train")

    def test_checksum_detects_modified_output_and_source(self):
        path = self.prepared / "dataset_tess_v0.npz"
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "output checksum mismatch"):
            check_prepared(self.prepared)
        path.write_bytes(original)
        with self.source_path.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "source checksum mismatch"):
            check_prepared(self.prepared)

    def test_rejects_target_fitted_statistics_even_with_updated_output_hash(self):
        path = self.prepared / "kepler_train_normalization.npz"
        np.savez_compressed(path, **fit_normalization(self.arrays, self.splits["train_idx"]))
        self.summary["outputs"][path.name] = _digest(path)
        self._save_summary()
        with self.assertRaisesRegex(ValueError, "differs from source training rows"):
            check_prepared(self.prepared)

    def test_requires_complete_signed_provenance(self):
        self.summary["status"] = "running"
        self._save_summary()
        with self.assertRaisesRegex(ValueError, "must be complete"):
            check_prepared(self.prepared)
        self.summary["status"] = "complete"
        self._save_summary()
        self.provenance["science"]["seed"] = 43
        (self.prepared / "provenance.json").write_text(json.dumps(self.provenance))
        with self.assertRaisesRegex(ValueError, "signature mismatch"):
            check_prepared(self.prepared)

    def test_requires_recorded_hashes_for_essential_artifacts(self):
        self.summary["outputs"] = {}
        self._save_summary()
        with self.assertRaisesRegex(ValueError, "absent from recorded checksums"):
            check_prepared(self.prepared)

    def test_unsplit_pilot_uses_only_its_first_four_rows(self):
        self.provenance.pop("signature")
        self.provenance["science"].update(pilot_candidates=6, train_only_groups=[])
        self.provenance["signature"] = hashlib.sha256(_canonical_json(self.provenance)).hexdigest()
        (self.prepared / "provenance.json").write_bytes(_canonical_json(self.provenance))
        for name in ("splits_tess_v0_seed42.npz", "tess_train_normalization.npz"):
            (self.prepared / name).unlink()
            self.summary["outputs"].pop(name)
        manifest = pd.read_csv(self.prepared / "manifest_tess_v0.csv")
        self.summary["validation"] = validate_dataset(self.arrays, manifest, None)
        self.summary["pilot_groups_reserved_for_training"] = []
        self._save_summary()
        with patch("scripts.data.check_tess_prepared._check_model_interfaces", return_value={"performed": True}) as check:
            report = check_prepared(self.prepared, check_models=True)
        self.assertEqual(report["mode"], "pilot")
        np.testing.assert_array_equal(check.call_args.args[2], np.arange(4))
        self.assertEqual(check.call_args.args[3], "pilot")


if __name__ == "__main__":
    unittest.main()
