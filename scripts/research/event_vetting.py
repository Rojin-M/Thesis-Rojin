"""Single-event diagnostics; all scores are review aids, never planet probabilities."""
from __future__ import annotations

import io
import math
import warnings

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from astropy import units as u
from scipy.ndimage import binary_dilation

from .detection import phase_distance
from .protocol import ValidationError

GAIA_ENDPOINT = "https://gea.esac.esa.int/tap-server/tap/sync"


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def event_masks(time, quality, start, end, excluded_intervals=()):
    """Use actual segment bounds, not its maximum neural score as a transit epoch."""
    if not np.isfinite([start, end]).all() or not 0 < end - start <= 1:
        raise ValidationError("Single-event bounds must span (0, 1] days")
    time = np.asarray(time)
    center, width = (start + end) / 2, end - start
    usable = np.isfinite(time) & (np.asarray(quality) == 0)
    inside = usable & (time >= start) & (time <= end)
    outside = usable & (abs(time - center) >= width) & (abs(time - center) <= 3 * width)
    for lower, upper in excluded_intervals:
        outside &= ~((time >= lower) & (time <= upper))
    if inside.sum() < 5 or (outside & (time < center)).sum() < 5 or (outside & (time > center)).sum() < 5:
        raise ValidationError("Insufficient event cadences or two-sided uncontaminated baseline")
    return inside, outside


def known_intervals(time, candidates):
    finite = np.asarray(time)[np.isfinite(time)]
    result = []
    for row in candidates:
        period = float(row["period_days"])
        epoch = float(row["epoch_bjd_tdb"]) - 2457000
        duration = float(row["duration_hours"]) / 24
        for k in range(math.floor((finite.min() - epoch) / period) - 1,
                       math.ceil((finite.max() - epoch) / period) + 2):
            center = epoch + k * period
            result.append((center - duration, center + duration))
    return result


def local_difference(time, values, inside, outside, center):
    """Fit a linear local baseline; preserve dimmings and brightening signs.

    Errors use residual scatter and linear-fit covariance, assuming independent
    cadences. They are explicitly not calibrated against red noise or selection.
    Columns with any missing local flux are left unavailable, never filled by zero.
    """
    values = np.asarray(values, float)
    shape = values.shape[1:]
    y = values.reshape(len(time), -1)
    finite = np.isfinite(y[inside | outside]).all(axis=0)
    x = np.column_stack([np.ones(len(time)), np.asarray(time) - center])
    reference = np.full(y.shape[1], np.nan)
    difference = reference.copy(); uncertainty = reference.copy()
    residual = np.full(y.shape, np.nan)
    if finite.any():
        xo, xi = x[outside], x[inside]
        coefficients = np.linalg.lstsq(xo, y[outside][:, finite], rcond=None)[0]
        local_residual = y[:, finite] - x @ coefficients
        reference[finite] = coefficients[0]
        difference[finite] = -local_residual[inside].mean(axis=0)
        out_var = (local_residual[outside] ** 2).sum(axis=0) / (outside.sum() - 2)
        in_var = np.var(local_residual[inside], axis=0, ddof=1)
        avg_x = xi.mean(axis=0)
        leverage = float(avg_x @ np.linalg.inv(xo.T @ xo) @ avg_x)
        uncertainty[finite] = np.sqrt(np.maximum(out_var, in_var) / inside.sum() + out_var * leverage)
        residual[:, finite] = local_residual
    return (reference.reshape(shape), difference.reshape(shape), uncertainty.reshape(shape),
            residual.reshape(values.shape))


def _center(image):
    weight = np.where(np.isfinite(image), np.maximum(image, 0), 0)
    if weight.sum() <= 0:
        return None
    yy, xx = np.indices(weight.shape)
    return [float((xx * weight).sum() / weight.sum()), float((yy * weight).sum() / weight.sum())]


def pixel_geometry(path):
    with fits.open(path, memmap=False) as hdus:
        wcs = WCS(hdus[2].header).celestial
        if not wcs.has_celestial:
            raise ValidationError("Target-pixel celestial WCS unavailable")
        ra = float(hdus[0].header["RA_OBJ"])
        dec = float(hdus[0].header["DEC_OBJ"])
        x, y = wcs.world_to_pixel_values(ra, dec)
    return wcs, ra, dec, [float(x), float(y)]


