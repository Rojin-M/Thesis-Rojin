"""Validated TESS target-pixel loading, aperture photometry and difference images."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Optional
import warnings

from astropy.io import fits
import numpy as np
from scipy.ndimage import binary_dilation

from .detection import phase_distance
from .lightcurves import _ones_complement
from .protocol import TIME_OFFSETS, ValidationError

VERSION = "tess_pixel_diagnostics_v1"
TPF_NAME = re.compile(r"tess\d{13}-s(\d{4})-(\d{16})-(\d{4})-s_tp\.fits")
LC_NAME = re.compile(r"tess\d{13}-s(\d{4})-(\d{16})-(\d{4})-s_lc\.fits")
MAX_TPF_BYTES = 320 * 1024 ** 2
MAX_CADENCES = 250_000
MAX_PIXELS = 2_500


@dataclass
class TargetPixels:
    time: np.ndarray
    flux: np.ndarray
    quality: np.ndarray
    aperture: np.ndarray
    target_id: str
    sector: int
    sha256: str
    path: str
    position_correction: Optional[np.ndarray] = None
    background_flux: Optional[np.ndarray] = None
    context: Optional[dict] = None


def target_pixel_product(lightcurve_path):
    """Return the deterministic public SPOC TPF filename, URI and cloud URL."""
    name = Path(lightcurve_path).name
    match = LC_NAME.fullmatch(name)
    if not match:
        raise ValidationError("Expected a standard SPOC TESS light-curve filename")
    tpf_name = name.removesuffix("_lc.fits") + "_tp.fits"
    groups = "/".join(match[2][i:i + 4] for i in range(0, 16, 4))
    return {"filename": tpf_name, "sector": int(match[1]), "tic_id": str(int(match[2])),
            "data_uri": "mast:TESS/product/" + tpf_name,
            "url": f"https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/s{match[1]}/{groups}/{tpf_name}"}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_target_pixels(path, target_id):
    path = Path(path).resolve()
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_TPF_BYTES or not TPF_NAME.fullmatch(path.name):
        raise ValidationError("Target-pixel source must be a standard SPOC TPF of at most 320 MiB")
    with fits.open(path, memmap=False, checksum=False) as hdus:
        hdus.verify("exception")
        # Mission products commonly carry CHECKSUM without DATASUM. Astropy
        # warns on those valid files, so verify each serialized HDU directly.
        with path.open("rb") as raw:
            for hdu in hdus:
                info = hdu.fileinfo()
                end = info["datLoc"] + info["datSpan"]
                raw.seek(info["hdrLoc"])
                block = raw.read(end - info["hdrLoc"])
                if len(block) != end - info["hdrLoc"]:
                    raise ValidationError("Truncated target-pixel FITS block")
                if "CHECKSUM" in hdu.header and _ones_complement(block) != 0xffffffff:
                    raise ValidationError("Target-pixel FITS CHECKSUM failed")
                if "DATASUM" in hdu.header:
                    offset = info["datLoc"] - info["hdrLoc"]
                    if _ones_complement(block[offset:]) != int(hdu.header["DATASUM"]):
                        raise ValidationError("Target-pixel FITS DATASUM failed")
        if len(hdus) < 3 or hdus[1].data is None or hdus[2].data is None:
            raise ValidationError("Target-pixel FITS requires PIXELS and APERTURE extensions")
        primary, table_header, data = hdus[0].header, hdus[1].header, hdus[1].data
        value = lambda key, default=None: table_header.get(key, primary.get(key, default))
        if str(value("TICID", "")) != str(target_id):
            raise ValidationError("Target-pixel identity differs from requested TIC")
        if str(value("TIMESYS", "")).upper() != "TDB" or str(value("TIMEREF", "")).upper() != "SOLARSYSTEM":
            raise ValidationError("Target pixels require barycentric TDB times")
        required = {"TIME", "FLUX", "QUALITY"}
        if not required.issubset(hdus[1].columns.names):
            raise ValidationError("Target-pixel table is missing TIME, FLUX or QUALITY")
        time = np.asarray(data["TIME"], dtype=np.float64)
        flux = np.asarray(data["FLUX"], dtype=np.float64)
        quality = np.asarray(data["QUALITY"], dtype=np.int64)
        aperture = np.asarray(hdus[2].data, dtype=np.int16)
        if (time.ndim != 1 or flux.ndim != 3 or flux.shape[0] != len(time)
                or quality.shape != time.shape or aperture.shape != flux.shape[1:]
                or len(time) > MAX_CADENCES or aperture.size > MAX_PIXELS):
            raise ValidationError("Target-pixel arrays exceed shape bounds or are misaligned")
        reference = float(value("BJDREFI", value("BJDREF", np.nan))) + float(value("BJDREFF", 0))
        timezero = float(value("TIMEZERO", 0))
        if not np.isfinite([reference, timezero]).all():
            raise ValidationError("Invalid target-pixel time reference")
        time = time + reference - TIME_OFFSETS["BTJD"] + timezero
        sector = int(value("SECTOR"))
        position = None
        if {"POS_CORR1", "POS_CORR2"}.issubset(hdus[1].columns.names):
            position = np.column_stack([
                np.asarray(data["POS_CORR1"], dtype=np.float32),
                np.asarray(data["POS_CORR2"], dtype=np.float32),
            ])
            if position.shape != (len(time), 2):
                raise ValidationError("Target-pixel position corrections are misaligned")
        background = None
        if "FLUX_BKG" in hdus[1].columns.names:
            background_cube = np.asarray(data["FLUX_BKG"], dtype=np.float32)
            if background_cube.shape != flux.shape:
                raise ValidationError("Target-pixel background flux is misaligned")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                background = np.nanmedian(background_cube, axis=(1, 2)).astype(np.float32)
        context_keys = ("TESSMAG", "TEFF", "LOGG", "MH", "RADIUS", "PMRA", "PMDEC",
                        "RA_OBJ", "DEC_OBJ", "SECTOR", "CAMERA", "CCD", "CROWDSAP", "FLFRCSAP")
        context = {key: value(key) for key in context_keys}
    return TargetPixels(time, flux, quality, aperture, str(target_id), sector, _sha256(path), str(path),
                        position, background, context)


def _centroid(image, mask=None):
    values = np.asarray(image, float)
    if mask is not None:
        values = np.where(mask, values, np.nan)
    floor = np.nanpercentile(values, 20)
    weight = np.clip(values - floor, 0, None)
    weight[~np.isfinite(weight)] = 0
    if weight.sum() <= 0:
        return (None, None)
    yy, xx = np.indices(weight.shape)
    return (float((xx * weight).sum() / weight.sum()), float((yy * weight).sum() / weight.sum()))


def _robust_error(values):
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return None
    sigma = 1.4826 * np.median(np.abs(values - np.median(values)))
    return float(sigma / math.sqrt(len(values)))


def _aperture_depth(cube, inside, outside, mask):
    series = np.nansum(cube[:, mask], axis=1)
    baseline = float(np.nanmedian(series[outside]))
    event = float(np.nanmedian(series[inside]))
    error_parts = (_robust_error(series[inside]), _robust_error(series[outside]))
    error = math.hypot(*error_parts) / baseline if all(x is not None for x in error_parts) and baseline > 0 else None
    depth = (baseline - event) / baseline if baseline > 0 else None
    return {"pixels": int(mask.sum()), "depth_relative_flux": depth, "depth_error": error,
            "depth_snr": depth / error if depth is not None and error and error > 0 else None}


def difference_image_diagnostics(pixels: TargetPixels, ephemeris, *, seed=92027):
    period = float(ephemeris["period_days"])
    epoch = float(ephemeris["epoch_btjd"])
    duration = float(ephemeris["duration_hours"]) / 24
    if not np.isfinite([period, epoch, duration]).all() or period <= 0 or duration <= 0 or duration >= period / 2:
        raise ValidationError("Invalid ephemeris for pixel diagnostics")
    finite_time = np.isfinite(pixels.time) & (pixels.quality == 0)
    phase = phase_distance(pixels.time, period, epoch)
    inside = finite_time & (np.abs(phase) <= duration / 2)
    outside = finite_time & (np.abs(phase) >= duration) & (np.abs(phase) <= min(3 * duration, .45 * period))
    if inside.sum() < 5 or outside.sum() < 15:
        raise ValidationError("Insufficient in/out-of-transit target-pixel cadences")
    cube = pixels.flux
    reference = np.nanmedian(cube[outside], axis=0)
    event = np.nanmedian(cube[inside], axis=0)
    difference = reference - event
    in_error = np.nanstd(cube[inside], axis=0, ddof=1) / math.sqrt(int(inside.sum()))
    out_error = np.nanstd(cube[outside], axis=0, ddof=1) / math.sqrt(int(outside.sum()))
    uncertainty = np.hypot(in_error, out_error)
    pipeline = (pixels.aperture & 2) != 0
    if not pipeline.any():
        pipeline = pixels.aperture > 0
    if not pipeline.any():
        raise ValidationError("SPOC target-pixel product has no pipeline aperture")
    ref_centroid = _centroid(reference, binary_dilation(pipeline, iterations=1))
    positive = np.clip(difference, 0, None)
    diff_centroid = _centroid(positive)
    if None in ref_centroid or None in diff_centroid:
        raise ValidationError("Difference-image centroid is undefined")
    offset = math.hypot(diff_centroid[0] - ref_centroid[0], diff_centroid[1] - ref_centroid[1])
    rng = np.random.default_rng(seed)
    simulations = []
    valid_error = np.where(np.isfinite(uncertainty), uncertainty, 0)
    for _ in range(128):
        simulated = np.clip(difference + rng.normal(size=difference.shape) * valid_error, 0, None)
        center = _centroid(simulated)
        if None not in center:
            simulations.append(center)
    if len(simulations) >= 16:
        scatter = np.asarray(simulations)
        centroid_sigma = float(np.sqrt(np.var(scatter[:, 0], ddof=1) + np.var(scatter[:, 1], ddof=1)))
    else:
        centroid_sigma = None
    yy, xx = np.unravel_index(int(np.nanargmax(np.where(np.isfinite(positive), positive, -np.inf))), positive.shape)
    brightest = np.unravel_index(int(np.nanargmax(np.where(np.isfinite(reference), reference, -np.inf))), reference.shape)
    core = np.zeros_like(pipeline)
    y0, x0 = brightest
    core[max(0, y0 - 1):y0 + 2, max(0, x0 - 1):x0 + 2] = True
    expanded = binary_dilation(pipeline, iterations=1)
    background = ~binary_dilation(pipeline, iterations=2)
    apertures = {"core_3x3": core, "pipeline": pipeline, "expanded": expanded}
    depths = {name: _aperture_depth(cube, inside, outside, mask) for name, mask in apertures.items()}
    if background.any():
        depths["background"] = _aperture_depth(cube, inside, outside, background)
    good_depths = [row["depth_relative_flux"] for name, row in depths.items()
                   if name != "background" and row["depth_relative_flux"] is not None]
    depth_cv = float(np.std(good_depths) / max(abs(np.mean(good_depths)), 1e-12)) if good_depths else None
    total_positive = float(np.nansum(positive))
    peak_snr = float(difference[yy, xx] / uncertainty[yy, xx]) if uncertainty[yy, xx] > 0 else None
    return {
        "version": VERSION, "target_id": pixels.target_id, "sector": pixels.sector,
        "ephemeris": {"period_days": period, "epoch_btjd": epoch, "duration_hours": duration * 24},
        "cadences": {"quality_zero": int(finite_time.sum()), "in_transit": int(inside.sum()),
                     "nearby_out_of_transit": int(outside.sum())},
        "source_localization": {"reference_centroid_xy": ref_centroid, "difference_centroid_xy": diff_centroid,
            "offset_pixels": offset, "centroid_noise_sigma_pixels": centroid_sigma,
            "offset_sigma_approximate": offset / centroid_sigma if centroid_sigma and centroid_sigma > 0 else None,
            "peak_difference_pixel_yx": [int(yy), int(xx)], "peak_difference_snr": peak_snr,
            "positive_flux_concentration": float(positive[yy, xx] / total_positive) if total_positive > 0 else None},
        "aperture_photometry": depths,
        "aperture_depth_coefficient_of_variation": depth_cv,
        "maps": {"reference": reference, "event": event, "difference": difference,
                 "uncertainty": uncertainty, "pipeline_aperture": pipeline.astype(np.uint8)},
        "interpretation": "Diagnostic only; centroid uncertainty uses pixel-noise Monte Carlo and is not a calibrated false-positive probability",
    }
