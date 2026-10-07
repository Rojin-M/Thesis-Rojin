"""Duration-aware event search and calibration for the recovery experiment.

This is an additive research detector, not a replacement for a frozen model.
Scores are relative dip significances, not planet probabilities.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks
from scipy.stats import chi2

from scripts.experiments.ai_telescope_continuous_validation import aperture_mask


def aperture_samples(pixels):
    """Reject incomplete apertures rather than interpreting NaNs as zero flux."""
    aperture = pixels.flux[:, aperture_mask(pixels)]
    valid = ((pixels.quality == 0) & np.isfinite(pixels.time)
             & np.isfinite(aperture).all(axis=1))
    time, flux = pixels.time[valid], aperture[valid].sum(axis=1)
    if len(time) < 200 or np.any(np.diff(time) <= 0):
        raise ValueError("Insufficient or non-increasing aperture samples")
    baseline = float(np.median(flux))
    if baseline <= 0:
        raise ValueError("Nonpositive aperture baseline")
    return time, flux / baseline


def suppress_overlaps(events):
    """Keep the strongest event when multiple durations describe the same dip."""
    kept = []
    for event in sorted(events, key=lambda e: (-e["score"], e["center_btjd"], e["duration_hours"])):
        if all(abs(event["center_btjd"] - other["center_btjd"]) >
               max(event["duration_hours"], other["duration_hours"]) / 48 for other in kept):
            kept.append(event)
    return sorted(kept, key=lambda e: e["center_btjd"])


def single_event_search(time, flux, durations_hours, minimum_score=3., coverage=.7):
    """Scan boxes against two adjacent sidebands on actual observation times.

    Each sideband is 1.5 durations wide. Their average removes local linear
    trends. Noise is the larger of a white-noise estimate and the robust spread
    of same-duration filtered measurements, allowing for correlated residuals.
    Coverage checks apply separately to the dip and both sidebands.
    """
    time, flux = np.asarray(time, float), np.asarray(flux, float)
    if (time.ndim != 1 or flux.shape != time.shape or len(time) < 200
            or not np.isfinite(time).all() or not np.isfinite(flux).all()
            or np.any(np.diff(time) <= 0)):
        raise ValueError("Expected finite, aligned, increasing photometry")
    durations = np.asarray(durations_hours, float)
    if (durations.ndim != 1 or not len(durations) or not np.isfinite(durations).all()
            or np.any(durations <= 0) or not 0 < coverage <= 1
            or not np.isfinite(minimum_score) or minimum_score < 0):
        raise ValueError("Invalid event-search settings")
    cadence = float(np.median(np.diff(time)))
    differences = np.diff(flux)[np.diff(time) <= 1.5 * cadence]
    sigma = 1.4826 * np.median(np.abs(differences - np.median(differences))) / np.sqrt(2)
    if not np.isfinite(sigma) or sigma <= 0:
        return []
    cumulative = np.r_[0., np.cumsum(flux - np.median(flux))]
    candidates = []
    for hours in durations:
        duration = hours / 24
        edges = [np.searchsorted(time, time + offset * duration)
                 for offset in (-2, -.5, .5, 2)]
        counts = [edges[i+1] - edges[i] for i in range(3)]
        means = [(cumulative[edges[i+1]] - cumulative[edges[i]]) / np.maximum(counts[i], 1)
                 for i in range(3)]
        good = ((counts[1] >= max(3, coverage * duration / cadence))
                & (counts[0] >= coverage * 1.5 * duration / cadence)
                & (counts[2] >= coverage * 1.5 * duration / cadence))
        if good.sum() < 100:
            continue
        depth = (means[0] + means[2]) / 2 - means[1]
        white_error = sigma * np.sqrt(1 / np.maximum(counts[1], 1)
                        + .25 / np.maximum(counts[0], 1) + .25 / np.maximum(counts[2], 1))
        raw = depth / white_error
        center = float(np.median(raw[good]))
        inflation = max(1., float(1.4826 * np.median(np.abs(raw[good] - center))))
        score = np.where(good, (raw - center) / inflation, -np.inf)
        peaks, _ = find_peaks(score, height=minimum_score,
                             distance=max(1, int(duration / cadence / 2)))
        for index in peaks:
            candidates.append({"center_btjd": float(time[index]), "duration_hours": float(hours),
                               "score": float(score[index]), "relative_depth": float(depth[index]),
                               "noise_inflation": inflation})
    return suppress_overlaps(candidates)


def bootstrap_indices(hosts, samples=2000, seed=28092027):
    if hosts < 2 or samples < 100:
        raise ValueError("Calibration needs multiple hosts and bootstrap draws")
    return np.random.default_rng(seed).integers(0, hosts, (samples, hosts))


def rate_diagnostics(counts, exposure, resamples):
    counts, exposure = np.asarray(counts, int), np.asarray(exposure, float)
    if (counts.shape != exposure.shape or np.any(counts < 0) or not np.isfinite(exposure).all()
            or np.any(exposure <= 0)):
        raise ValueError("Invalid control counts/exposure")
    days, count = float(exposure.sum()), int(counts.sum())
    bootstrap = counts[resamples].sum(axis=1) / exposure[resamples].sum(axis=1) * 27
    poisson = float(.5 * chi2.ppf(.95, 2 * (count + 1)) / days * 27)
    upper = max(poisson, float(np.quantile(bootstrap, .95)))
    return {"events": count, "exposure_days": days, "events_per_27_days": count / days * 27,
            "poisson_upper_95": poisson, "host_bootstrap_upper_95": float(np.quantile(bootstrap, .95)),
            "conservative_upper": upper}


def select_count_threshold(thresholds, counts, exposure, budget, margin=.5):
    """Require a margin and account for host clusters, using calibration only.

    These upper estimates are operational diagnostics, not a simultaneous or
    distribution-shift coverage guarantee. Fail closed if no threshold fits.
    Neural event grouping need not be monotone, so every higher tested threshold
    must satisfy the rule as well.
    """
    thresholds, counts = np.asarray(thresholds, float), np.asarray(counts, int)
    if (thresholds.ndim != 1 or not len(thresholds) or np.any(np.diff(thresholds) <= 0)
            or not np.isfinite(thresholds).all() or counts.shape != (len(thresholds), len(exposure))
            or not 0 < margin <= 1 or not np.isfinite(budget) or budget <= 0):
        raise ValueError("Invalid threshold calibration")
    indices = bootstrap_indices(len(exposure))
    table = [{"threshold": float(t), **rate_diagnostics(c, exposure, indices)}
             for t, c in zip(thresholds, counts)]
    tail_upper = np.maximum.accumulate([row["conservative_upper"] for row in table][::-1])[::-1]
    eligible = np.flatnonzero(tail_upper <= budget * margin)
    if not len(eligible):
        raise ValueError("Insufficient calibration exposure for the requested control budget")
    return {"selected_threshold": float(thresholds[eligible[0]]), "selected": table[eligible[0]],
            "budget_per_27_days": budget, "calibration_margin": margin, "table": table}


def exact_score_threshold(events_by_host, exposure, budget, margin=.5, minimum=0.):
    """Use every observed score boundary, including tied, event-weighted scores."""
    if len(events_by_host) != len(exposure):
        raise ValueError("Control hosts and exposures differ")
    values = [float(e["score"]) for host in events_by_host for e in host]
    if not np.isfinite(values).all() or not np.isfinite(minimum):
        raise ValueError("Nonfinite calibration score")
    # Acceptance is >= threshold; nextafter excludes the entire tied group.
    thresholds = sorted({float(minimum), *[float(np.nextafter(score, np.inf))
                                          for score in values if score >= minimum]})
    counts = [[sum(int(e.get("count", 1)) for e in host if e["score"] >= threshold)
               for host in events_by_host] for threshold in thresholds]
    return select_count_threshold(thresholds, counts, exposure, budget, margin)
