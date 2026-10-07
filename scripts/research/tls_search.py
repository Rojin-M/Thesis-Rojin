"""Bounded Transit Least Squares diagnostics for an already flattened light curve."""
from __future__ import annotations

import math
import time

import numpy as np
from transitleastsquares import transitleastsquares

from .detection import SearchConfig, event_diagnostics
from .lightcurves import LightCurve
from .protocol import ValidationError

VERSION = "tls_diagnostic_v1"


def _finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def search_tls(flat: LightCurve, *, period_min_days=.5, period_max_days=20.,
               oversampling_factor=2, duration_grid_step=1.2, use_threads=4):
    """Run TLS without catalog ephemerides and return a compact JSON-safe record."""
    if (not .05 <= period_min_days < period_max_days <= 100
            or type(oversampling_factor) is not int or not 1 <= oversampling_factor <= 5
            or type(use_threads) is not int or not 1 <= use_threads <= 8
            or not 1.01 <= duration_grid_step <= 1.5):
        raise ValidationError("Invalid bounded TLS configuration")
    if len(flat.time) < 200 or not np.isfinite(flat.time).all() or not np.isfinite(flat.flux).all():
        raise ValidationError("TLS requires at least 200 finite flattened samples")
    baseline = float(np.ptp(flat.time))
    upper = min(float(period_max_days), baseline / 2)
    if upper <= period_min_days:
        raise ValidationError("Light-curve baseline is too short for TLS period bounds")
    began = time.monotonic()
    result = transitleastsquares(flat.time, flat.flux, flat.error, verbose=False).power(
        period_min=period_min_days, period_max=upper, n_transits_min=2,
        oversampling_factor=oversampling_factor, duration_grid_step=duration_grid_step,
        use_threads=use_threads, show_progress_bar=False)
    values = (result.period, result.T0, result.duration, result.depth, result.SDE, result.snr)
    if not np.isfinite(values).all() or result.duration <= 0 or result.period <= 0:
        raise ValidationError("TLS did not return a finite transit solution")
    duration_days = float(result.duration)
    cfg = SearchConfig(period_min_days=period_min_days, period_max_days=period_max_days)
    diagnostics = event_diagnostics(flat, float(result.period), float(result.T0), duration_days, cfg)
    fap = float(result.FAP) if np.isfinite(result.FAP) else None
    return {
        "version": VERSION,
        "used_catalog_ephemeris": False,
        "period_days": float(result.period),
        "period_uncertainty_days": _finite(result.period_uncertainty),
        "epoch_btjd": float(result.T0),
        "duration_hours": duration_days * 24,
        "depth_relative_flux": float(1 - result.depth),
        "radius_ratio": _finite(result.rp_rs),
        "sde": float(result.SDE),
        "sde_raw": float(result.SDE_raw),
        "snr_white": float(result.snr),
        "false_alarm_probability_analytic": fap,
        "odd_even_mismatch_sigma": _finite(result.odd_even_mismatch),
        "transit_count": int(result.transit_count),
        "distinct_transit_count": int(result.distinct_transit_count),
        "empty_transit_count": int(result.empty_transit_count),
        "periods_evaluated": int(len(result.periods)),
        "runtime_seconds": time.monotonic() - began,
        "diagnostics": diagnostics,
        "config": {"period_min_days": period_min_days, "period_max_days": upper,
                   "n_transits_min": 2, "oversampling_factor": oversampling_factor,
                   "duration_grid_step": duration_grid_step, "use_threads": use_threads},
        "score_semantics": "TLS SDE and analytic FAP are ranking diagnostics, not calibrated planet probabilities",
    }


def ephemeris_agreement(bls, tls):
    """Describe agreement across common half/double-period aliases."""
    bp, tp = float(bls["period_days"]), float(tls["period_days"])
    options = [(factor, abs(bp - factor * tp) / bp) for factor in (.5, 1., 2.)]
    factor, fractional = min(options, key=lambda row: row[1])
    aligned_period = factor * tp
    duration = max(float(bls["duration_hours"]), float(tls["duration_hours"])) / 24
    epoch_delta = abs((float(bls["epoch_btjd"]) - float(tls["epoch_btjd"]) + .5 * aligned_period)
                      % aligned_period - .5 * aligned_period)
    return {"tls_period_multiplier": factor, "fractional_period_difference": fractional,
            "epoch_phase_difference_days": epoch_delta,
            "agrees_within_one_duration": bool(fractional <= .01 and epoch_delta <= duration)}
