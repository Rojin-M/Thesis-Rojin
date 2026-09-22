"""Bounded blind BLS proposals, independent of all catalog ephemerides.

Proposals are retained for review, including low-significance peaks. The white
noise depth S/N and sampling checks are not planet probabilities or calibrated
false-alarm statistics. No trained classifier is consulted here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import multiprocessing
import time

import astropy
import numpy as np
from astropy.timeseries import BoxLeastSquares
from scipy.signal import find_peaks

from .lightcurves import LightCurve, detrend
from .protocol import ValidationError

VERSION = "blind_bls_v1"


@dataclass(frozen=True)
class SearchConfig:
    period_min_days: float = .5
    period_max_days: float = 30.
    durations_hours: tuple = (.75, 1.25, 2., 3., 4.5, 6.)
    max_period_grid: int = 20000
    max_signals: int = 3
    max_seconds: int = 300
    minimum_sampled_events: int = 2
    minimum_event_points: int = 3
    minimum_event_fraction: float = .5
    detrend_window_days: float = 1.5
    oversample: int = 10
    mask_duration_factor: float = 1.5

    def __post_init__(self):
        numbers = (self.period_min_days, self.period_max_days, self.detrend_window_days,
                   self.minimum_event_fraction, self.mask_duration_factor, *self.durations_hours)
        if not all(math.isfinite(float(v)) for v in numbers):
            raise ValidationError("Search settings must be finite")
        if not .05 <= self.period_min_days < self.period_max_days <= 100:
            raise ValidationError("Period bounds must satisfy .05 <= min < max <= 100 days")
        for name, low, high in (("max_period_grid", 100, 20000), ("max_signals", 1, 3),
                                ("max_seconds", 1, 300), ("minimum_sampled_events", 2, 10),
                                ("minimum_event_points", 3, 20), ("oversample", 1, 20)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ValidationError("Invalid bounded search setting: " + name)
        if (not 1 <= len(self.durations_hours) <= 12 or not .5 <= self.minimum_event_fraction <= 1
                or not 1 <= self.mask_duration_factor <= 3 or not .5 <= self.detrend_window_days <= 10
                or any(not 0.25 <= d <= 24 or d / 24 >= self.period_min_days for d in self.durations_hours)
                or max(self.durations_hours) / 24 * 3 > self.detrend_window_days):
            raise ValidationError("Invalid durations, coverage, masking or detrending window")

    @classmethod
    def from_protocol(cls, protocol, **overrides):
        search = protocol["search"]
        cfg = cls(**{**{key: search[key] for key in ("period_min_days", "period_max_days", "max_period_grid", "minimum_sampled_events")},
                     "max_signals": search["max_signals_per_target"], "max_seconds": search["max_seconds_per_target"], **overrides})
        if (cfg.max_period_grid > search["max_period_grid"] or cfg.max_signals > search["max_signals_per_target"]
                or cfg.max_seconds > search["max_seconds_per_target"] or len(cfg.durations_hours) > search["max_duration_grid"]
                or cfg.period_min_days < search["period_min_days"] or cfg.period_max_days > search["period_max_days"]
                or cfg.minimum_sampled_events < search["minimum_sampled_events"]):
            raise ValidationError("Requested search exceeds registered protocol bounds")
        return cfg


def phase_distance(time_values, period, epoch):
    return (np.asarray(time_values) - epoch + .5 * period) % period - .5 * period


def _depth(flux, error, inside, outside):
    if inside.sum() < 2 or outside.sum() < 5:
        return {"depth": None, "error": None, "snr": None, "in_points": int(inside.sum()), "out_points": int(outside.sum())}
    wi, wo = 1 / error[inside] ** 2, 1 / error[outside] ** 2
    d = float(np.average(flux[outside], weights=wo) - np.average(flux[inside], weights=wi))
    sigma = float(np.sqrt(1 / wi.sum() + 1 / wo.sum()))
    return {"depth": d, "error": sigma, "snr": d / sigma, "in_points": int(inside.sum()), "out_points": int(outside.sum())}


def event_diagnostics(curve, period, epoch, duration, cfg):
    t, f, e = curve.time, curve.flux, curve.error
    phase = phase_distance(t, period, epoch)
    in_transit = np.abs(phase) <= duration / 2
    baseline = (np.abs(phase) >= duration) & (np.abs(phase) <= min(3 * duration, .45 * period))
    cycles = np.rint((t - epoch) / period).astype(int)
    cadence = float(np.median(np.diff(t)))
    first = int(math.ceil((t[0] - duration / 2 - epoch) / period))
    last = int(math.floor((t[-1] + duration / 2 - epoch) / period))
    events = []
    for cycle in range(first, last + 1):
        center = epoch + cycle * period
        inside = in_transit & (cycles == cycle)
        outside = baseline & (cycles == cycle)
        local_times = t[np.abs(t - center) <= 3 * duration]
        local_cadence = float(np.median(np.diff(local_times))) if len(local_times) >= 3 else cadence
        expected = max(duration / max(local_cadence, 1e-10), 1.)
        fraction = min(float(inside.sum()) / expected, 1.)
        left = int(np.count_nonzero(outside & (t < center)))
        right = int(np.count_nonzero(outside & (t > center)))
        supported = bool(inside.sum() >= cfg.minimum_event_points and fraction >= cfg.minimum_event_fraction and left >= 3 and right >= 3)
        events.append({"cycle": cycle, "center_btjd": center, "center_bjd_tdb": center + 2457000.,
                       "sampled_fraction": fraction, "expected_points": expected,
                       "baseline_left_points": left, "baseline_right_points": right,
                       "covered": supported, **_depth(f, e, inside, outside)})
    odd = _depth(f, e, in_transit & (cycles % 2 != 0), baseline & (cycles % 2 != 0))
    even = _depth(f, e, in_transit & (cycles % 2 == 0), baseline & (cycles % 2 == 0))
    difference = None
    if odd["error"] is not None and even["error"] is not None:
        difference = abs(odd["depth"] - even["depth"]) / math.hypot(odd["error"], even["error"])
    secondary_phase = phase_distance(t, period, epoch + .5 * period)
    secondary = _depth(f, e, np.abs(secondary_phase) <= duration / 2,
                       (np.abs(secondary_phase) >= duration) & (np.abs(secondary_phase) <= min(3 * duration, .45 * period)))
    contributions = [max(event["snr"] or 0, 0) ** 2 for event in events]
    dominance = max(contributions) / sum(contributions) if sum(contributions) else None
    n_covered = sum(event["covered"] for event in events)
    warnings = []
    if n_covered < cfg.minimum_sampled_events:
        warnings.append("insufficient_covered_events")
    if dominance is not None and dominance > .8:
        warnings.append("one_event_dominates_white_noise_snr")
    if difference is not None and difference > 3:
        warnings.append("odd_even_depth_difference")
    if secondary["snr"] is not None and secondary["snr"] > 3:
        warnings.append("secondary_eclipse_or_correlated_variability")
    return {"events": events, "n_expected_events": len(events), "n_sampled_events": sum(e["in_points"] > 0 for e in events),
            "n_covered_events": n_covered, "sampling_gate_passed": n_covered >= cfg.minimum_sampled_events,
            "in_transit_points": int(in_transit.sum()), "cadence_days": cadence,
            "odd_event_depth": odd, "even_event_depth": even, "odd_even_difference_sigma": difference,
            "secondary_at_phase_half": secondary, "single_event_snr2_fraction": dominance,
            "warnings": warnings, "uncertainty_model": "independent_samples_only_not_red_noise_corrected",
            "missing_diagnostics": ["centroid", "difference_images", "aperture_dependence", "nearby_source_contamination"]}


def harmonic_relation(a, b, baseline_days):
    """Require both period commensurability and aligned epochs; never collapse by period alone."""
    ratio = a["period_days"] / b["period_days"]
    for expected in (.5, 2 / 3, 1., 1.5, 2., 3.):
        drift = abs(a["period_days"] - expected * b["period_days"]) * baseline_days / a["period_days"]
        tolerance = max(a["duration_hours"], b["duration_hours"]) / 24
        phase = abs(float(phase_distance([a["epoch_btjd"]], min(a["period_days"], b["period_days"]), b["epoch_btjd"])[0]))
        if abs(ratio - expected) < .015 and drift < tolerance and phase <= tolerance:
            return {"period_ratio": expected, "accumulated_drift_days": drift, "epoch_separation_days": phase}
    return None


def _power(bls, periods, durations, cfg, deadline):
    pieces = []
    for start in range(0, len(periods), 256):
        if time.monotonic() >= deadline:
            raise TimeoutError("Bounded BLS search exceeded the target time allowance")
        result = bls.power(periods[start:start + 256], durations, objective="likelihood", method="fast", oversample=cfg.oversample)
        pieces.append({k: np.asarray(result[k]) for k in ("period", "power", "duration", "transit_time", "depth", "depth_err", "depth_snr")})
    return {key: np.concatenate([p[key] for p in pieces]) for key in pieces[0]}


def _peak(record, index):
    return {"period_days": float(record["period"][index]), "epoch_btjd": float(record["transit_time"][index]),
            "duration_hours": float(record["duration"][index] * 24), "depth_relative_flux": float(record["depth"][index]),
            "depth_error_relative_flux": float(record["depth_err"][index]), "depth_snr_white": float(record["depth_snr"][index]),
            "bls_log_likelihood": float(record["power"][index])}


def search(curve, cfg=SearchConfig()):
    """No target catalog, known period, known epoch, model or evaluation truth argument."""
    began = time.monotonic()
    deadline = began + cfg.max_seconds
    flat, raw = detrend(curve, cfg.detrend_window_days)
    baseline = float(np.ptp(flat.time))
    high = min(cfg.period_max_days, baseline / (cfg.minimum_sampled_events - 1))
    if high <= cfg.period_min_days:
        raise ValidationError("Baseline is too short for the requested blind period range")
    durations = np.asarray(sorted(set(cfg.durations_hours))) / 24
    n_coarse = max(80, int(cfg.max_period_grid * .8))
    periods = 1 / np.linspace(1 / cfg.period_min_days, 1 / high, n_coarse)
    df = float(abs(1 / periods[1] - 1 / periods[0]))
    proposals, rounds, suppressed = [], [], []
    keep = np.ones(len(flat.time), bool)
    for iteration in range(cfg.max_signals):
        if keep.sum() < 200:
            break
        current = LightCurve(flat.time[keep], flat.flux[keep], flat.error[keep], flat.segment[keep], flat.sources, flat.metadata)
        bls = BoxLeastSquares(current.time, current.flux, current.error)
        broad = _power(bls, periods, durations, cfg, deadline)
        maxima = np.r_[0, find_peaks(broad["power"])[0], len(periods) - 1]
        maxima = maxima[np.argsort(broad["power"][maxima])[::-1]][:8]
        n_each = max(2, (cfg.max_period_grid - n_coarse) // len(maxima))
        refine = np.concatenate([1 / np.linspace(max(1 / high, 1 / periods[i] - df),
                                                min(1 / cfg.period_min_days, 1 / periods[i] + df), n_each) for i in maxima])
        fine = _power(bls, np.unique(refine), durations, cfg, deadline)
        combined = {k: np.r_[broad[k], fine[k]] for k in broad}
        rank = np.argsort(combined["power"])[::-1]
        alternatives = []
        for i in rank:
            proposed = _peak(combined, i)
            if not all(np.isfinite(v) for v in proposed.values()) or proposed["depth_relative_flux"] <= 0:
                continue
            if all(abs(proposed["period_days"] - other["period_days"]) / other["period_days"] > .005 for other in alternatives):
                alternatives.append(proposed)
            if len(alternatives) >= 12:
                break
        rounds.append({"iteration": iteration + 1, "periods": broad["period"], "power": broad["power"],
                       "evaluated_periods": len(combined["period"]), "samples": int(keep.sum()), "alternatives": alternatives})
        if not alternatives:
            break
        best = alternatives[0]
        relation = next(((p, harmonic_relation(best, p, baseline)) for p in proposals if harmonic_relation(best, p, baseline)), None)
        mask = np.abs(phase_distance(flat.time, best["period_days"], best["epoch_btjd"])) <= best["duration_hours"] / 24 / 2 * cfg.mask_duration_factor
        keep &= ~mask
        if relation:
            suppressed.append({**best, "reason": "aligned_harmonic_of_prior_signal", "prior_rank": relation[0]["rank"], "relation": relation[1]})
            continue
        best.update(rank=len(proposals) + 1, search_iteration=iteration + 1,
                    diagnostics=event_diagnostics(current, best["period_days"], best["epoch_btjd"], best["duration_hours"] / 24, cfg),
                    aliases=[{**p, "relation": harmonic_relation(p, best, baseline)} for p in alternatives[1:]],
                    iterative_masked_points=int((~keep).sum()))
        proposals.append(best)
    return {"version": VERSION, "config": asdict(cfg), "used_catalog_ephemeris": False,
            "astropy_version": astropy.__version__, "numpy_version": np.__version__,
            "proposals": proposals, "rounds": rounds, "suppressed_harmonics": suppressed,
            "search_grid": {"period_min_days": cfg.period_min_days, "period_max_days": high,
                "coarse_period_count": n_coarse, "frequency_spacing_per_day": df,
                "shortest_duration_heuristic_df": float(min(durations) / baseline ** 2),
                "coarse_grid_underresolved": bool(df > min(durations) / baseline ** 2),
                "refinement": "top_eight_local_peaks_within_fixed_total_grid_budget",
                "limitation": "Bounded coarse grids can miss narrow peaks; refinement cannot guarantee completeness."},
            "flat": flat, "raw": raw, "tls": {"state": "not_run", "reason": "Optional TLS adapter not implemented; dependency absent in reference environment"},
            "score_semantics": "BLS white-noise ranking statistic; not a false-alarm or planet probability"}


def _child(connection, curve, cfg):
    try:
        connection.send((True, search(curve, cfg)))
    except Exception as exc:
        connection.send((False, {"type": type(exc).__name__, "message": str(exc)}))
    finally:
        connection.close()


def bounded_search(curve, cfg, heartbeat=None):
    """One owned CPU subprocess with a hard wall-clock deadline, including C calls."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(child, curve, cfg), daemon=True)
    process.start()
    child.close()
    deadline = time.monotonic() + cfg.max_seconds
    try:
        while time.monotonic() < deadline:
            if parent.poll(min(1., max(0., deadline - time.monotonic()))):
                ok, result = parent.recv()
                if not ok:
                    raise RuntimeError(result["type"] + ": " + result["message"])
                return result
            if not process.is_alive():
                raise RuntimeError("BLS worker exited without a result")
            if heartbeat:
                heartbeat()
        raise TimeoutError("BLS worker reached the hard wall-clock target limit")
    finally:
        parent.close()
        process.join(timeout=.1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
