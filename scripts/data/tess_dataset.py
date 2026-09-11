"""Validate TESS model inputs and apply explicit source-training normalization.

The raw feature schema preserves Kepler's legacy definitions. In particular,
``feat_odd_even`` compares alternating phase bins and ``bls_snr`` contains the
BLS likelihood power. These names are retained for checkpoint compatibility.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


def feature_names(global_bins: int = 200, local_bins: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Return Unicode names in the exact Kepler channel-major flat order."""
    if any(not isinstance(n, (int, np.integer)) or n < 1 for n in (global_bins, local_bins)):
        raise ValueError("Bin counts must be positive integers")
    scalar = ["feat_depth", "feat_symmetry", "feat_odd_even",
              "bls_snr", "bls_depth", "bls_duration", "bls_period"]
    flat = [f"{view}_{channel}_{i}"
            for view, bins in (("g", global_bins), ("l", local_bins))
            for channel in ("mean", "std", "mask") for i in range(bins)] + scalar
    return np.asarray(flat, dtype=str), np.asarray(scalar, dtype=str)


def _normalization_inputs(arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    values = {}
    for key in ("X_global", "X_local", "X_scalar", "X"):
        if key not in arrays:
            raise ValueError(f"Missing normalization input {key}")
        values[key] = np.asarray(arrays[key], dtype=np.float32)
        expected_ndim = 3 if key in ("X_global", "X_local") else 2
        if (values[key].ndim != expected_ndim or not np.isfinite(values[key]).all()
                or any(size == 0 for size in values[key].shape)):
            raise ValueError(f"Invalid shape or nonfinite normalization input {key}")
        if expected_ndim == 3 and values[key].shape[-1] != 3:
            raise ValueError(f"{key} requires mean, std, and mask channels")
    if len({len(value) for value in values.values()}) != 1:
        raise ValueError("Normalization input row counts differ")
    return values


def _indices(value: np.ndarray, n: int, label: str) -> np.ndarray:
    result = np.asarray(value)
    if (result.ndim != 1 or not np.issubdtype(result.dtype, np.integer)
            or len(result) == 0 or (result < 0).any() or (result >= n).any()):
        raise ValueError(f"Invalid {label} indices")
    if len(np.unique(result)) != len(result):
        raise ValueError(f"Duplicate {label} indices")
    return result


def fit_normalization(arrays: Mapping[str, np.ndarray], train_idx: np.ndarray) -> dict[str, np.ndarray]:
    """Fit only the given training rows, matching the original float32 loader.

    For independent TESS inference, pass the Kepler source arrays and their
    original training indices here; never fit these statistics on TESS rows.
    """
    values = _normalization_inputs(arrays)
    indices = _indices(train_idx, len(values["X"]), "training")
    stats = {}
    for prefix, key in (("g", "X_global"), ("l", "X_local"),
                        ("scalar", "X_scalar"), ("flat", "X")):
        train = values[key][indices]
        axes = 0
        if prefix in ("g", "l"):
            train = train[:, :, :2]
            axes = (0, 1)
        stats[prefix + "_mean"] = train.mean(axis=axes, keepdims=True)
        stats[prefix + "_std"] = np.clip(train.std(axis=axes, keepdims=True), 1e-6, None)
    if any(not np.isfinite(value).all() for value in stats.values()):
        raise ValueError("Nonfinite fitted normalization statistics")
    return stats


def apply_normalization(arrays: Mapping[str, np.ndarray],
                        stats: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Apply supplied moments without refitting; leave view masks unchanged."""
    values = _normalization_inputs(arrays)
    result = {}
    for prefix, key, output in (("g", "X_global", "x_global"),
                                ("l", "X_local", "x_local"),
                                ("scalar", "X_scalar", "x_scalar"),
                                ("flat", "X", "x_flat")):
        expected_shape = (1, 1, 2) if prefix in ("g", "l") else (1, values[key].shape[1])
        moments = {}
        for name in ("mean", "std"):
            stat_key = prefix + "_" + name
            if stat_key not in stats:
                raise ValueError(f"Missing normalization statistic {stat_key}")
            value = np.asarray(stats[stat_key], dtype=np.float32)
            if value.shape != expected_shape or not np.isfinite(value).all():
                raise ValueError(f"Invalid normalization statistic {stat_key}")
            if name == "std" and (value < np.float32(1e-6)).any():
                raise ValueError(f"Normalization scale {stat_key} is below the Kepler floor")
            moments[name] = value
        if prefix in ("g", "l"):
            normalized = values[key].copy()
            normalized[:, :, :2] = (normalized[:, :, :2] - moments["mean"]) / moments["std"]
        else:
            normalized = (values[key] - moments["mean"]) / moments["std"]
        if not np.isfinite(normalized).all():
            raise ValueError(f"Nonfinite normalized input {output}")
        result[output] = normalized.astype(np.float32, copy=False)
    return result


def validate_dataset(arrays: Mapping[str, np.ndarray], manifest: pd.DataFrame,
                     splits: Mapping[str, np.ndarray] | None, *,
                     forbidden_tic_ids: Iterable[int] = (),
                     train_only_groups: Iterable[Any] = ()) -> dict[str, Any]:
    """Check the canonical raw schema and candidate/star/group split integrity.

    ``splits=None`` permits an unsplit pilot. Training-only restrictions require
    actual split assignments and therefore cannot be checked in that mode.
    """
    required_columns = {"candidate_id", "tic_id", "y", "split_group"}
    if required_columns - set(manifest.columns):
        raise ValueError(f"Missing manifest columns: {sorted(required_columns - set(manifest.columns))}")
    n = len(manifest)
    candidate_ids = manifest.candidate_id.astype(str)
    if (n == 0 or manifest.candidate_id.isna().any() or not candidate_ids.is_unique
            or candidate_ids.str.strip().eq("").any()):
        raise ValueError("Manifest requires unique, nonempty candidate IDs")
    tic_numeric = pd.to_numeric(manifest.tic_id, errors="coerce").to_numpy()
    if (not np.isfinite(tic_numeric).all() or (tic_numeric <= 0).any()
            or (tic_numeric != np.floor(tic_numeric)).any()):
        raise ValueError("Manifest requires positive integer TIC IDs")
    tic_ids = tic_numeric.astype(np.int64)
    group_ids = manifest.split_group.astype(str).to_numpy()
    if manifest.split_group.isna().any() or manifest.split_group.astype(str).str.strip().eq("").any():
        raise ValueError("Manifest requires nonempty split groups")

    shapes = {"X_global": (n, 200, 3), "X_local": (n, 100, 3),
              "X_scalar": (n, 7), "X": (n, 907), "y": (n,)}
    values = {}
    for key, shape in shapes.items():
        if key not in arrays:
            raise ValueError(f"Missing dataset array {key}")
        values[key] = np.asarray(arrays[key])
        if values[key].shape != shape or not np.issubdtype(values[key].dtype, np.number):
            raise ValueError(f"Invalid {key} shape or numeric dtype; expected {shape}")
        if not np.isfinite(values[key]).all():
            raise ValueError(f"Nonfinite values in {key}")
    labels = values["y"]
    if not np.isin(labels, [0, 1]).all() or not np.isin(manifest.y.to_numpy(), [0, 1]).all():
        raise ValueError("Dataset and manifest labels must be binary")
    if not np.array_equal(labels, manifest.y.to_numpy()):
        raise ValueError("Dataset labels differ from manifest row order")
    flat_names, scalar_names = feature_names()
    for key, expected in (("feature_names", flat_names), ("scalar_feature_names", scalar_names)):
        if key not in arrays or not np.array_equal(np.asarray(arrays[key]), expected):
            raise ValueError(f"Incorrect {key} column order")
    for key in ("X_global", "X_local"):
        if not np.isin(values[key][:, :, 2], [0, 1]).all():
            raise ValueError(f"{key} coverage masks must be binary")
        if (values[key][:, :, 1] < 0).any():
            raise ValueError(f"{key} standard deviations must be nonnegative")
    flattened = np.concatenate([values[key][:, :, channel]
                                for key in ("X_global", "X_local") for channel in range(3)]
                               + [values["X_scalar"]], axis=1)
    if not np.array_equal(values["X"], flattened):
        raise ValueError("X differs from the exact channel-major flat concatenation")
    forbidden = {int(value) for value in forbidden_tic_ids}
    if forbidden.intersection(tic_ids.tolist()):
        raise ValueError("Dataset contains forbidden TIC stars")
    # A star cannot have conflicting group assignments even within one split.
    identity = pd.DataFrame({"tic_id": tic_ids, "group": group_ids})
    if (identity.groupby("tic_id")["group"].nunique() > 1).any():
        raise ValueError("One TIC star has multiple split groups")

    def counts(indices: np.ndarray) -> dict[str, Any]:
        return {"n_candidates": int(len(indices)),
                "n_stars": int(len(np.unique(tic_ids[indices]))),
                "n_groups": int(len(np.unique(group_ids[indices]))),
                "class_counts": {str(label): int(np.sum(labels[indices] == label)) for label in (0, 1)}}

    summary = {**counts(np.arange(n)), "shapes": {key: list(shape) for key, shape in shapes.items()},
               "splits": {}, "validated": True}
    forced_groups = {str(value) for value in train_only_groups}
    if splits is None:
        if forced_groups:
            raise ValueError("Training-only groups require split assignments")
        return summary
    partitions = {}
    for name in ("train", "val", "test"):
        key = name + "_idx"
        if key not in splits:
            raise ValueError(f"Missing split {key}")
        partitions[name] = _indices(splits[key], n, name)
    if not np.array_equal(np.sort(np.concatenate(list(partitions.values()))), np.arange(n)):
        raise ValueError("Splits must cover every candidate exactly once")
    for field, ids in (("TIC stars", tic_ids), ("split groups", group_ids)):
        sets = [set(ids[indices]) for indices in partitions.values()]
        if any(sets[i] & sets[j] for i in range(3) for j in range(i + 1, 3)):
            raise ValueError(f"Splits contain overlapping {field}")
    for name, indices in partitions.items():
        if len(np.unique(labels[indices])) != 2:
            raise ValueError(f"Split {name} must contain both classes")
        if name != "train" and forced_groups.intersection(group_ids[indices]):
            raise ValueError("Inspected pilot groups must occur only in the training split")
        summary["splits"][name] = counts(indices)
    return summary
