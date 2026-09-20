"""Common transit-preserving preprocessing of native Kepler and TESS photometry.

Readers retain each mission's cadence and header conventions. Everything after
reading uses the same functions and settings. Original v0 code is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import io
from pathlib import Path

import numpy as np
from astropy.io import fits

from scripts.data.kepler_pipeline_lib import compute_bls_features, fold_phase, robust_scale_series
from scripts.data.tess_preprocessing import (
    BJD_OFFSET, TessPrepConfig, _read_product, _coverage, _views, detrend_sector, transit_mask,
)

VERSION = "shared_v1"
KEYS = ("X_global", "X_local", "X_scalar", "X")


@dataclass(frozen=True)
class SharedConfig:
    global_bins: int = 200
    local_bins: int = 100
    global_window: float = .5
    local_window_mult: float = 4.
    detrend_window_days: float = 1.5
    bls_min_period: float = .5
    bls_max_period: float = 30.
    bls_grid_size: int = 2000
    gap_cadences: float = 5.
    min_usable_points: int = 200
    min_transit_events: int = 2
    min_transit_points: int = 3
    min_transit_fraction: float = .5
    baseline_min_points: int = 5
    preview_points: int = 0
    cadence_seconds: float = 120.


def read_kepler(path: Path, star_id: int):
    """Read a native long-cadence quarter, preserving quality and time metadata."""
    payload = path.read_bytes()
    if not payload or len(payload) % 2880:
        raise ValueError(f"Incomplete Kepler FITS blocks: {path}")
    with fits.open(io.BytesIO(payload), memmap=False) as hdus:
        hdus.verify("exception")
        primary, header, table = hdus[0].header, hdus[1].header, hdus[1].data
        def value(key, default=None):
            return header.get(key, primary.get(key, default))
        if int(primary.get("KEPLERID", -1)) != star_id or "long" not in str(value("OBSMODE", "")).lower():
            raise ValueError(f"Wrong Kepler star or cadence: {path}")
        if str(value("TIMESYS", "")).upper() != "TDB" or str(value("TIMEUNIT", "")).lower() != "d":
            raise ValueError(f"Invalid Kepler time system: {path}")
        if str(value("TIMEREF", "")).upper() != "SOLARSYSTEM":
            raise ValueError(f"Non-barycentric Kepler data: {path}")
        reference = float(value("BJDREFI")) + float(value("BJDREFF", 0))
        timezero, cadence = float(value("TIMEZERO", 0)), float(value("TIMEDEL")) * 86400
        if not np.isfinite([reference, timezero, cadence]).all() or reference <= 2_000_000 or abs(cadence - 1765.46) > 5:
            raise ValueError(f"Invalid Kepler timing/cadence: {path}")
        required = {"TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", "SAP_QUALITY"}
        if table is None or not required.issubset(hdus[1].columns.names):
            raise ValueError(f"Missing Kepler columns: {path}")
        time = np.asarray(table["TIME"], dtype=np.float64) + (reference - BJD_OFFSET) + timezero
        flux, error = (np.asarray(table[k], dtype=np.float64) for k in ("PDCSAP_FLUX", "PDCSAP_FLUX_ERR"))
        quality = np.asarray(table["SAP_QUALITY"])
        quarter = int(value("QUARTER"))
        valid = np.isfinite(time) & np.isfinite(flux) & np.isfinite(error) & (flux > 0) & (error > 0) & (quality == 0)
        time, flux = time[valid], flux[valid]
    order = np.argsort(time, kind="stable")
    time, flux = time[order], flux[order]
    unique = np.r_[True, np.diff(time) > 0] if len(time) else np.array([], dtype=bool)
    return time[unique], flux[unique], cadence, {
        "quarter": quarter, "cadence_seconds": cadence, "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(), "n_raw": len(valid),
        "n_quality_rejected": int((quality != 0).sum()), "n_after_quality": int(valid.sum()),
        "n_duplicate_times": int((~unique).sum()), "bjd_reference": reference,
    }


def ephemeris(row):
    period, epoch, hours = (float(row[k]) for k in ("period", "epoch_bjd", "duration_hours"))
    if not np.isfinite([period, epoch, hours]).all() or not (period > 0 and epoch > 2_000_000 and 0 < hours < 24 * period):
        raise ValueError("Missing or invalid companion ephemeris")
    return period, epoch - BJD_OFFSET, hours / 24


def candidate_features(time, flux, candidate, companions, cfg, bls):
    """Same companion masking, coverage, folding and feature functions for both missions."""
    target = ephemeris(candidate)
    mask = np.zeros(len(time), dtype=bool)
    for identifier, other in companions.items():
        if identifier != candidate["candidate_id"]:
            mask |= transit_mask(time, other)
    time, flux = time[~mask], flux[~mask]
    diagnostics = {"n_target_usable_points": len(time), "n_other_transit_masked": int(mask.sum()),
                   "n_known_companions": len(companions) - 1, "cadence_seconds": cfg.cadence_seconds,
                   "duration_in_cadences": target[2] * 86400 / cfg.cadence_seconds}
    diagnostics.update(_coverage(time, target, cfg))
    result = {"candidate_id": candidate["candidate_id"], "status": "rejected", "diagnostics": diagnostics}
    if len(time) < cfg.min_usable_points:
        result["reason"] = "too_few_usable_points"
    elif diagnostics["n_covered_transit_events"] < cfg.min_transit_events:
        result["reason"] = "insufficient_sampled_transit_events"
    else:
        arrays, half_window = _views(time, flux, target, bls, cfg)
        phase, folded_flux = fold_phase(time, flux, target[0], target[1])
        result.update(status="accepted", reason="accepted", arrays=arrays,
                      folded={"phase": phase.astype(np.float32), "flux": robust_scale_series(folded_flux),
                              "relative_flux": folded_flux.astype(np.float32), "period": np.asarray(target[0]),
                              "epoch_bjd": np.asarray(candidate["epoch_bjd"]),
                              "duration_hours": np.asarray(candidate["duration_hours"])})
        diagnostics["local_half_window"] = half_window
    return result


def prepare_shared_star(base, mission, star_id, products, candidates, companion_rows, cfg):
    known = {row["candidate_id"]: row for row in companion_rows}
    known.update({row["candidate_id"]: row for row in candidates})
    try:
        companions = {identifier: ephemeris(row) for identifier, row in known.items()}
    except (TypeError, ValueError, KeyError):
        return [{"candidate_id": c["candidate_id"], "status": "rejected",
                 "reason": "companion_missing_or_invalid_ephemeris", "diagnostics": {}} for c in candidates], {}, []
    if not products:
        return [{"candidate_id": c["candidate_id"], "status": "rejected",
                 "reason": "no_native_lightcurves", "diagnostics": {}} for c in candidates], {}, []
    segments, diagnostics, cadences = [], [], []
    for product in products:
        path = Path(base) / product["path"]
        if mission == "kepler":
            time, flux, cadence, info = read_kepler(path, star_id)
        elif mission == "tess":
            time, flux, info = _read_product(Path(base) / "data/raw/tess", product, TessPrepConfig())
            cadence = 120.
        else:
            raise ValueError("Unknown mission")
        local = replace(cfg, cadence_seconds=cadence)
        time, flux, details = detrend_sector(time, flux, list(companions.values()), local)
        info.update(details, path=product["path"])
        diagnostics.append(info)
        segments.append((time, flux)); cadences.append(cadence)
    time = np.concatenate([part[0] for part in segments])
    flux = np.concatenate([part[1] for part in segments])
    order = np.argsort(time, kind="stable")
    time, flux = time[order], flux[order]
    unique = np.r_[True, np.diff(time) > 0] if len(time) else np.array([], dtype=bool)
    time, flux = time[unique], flux[unique]
    native = replace(cfg, cadence_seconds=float(np.median(cadences)))
    # BLS remains star-level context and is computed once, with all known dips retained.
    bls = compute_bls_features(time, flux, native)
    results = [candidate_features(time, flux, row, companions, native, bls) for row in candidates]
    return results, bls, diagnostics
