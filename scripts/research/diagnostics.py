"""Descriptive transit and native light-curve evidence; never a planet validator."""
import io
import math

import numpy as np
from astropy.io import fits

from .detection import _depth, phase_distance
from .lightcurves import snapshot_file, _fits
from .protocol import ValidationError

VERSION = "vetting_diagnostics_v1"
LIMITATIONS = ["White-noise depth errors do not account for correlated stellar/instrument noise.",
              "Scanning secondary phase incurs a trials effect; maximum S/N is descriptive, not a false-alarm probability.",
              "Photometric centroids cannot replace difference-image source localization."]


def _event_group(events):
    values = [e for e in events if e["covered"] and e.get("error") and e.get("depth") is not None]
    if not values:
        return {"n_events": 0, "depth": None, "white_error": None, "event_scatter_error": None}
    depth = np.asarray([e["depth"] for e in values])
    weight = 1 / np.asarray([e["error"] for e in values]) ** 2
    return {"n_events": len(values), "depth": float(np.average(depth, weights=weight)),
            "white_error": float(1 / np.sqrt(weight.sum())),
            "event_scatter_error": float(np.std(depth, ddof=1) / np.sqrt(len(depth))) if len(depth) > 1 else None}


def transit_diagnostics(candidate, arrays, detection):
    eph = candidate["ephemeris"]
    period, epoch, duration = eph["period_days"], eph["epoch_bjd_tdb"] - 2457000., eph["duration_hours"] / 24
    t, f, e = (arrays[key] for key in ("time_btjd", "flux", "flux_err"))
    phase = phase_distance(t, period, epoch)
    recorded = detection["proposal"]["diagnostics"]
    odd = _event_group([v for v in recorded["events"] if v["cycle"] % 2])
    even = _event_group([v for v in recorded["events"] if not v["cycle"] % 2])
    empirical_sigma = None
    if all(g["event_scatter_error"] is not None for g in (odd, even)):
        error = math.hypot(*[max(g["white_error"], g["event_scatter_error"]) for g in (odd, even)])
        empirical_sigma = abs(odd["depth"] - even["depth"]) / error if error else None
    primary_excluded = np.abs(phase) > duration
    scans = []
    for fraction in np.linspace(.02, .98, 97):
        if min(fraction, 1 - fraction) * period <= 1.5 * duration:
            continue
        distance = np.abs(phase_distance(t, period, epoch + fraction * period))
        inside = (distance <= duration / 2) & primary_excluded
        outside = (distance >= duration) & (distance <= min(3 * duration, .45 * period)) & primary_excluded
        item = _depth(f, e, inside, outside)
        scans.append({"phase": float(fraction), **item})
    sampled = [item for item in scans if item["snr"] is not None]
    best = max(sampled, key=lambda item: item["snr"]) if sampled else None
    aliases = []
    for multiplier in (.5, 1., 2., 3.):
        trial = period * multiplier
        delta = np.abs(phase_distance(t, trial, epoch))
        measurement = _depth(f, e, delta <= duration / 2,
                             (delta >= duration) & (delta <= min(3 * duration, .45 * trial)))
        aliases.append({"period_multiplier": multiplier, "period_days": trial, "epoch_bjd_tdb": eph["epoch_bjd_tdb"],
                        "duration_hours": eph["duration_hours"], **measurement})
    # Edge exposure: nearest observation discontinuity, not a claim about a spacecraft event.
    cadence = float(np.median(np.diff(t)))
    gaps = (np.diff(t) > 5 * cadence) | (np.diff(arrays["segment"]) != 0)
    starts = t[np.r_[True, gaps]]; stops = t[np.r_[gaps, True]]
    inside = np.abs(phase) <= duration / 2
    near = np.zeros(len(t), dtype=bool)
    for edge in np.r_[starts, stops]:
        near |= np.abs(t - edge) <= duration
    edge_fraction = float(np.count_nonzero(near & inside) / inside.sum()) if inside.any() else None
    result = {"version": VERSION, "time_system": "BTJD", "period_unit": "day", "duration_unit": "hour",
              "event_coverage": recorded, "odd_even_by_covered_event": {"odd": odd, "even": even,
                  "difference_sigma_with_event_scatter_floor": empirical_sigma,
                  "state": "complete" if empirical_sigma is not None else "incomplete",
                  "method": "inverse_variance_event_depths; uncertainty=max(white_error,event_scatter/sqrt(N)); at least two events per parity"},
              "secondary_scan": {"state": "complete" if sampled else "incomplete", "trials": len(scans),
                  "fixed_duration_hours": eph["duration_hours"], "best": best, "samples": scans,
                  "false_alarm_calibrated": False, "primary_window_excluded": True},
              "aliases": {"state": "complete" if all(v["depth"] is not None for v in aliases) else "incomplete",
                  "fixed_epoch_comparisons": aliases, "interpretation": "fixed_ephemeris_depth_tests_not_independent_searches_or_model_selection",
                  "detector_suppressed_harmonics": detection.get("suppressed_harmonics", [])},
              "gap_edges": {"in_transit_fraction_within_one_duration_of_segment_edge": edge_fraction,
                            "spacecraft_event_catalog_checked": False},
              "limitations": LIMITATIONS,
              "missing_diagnostics": ["difference_images", "aperture_dependence", "nearby_Gaia_sources", "spacecraft_event_catalog"]}
    complete = empirical_sigma is not None and sampled and result["aliases"]["state"] == "complete"
    return ("complete" if complete else "incomplete"), result


