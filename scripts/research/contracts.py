"""Integration guard for raw, pre-normalization shared_v1 model inputs.

Import this at the feature/scoring boundary, not during HTTP startup. The frozen
normalizer remains scripts.data.tess_dataset.apply_normalization; do not fit new
moments to discovery targets. This guard does not construct or discover signals.
"""
from .protocol import ValidationError


def validate_shared_inputs(arrays):
    import numpy as np

    shapes = {"X_global": (200, 3), "X_local": (100, 3), "X_scalar": (7,), "X": (907,)}
    n = None
    for name, shape in shapes.items():
        value = arrays.get(name)
        if not isinstance(value, np.ndarray) or value.ndim != len(shape) + 1 or value.shape[1:] != shape:
            raise ValidationError(f"{name} must have batched shape (N, {', '.join(map(str, shape))})")
        if n is None:
            n = len(value)
        if not n or len(value) != n or value.dtype != np.float32 or not np.isfinite(value).all():
            raise ValidationError("Shared inputs must be nonempty, equally batched, finite float32 arrays")
    for name in ("X_global", "X_local"):
        if (arrays[name][..., 2] < 0).any():
            raise ValidationError("Coverage counts cannot be negative")
    expected = np.concatenate([arrays["X_global"].transpose(0, 2, 1).reshape(n, -1),
                               arrays["X_local"].transpose(0, 2, 1).reshape(n, -1), arrays["X_scalar"]], axis=1)
    if not np.array_equal(arrays["X"], expected):
        raise ValidationError("Raw flat features must be channel-major global/local views followed by seven scalars")
    return {"contract": "shared_v1", "n_candidates": n, "dtype": "float32",
            "shapes": {name: list(arrays[name].shape) for name in shapes}}
