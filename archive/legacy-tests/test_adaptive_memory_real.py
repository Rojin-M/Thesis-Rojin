import numpy as np

from scripts.experiments.adaptive_memory import MemoryConfig, MultiTimescaleTestTimeMemory
from scripts.experiments.adaptive_memory_real import inject_box, memory_curve, normalized_curve
from scripts.research.lightcurves import LightCurve


def fixture_curve(size=400):
    time = 1300 + np.arange(size) / 48
    flux = 1000 + 2 * np.sin(np.arange(size) / 31)
    return LightCurve(time, flux, np.full(size, .5), np.zeros(size, dtype=np.int32), [], {})


def test_injection_precedes_preprocessing_and_has_expected_depth():
    original = fixture_curve()
    injected, truth = inject_box(original, 2.731, .008, 2.4)
    mask = injected.flux != original.flux
    assert mask.any()
    np.testing.assert_allclose(injected.flux[mask] / original.flux[mask], .992)
    assert truth["period_days"] == 2.731
    assert "truth" not in injected.metadata


def test_all_memory_modes_preserve_detector_shape_and_positive_flux():
    curve = normalized_curve(fixture_curve())
    memory = MultiTimescaleTestTimeMemory(MemoryConfig())
    for mode in ("raw", "frozen", "adaptive", "protected"):
        transformed, diagnostics = memory_curve(curve, mode, memory)
        assert len(transformed.time) == len(curve.time)
        assert np.all(transformed.flux > 0)
        assert np.isfinite(transformed.flux).all()
        assert 0 <= diagnostics["protection_fraction"] <= 1