def single_event_pixels(pixels, start, end, *, excluded_intervals=(), seed=92028):
    inside, outside = event_masks(pixels.time, pixels.quality, start, end, excluded_intervals)
    center = (start + end) / 2
    reference, difference, error, _ = local_difference(pixels.time, pixels.flux, inside, outside, center)
    pipeline = (pixels.aperture & 2) != 0
    if not pipeline.any():
        raise ValidationError("No pipeline aperture")
    _, _, _, target_xy = pixel_geometry(pixels.path)
    yy, xx = np.indices(pipeline.shape)
    core = (abs(xx - target_xy[0]) <= 1.5) & (abs(yy - target_xy[1]) <= 1.5)
    masks = {"pipeline": pipeline, "target_core": core,
             "expanded": binary_dilation(pipeline), "background": ~binary_dilation(pipeline, iterations=2)}
    photometry = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        # np.sum intentionally preserves missing aperture pixels as missing data.
        series = np.sum(pixels.flux[:, mask], axis=1)
        base, depth, sigma, _ = local_difference(pixels.time, series, inside, outside, center)
        photometry[name] = {"pixels": int(mask.sum()), "depth_relative_flux": float(depth / base) if base > 0 else None,
                            "depth_snr_white": float(depth / sigma) if sigma > 0 else None}
    snr = np.divide(difference, error, out=np.full_like(difference, np.nan), where=error > 0)
    # Thresholding suppresses a centroid driven by many positive noise pixels.
    support = (snr >= 3) & (difference > 0)
    centroid = _center(np.where(support, difference, 0))
    sigma_xy = None
    offset = None
    if centroid is not None:
        rng = np.random.default_rng(seed)
        centers = [_center(np.where(support, difference + rng.normal(size=error.shape)
                                     * np.nan_to_num(error), 0)) for _ in range(128)]
        centers = np.asarray([c for c in centers if c is not None])
        if len(centers) >= 16:
            sigma_xy = float(np.sqrt(np.var(centers, axis=0, ddof=1).sum()))
        offset = float(np.linalg.norm(np.asarray(centroid) - target_xy))
    record = {"status": "complete", "start_btjd": start, "end_btjd": end, "center_btjd": center,
              "cadences": {"inside": int(inside.sum()), "outside": int(outside.sum()),
                            "left": int((outside & (pixels.time < center)).sum()),
                            "right": int((outside & (pixels.time > center)).sum())},
              "photometry": photometry,
              "localization": {"target_wcs_xy": target_xy, "difference_xy": centroid,
                  "offset_pixels": offset, "centroid_noise_sigma_pixels": sigma_xy,
                  "peak_pixel_snr_white": float(np.nanmax(snr)) if np.isfinite(snr).any() else None},
              "uncertainty": "Independent-cadence residual scatter; centroid MC fixes the selected pixels. Neither accounts for red noise, WCS error, or selection bias."}
    return clean_json(record), {"reference": reference, "difference": difference, "error": error,
                               "pipeline_aperture": pipeline, "inside": inside, "outside": outside}


def gaia_query(ra, dec, radius_degrees, limit=2000):
    if not np.isfinite([ra, dec, radius_degrees]).all() or not (0 <= ra < 360 and -90 <= dec <= 90 and 0 < radius_degrees <= .25):
        raise ValidationError("Invalid bounded Gaia cone")
    return (f"SELECT TOP {limit + 1} source_id,ra,dec,ref_epoch,pmra,pmdec,phot_g_mean_mag,"
            "phot_bp_mean_mag,phot_rp_mean_mag,ruwe FROM gaiadr3.gaia_source "
            f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.10f},{dec:.10f},{radius_degrees:.10f}))")


def parse_gaia(payload, limit=2000):
    frame = pd.read_csv(io.BytesIO(payload), dtype={"source_id": str})
    required = {"source_id", "ra", "dec", "ref_epoch", "pmra", "pmdec", "phot_g_mean_mag"}
    if not required.issubset(frame.columns) or len(frame) > limit:
        raise ValidationError("Gaia schema mismatch or truncated cone")
    if frame.source_id.duplicated().any() or not frame.source_id.str.fullmatch(r"\d+").all():
        raise ValidationError("Invalid Gaia source IDs")
    return frame


def project_gaia(frame, wcs, epoch_btjd, shape, target_radec):
    result = []
    observation = Time(epoch_btjd + 2457000, format="jd", scale="tdb")
    for row in frame.to_dict("records"):
        coordinate = SkyCoord(row["ra"] * u.deg, row["dec"] * u.deg)
        moved = all(np.isfinite(row[key]) for key in ("pmra", "pmdec", "ref_epoch"))
        if moved:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                coordinate = SkyCoord(ra=row["ra"] * u.deg, dec=row["dec"] * u.deg,
                    pm_ra_cosdec=row["pmra"] * u.mas/u.yr, pm_dec=row["pmdec"] * u.mas/u.yr,
                    obstime=Time(row["ref_epoch"], format="jyear")).apply_space_motion(new_obstime=observation)
        x, y = wcs.world_to_pixel(coordinate)
        separation = coordinate.separation(SkyCoord(*target_radec, unit="deg")).arcsec
        result.append({**row, "pixel_x": float(x), "pixel_y": float(y),
                       "proper_motion_applied": moved, "target_separation_arcsec": float(separation),
                       "inside_stamp": bool(-.5 <= x < shape[1]-.5 and -.5 <= y < shape[0]-.5)})
    return clean_json(result)


def periodic_event_matches(start, end, searches):
    center, halfwidth = (start + end) / 2, (end - start) / 2
    matches = []
    for name, result in searches.items():
        if result.get("status") != "complete":
            continue
        for peak in result["peaks"]:
            distance = abs(float(phase_distance([center], peak["period_days"], peak["epoch_btjd"])[0]))
            if distance <= halfwidth + peak["duration_hours"] / 48:
                matches.append({"method": name, "period_days": peak["period_days"],
                                "epoch_distance_days": distance,
                                "strength": peak.get("sde", peak.get("depth_snr_white"))})
    return matches


def review_flags(pixel, gaia_status, matches):
    flags = []
    if pixel.get("status") != "complete":
        return ["pixel_diagnostic_unavailable"] + ([] if gaia_status == "complete" else ["gaia_unavailable"])
    depth = pixel["photometry"]["pipeline"]
    if depth["depth_relative_flux"] is None or depth["depth_snr_white"] is None:
        flags.append("aperture_depth_unavailable")
    elif depth["depth_relative_flux"] <= 0:
        flags.append("no_local_aperture_dimming")
    elif depth["depth_snr_white"] < 5:
        flags.append("weak_local_dimming")
    localization = pixel["localization"]
    if localization["difference_xy"] is None:
        flags.append("difference_source_unlocalized")
    elif localization["offset_pixels"] >= 1:
        flags.append("difference_source_offset_at_least_one_pixel")
    if gaia_status != "complete":
        flags.append("gaia_unavailable")
    if matches:
        flags.append("overlaps_periodic_search_ephemeris")
    return flags
