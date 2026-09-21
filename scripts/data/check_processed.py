#!/usr/bin/env python3
"""Check the published processed artifacts without downloading or preparing data."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def main():
    checksums = json.loads((ROOT / "configs/data_checksums.json").read_text())
    for relative, expected in checksums.items():
        path = ROOT / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Processed artifact differs from the published reference: {relative}")
    data = ROOT / "data/processed/kepler"
    manifest = pd.read_csv(data / "v0/manifest_kepler_v0.csv")
    with np.load(data / "v0/splits_kepler_v0_seed42.npz") as saved:
        indices = [saved[s + "_idx"] for s in ("train", "val", "test")]
        np.testing.assert_array_equal(np.sort(np.concatenate(indices)), np.arange(len(manifest)))
        stars = [set(manifest.iloc[idx].kepid) for idx in indices]
        assert all(not stars[i] & stars[j] for i in range(3) for j in range(i))
    with np.load(next((data / "v0").glob("dataset_*.npz")), allow_pickle=True) as dataset:
        np.testing.assert_array_equal(dataset["y"], manifest.y.to_numpy())
        for key in ("X", "X_global", "X_local", "X_scalar"):
            if not np.isfinite(dataset[key]).all():
                raise ValueError(f"Processed artifact contains non-finite values: {key}")
    print(f"Verified {len(checksums)} unchanged artifacts; {len(manifest)} candidates; split sizes {[len(i) for i in indices]}; disjoint star groups; finite model inputs.")


if __name__ == "__main__":
    main()