def _centroid_axis(t, value, period, epoch, duration):
    good = np.isfinite(t) & np.isfinite(value)
    t, value = t[good], value[good]
    phase = phase_distance(t, period, epoch)
    cycles = np.rint((t - epoch) / period).astype(int)
    inside = np.abs(phase) <= duration / 2
    outside = (np.abs(phase) >= duration) & (np.abs(phase) <= min(3 * duration, .45 * period))
    events = []
    for cycle in np.unique(cycles[inside]):
        vi, vo = value[inside & (cycles == cycle)], value[outside & (cycles == cycle)]
        if len(vi) < 3 or len(vo) < 5:
            continue
        sigma = float(np.sqrt(np.var(vi, ddof=1) / len(vi) + np.var(vo, ddof=1) / len(vo)))
        shift = float(np.mean(vi) - np.mean(vo))
        events.append({"cycle": int(cycle), "shift_pixel": shift, "white_error_pixel": sigma,
                       "white_sigma": shift / sigma if sigma > 0 else None})
    values = [r for r in events if r["white_error_pixel"] > 0]
    if not values:
        return {"state": "incomplete", "events": events, "reason": "insufficient_centroid_event_samples"}
    weights = 1 / np.asarray([r["white_error_pixel"] for r in values]) ** 2
    shift = float(np.average([r["shift_pixel"] for r in values], weights=weights))
    error = float(1 / np.sqrt(weights.sum()))
    return {"state": "complete", "events": events, "shift_pixel": shift, "white_error_pixel": error,
            "white_sigma": shift / error, "interpretation": "in_minus_nearby_out_of_transit_photometric_centroid_not_source_localization"}


def native_evidence(inputs, candidate):
    eph = candidate["ephemeris"]
    period, epoch, duration = eph["period_days"], eph["epoch_bjd_tdb"] - 2457000., eph["duration_hours"] / 24
    centroid, contamination = [], []
    for path in inputs["paths"]:
        payload, receipt = snapshot_file(path)
        if receipt["sha256"] != inputs["sha256"][str(path)]:
            raise ValidationError("Native diagnostic source changed since detection")
        if not str(path).lower().endswith((".fits", ".fit")):
            centroid.append({"source_sha256": receipt["sha256"], "state": "incomplete", "reason": "input_has_no_native_centroid_columns"})
            contamination.append({"source_sha256": receipt["sha256"], "state": "incomplete", "reason": "input_has_no_native_crowding_headers"})
            continue
        (time, flux, error, quality), metadata = _fits(payload, inputs["mission"], inputs["target_id"])
        good = np.isfinite(time) & np.isfinite(flux) & np.isfinite(error) & (flux > 0) & (error > 0) & (quality == 0)
        with fits.open(io.BytesIO(payload), memmap=False) as hdus:
            h, table = hdus[1].header, hdus[1].data
            item = {"source_sha256": receipt["sha256"], "time_system": "BTJD", "axes": {}}
            for key in ("MOM_CENTR1", "MOM_CENTR2"):
                if key in hdus[1].columns.names:
                    item["axes"][key] = _centroid_axis(time[good], np.asarray(table[key], dtype=float)[good], period, epoch, duration)
            item.update(state="incomplete", reason="difference_images_and_source_localization_unavailable",
                        method="native_flux_weighted_centroid_local_event_baseline", source_metadata=metadata)
            centroid.append(item)
            fractions = {}
            for key in ("CROWDSAP", "FLFRCSAP"):
                value = h.get(key, hdus[0].header.get(key))
                if value is not None:
                    try:
                        value = float(value)
                        if np.isfinite(value) and 0 <= value <= 1:
                            fractions[key] = value
                    except (ValueError, TypeError):
                        pass
            contamination.append({"source_sha256": receipt["sha256"], "state": "incomplete", "header_fractions": fractions,
                "reason": "no_nearby_source_catalog_or_aperture_dependence_test",
                "interpretation": "pipeline_aperture_estimates_only_PDCSAP_already_corrected_do_not_apply_again"})
    return {"centroid": {"state": "incomplete", "products": centroid, "difference_images": "unavailable",
                         "limitations": LIMITATIONS},
            "contamination": {"state": "incomplete", "products": contamination,
                              "nearby_sources": "not_queried", "aperture_dependence": "unavailable"}}
