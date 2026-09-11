"""Read-only TESS preprocessing with Kepler v0 model feature conventions.

`tess_v0` shares geometry and feature functions with Kepler v0, but deliberately
uses transit-protected, sector/gap-local detrending and conservative TESS QC.
Coverage below measures sampling at catalog ephemerides, never signal detection.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from astropy.io import fits

try:  # Both package import and execution via a script in scripts/data work.
    from .kepler_pipeline_lib import (
        bin_curve_stats, compute_bls_features, engineered_features,
        fold_phase, robust_scale_series,
    )
except ImportError:
    from kepler_pipeline_lib import (
        bin_curve_stats, compute_bls_features, engineered_features,
        fold_phase, robust_scale_series,
    )

PREPROCESS_VERSION = "tess_v0"
BJD_OFFSET = 2457000.0
SCALAR_NAMES = ("depth", "symmetry", "odd_even", "bls_snr", "bls_depth", "bls_duration", "bls_period")


@dataclass(frozen=True)
class TessPrepConfig:
    global_bins: int = 200
    local_bins: int = 100
    global_window: float = 0.5
    local_window_mult: float = 4.0
    detrend_window_days: float = 1.5
    bls_min_period: float = 0.5
    bls_max_period: float = 30.0
    bls_grid_size: int = 2000
    cadence_seconds: float = 120.0
    cadence_tolerance_seconds: float = 1.0
    gap_cadences: float = 5.0
    min_usable_points: int = 200
    min_transit_events: int = 2
    min_transit_points: int = 3
    min_transit_fraction: float = 0.5
    baseline_min_points: int = 5
    preview_points: int = 0

    def __post_init__(self):
        if (self.global_bins, self.local_bins) != (200, 100):
            raise ValueError("TESS transfer inputs require global_bins=200 and local_bins=100")
        if not (0 < self.global_window <= 0.5 and self.local_window_mult > 0
                and self.detrend_window_days > 0 and self.bls_grid_size >= 2
                and 0 < self.bls_min_period < self.bls_max_period
                and self.cadence_seconds == 120.0 and self.cadence_tolerance_seconds > 0
                and self.gap_cadences > 1 and self.min_usable_points >= 200
                and self.min_transit_events >= 2 and self.min_transit_points >= 3
                and 0.5 <= self.min_transit_fraction <= 1 and self.baseline_min_points >= 3
                and self.preview_points >= 0):
            raise ValueError("Invalid TESS preprocessing configuration")


class InputValidationError(ValueError):
    """A receipt, FITS identity, or timing contract could not be verified."""


def _first(record, *keys):
    for key in keys:
        if key in record:
            return record[key]
    raise ValueError("missing_" + keys[0])


def _candidate_id(record):
    return str(record.get("candidate_id", record.get("toidisplay", record.get("toi", "unknown"))))


def _ephemeris(record):
    period = float(_first(record, "period", "period_days", "pl_orbper"))
    epoch = float(_first(record, "epoch_bjd", "pl_tranmid"))
    duration = float(_first(record, "duration_hours", "pl_trandurh")) / 24.0
    if not (np.isfinite([period, epoch, duration]).all()
            and period > 0 and epoch > 2_000_000 and 0 < duration < period):
        raise ValueError("invalid_ephemeris")
    return period, epoch - BJD_OFFSET, duration


def transit_mask(time, ephemeris):
    """Catalog's nominal full-duration window; no period-based depth inference."""
    period, epoch, duration = ephemeris
    delta = ((np.asarray(time) - epoch + 0.5 * period) % period) - 0.5 * period
    return np.abs(delta) <= duration / 2.0 + 1e-10


def _read_product(raw_root, product, cfg):
    """Hash an immutable byte snapshot, then interpret those same FITS bytes."""
    root = Path(raw_root).resolve()
    relative = Path(product["relative_path"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise InputValidationError("product_path_outside_raw_root")
    filename = str(product.get("filename", relative.name))
    if filename != relative.name:
        raise InputValidationError("product_filename_mismatch")
    receipt_path = root / "metadata" / "receipts" / (filename + ".json")
    receipt = json.loads(receipt_path.read_text())
    payload = path.read_bytes()
    size = len(payload)
    digest = hashlib.sha256(payload).hexdigest()
    if (receipt.get("relative_path") != str(relative)
            or (product.get("data_uri") is not None and receipt.get("data_uri") != product["data_uri"])
            or receipt.get("size_bytes") != size or receipt.get("sha256") != digest
            or ("size_bytes" in product and int(product["size_bytes"]) != size)
            or ("sha256" in product and product["sha256"] != digest)):
        raise InputValidationError("receipt_integrity_mismatch")
    if size == 0 or size % 2880:
        raise InputValidationError("incomplete_fits_blocks")

    with warnings.catch_warnings():
        warnings.simplefilter("error", fits.verify.VerifyWarning)
        with fits.open(io.BytesIO(payload), mode="readonly", memmap=False) as hdus:
            hdus.verify("exception")
            if len(hdus) < 2 or not hasattr(hdus[1], "columns"):
                raise InputValidationError("missing_lightcurve_table")
            primary, header = hdus[0].header, hdus[1].header
            for key, expected in (("TICID", int(product["tic_id"])), ("SECTOR", int(product["sector"]))):
                if int(primary.get(key, -1)) != expected or (key in header and int(header[key]) != expected):
                    raise InputValidationError("fits_identity_mismatch")
            required = {"TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", "QUALITY"}
            if not required.issubset(hdus[1].columns.names):
                raise InputValidationError("missing_required_columns")
            def value(key, default=None):
                return header.get(key, primary.get(key, default))
            if str(value("TIMESYS", "")).upper() != "TDB":
                raise InputValidationError("time_system_not_tdb")
            if str(value("TIMEUNIT", "")).lower() not in {"d", "day", "days"}:
                raise InputValidationError("time_unit_not_days")
            if value("TIMEREF") is not None and str(value("TIMEREF")).upper() != "SOLARSYSTEM":
                raise InputValidationError("time_reference_not_barycentric")
            reference = float(value("BJDREFI", value("BJDREF", np.nan))) + float(value("BJDREFF", 0))
            timezero = float(value("TIMEZERO", 0))
            if not (np.isfinite(reference) and reference > 2_000_000 and np.isfinite(timezero)):
                raise InputValidationError("invalid_bjd_reference")
            header_cadence = value("TIMEDEL")
            if header_cadence is not None and (
                not np.isfinite(float(header_cadence))
                or abs(float(header_cadence) * 86400 - cfg.cadence_seconds) > cfg.cadence_tolerance_seconds
            ):
                raise InputValidationError("header_cadence_not_120_seconds")
            table = hdus[1].data
            if table is None or len(table) == 0:
                raise InputValidationError("empty_lightcurve_table")
            # Subtract reference offsets before addition to retain subcadence precision.
            time = np.array(table["TIME"], dtype=np.float64) + (reference - BJD_OFFSET) + timezero
            flux = np.array(table["PDCSAP_FLUX"], dtype=np.float64)
            error = np.array(table["PDCSAP_FLUX_ERR"], dtype=np.float64)
            quality = np.array(table["QUALITY"])
    finite_times = np.unique(time[np.isfinite(time)])
    cadence = float(np.median(np.diff(finite_times)) * 86400) if len(finite_times) > 1 else None
    if cadence is not None and abs(cadence - cfg.cadence_seconds) > cfg.cadence_tolerance_seconds:
        raise InputValidationError("measured_cadence_not_120_seconds")
    valid = (np.isfinite(time) & np.isfinite(flux) & np.isfinite(error)
             & (flux > 0) & (error > 0) & (quality == 0))
    kept_time, kept_flux = time[valid], flux[valid]
    order = np.argsort(kept_time, kind="stable")
    kept_time, kept_flux = kept_time[order], kept_flux[order]
    unique = np.r_[True, np.diff(kept_time) > 0] if len(kept_time) else np.array([], dtype=bool)
    diagnostics = {
        "relative_path": str(relative), "sector": int(product["sector"]), "size_bytes": size,
        "sha256": digest, "n_raw": len(time), "n_quality_rejected": int((quality != 0).sum()),
        "n_invalid_samples": int((~(np.isfinite(time) & np.isfinite(flux) & np.isfinite(error)
                                     & (flux > 0) & (error > 0))).sum()),
        "n_after_quality": int(valid.sum()), "n_duplicate_times": int((~unique).sum()),
        "measured_cadence_seconds": cadence, "bjd_reference": reference,
        "timezero_days": timezero, "timesys": "TDB", "timeunit": "d",
    }
    return kept_time[unique], kept_flux[unique], diagnostics


def detrend_sector(time, flux, ephemerides, cfg):
    """Exclude every known transit from a rolling median in each gap segment.

    No flux sample is clipped or synthesized. Where too few out-of-transit
    samples support a trend, discard the sample rather than invent a baseline.
    """
    time, flux = np.asarray(time, dtype=np.float64), np.asarray(flux, dtype=np.float64)
    protected = np.zeros(len(time), dtype=bool)
    for ephemeris in ephemerides:
        protected |= transit_mask(time, ephemeris)
    boundaries = np.r_[0, np.flatnonzero(np.diff(time) > cfg.gap_cadences * cfg.cadence_seconds / 86400) + 1, len(time)]
    trend = np.full(len(time), np.nan, dtype=np.float64)
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        if stop - start < cfg.baseline_min_points:
            continue
        values = flux[start:stop].copy()
        values[protected[start:stop]] = np.nan
        index = pd.to_timedelta(time[start:stop] - time[start], unit="D")
        trend[start:stop] = pd.Series(values, index=index).rolling(
            pd.Timedelta(days=cfg.detrend_window_days), center=True,
            min_periods=cfg.baseline_min_points,
        ).median().to_numpy()
    supported = np.isfinite(trend) & (trend > 0)
    corrected = flux[supported] / trend[supported]
    finite = np.isfinite(corrected) & (corrected > 0)
    diagnostics = {
        "n_segments": int(max(len(boundaries) - 1, 0)) if len(time) else 0,
        "n_protected_baseline_samples": int(protected.sum()),
        "n_unsupported_baseline_samples": int((~supported).sum()),
        "n_after_detrending": int(finite.sum()),
    }
    return time[supported][finite], corrected[finite], diagnostics


def _coverage(time, ephemeris, cfg):
    period, epoch, duration = ephemeris
    in_transit = transit_mask(time, ephemeris)
    cycles = np.floor((time[in_transit] - epoch) / period + 0.5).astype(np.int64)
    events, counts = np.unique(cycles, return_counts=True)
    minimum = max(cfg.min_transit_points, math.ceil(cfg.min_transit_fraction * duration * 86400 / cfg.cadence_seconds - 1e-10))
    qualified = counts >= minimum
    return {
        "coverage_interpretation": "sampling_at_catalog_ephemeris_only_not_signal_detection",
        "required_points_per_event": minimum, "required_transit_events": cfg.min_transit_events,
        "n_in_transit_points": int(in_transit.sum()), "n_sampled_transit_events": int(len(events)),
        "n_covered_transit_events": int(qualified.sum()),
        "transit_event_numbers": events.tolist(), "transit_event_point_counts": counts.tolist(),
    }


def _views(time, flux, ephemeris, bls, cfg):
    period, epoch, duration = ephemeris
    phase, folded_flux = fold_phase(time, flux, period, epoch)
    scaled = robust_scale_series(folded_flux)
    half_window = min(0.25, cfg.local_window_mult * duration / period)
    g = bin_curve_stats(phase, scaled, cfg.global_bins, -cfg.global_window, cfg.global_window)
    local = bin_curve_stats(phase, scaled, cfg.local_bins, -half_window, half_window)
    engineered = engineered_features(g[0], local[0])
    bls_values = np.asarray([bls[key] for key in SCALAR_NAMES[3:]], dtype=np.float32)
    scalar = np.concatenate([engineered, bls_values]).astype(np.float32)
    # The source flat representation is channel-major, not channels.reshape(-1).
    arrays = {
        "X_global": np.stack(g, axis=-1).astype(np.float32),
        "X_local": np.stack(local, axis=-1).astype(np.float32),
        "X_scalar": scalar,
        "X": np.concatenate([*g, *local, scalar]).astype(np.float32),
    }
    if not all(np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("nonfinite_model_features")
    if cfg.preview_points:
        index = np.linspace(0, len(phase) - 1, min(cfg.preview_points, len(phase)), dtype=int)
        arrays["preview_phase"] = phase[index]
        arrays["preview_flux"] = folded_flux[index]
        time_index = np.linspace(0, len(time) - 1, min(cfg.preview_points, len(time)), dtype=int)
        arrays["preview_time_btjd"] = time[time_index].astype(np.float64)
        arrays["preview_time_flux"] = flux[time_index].astype(np.float32)
    return arrays, half_window


def prepare_star(raw_root: Path, products: list[dict], candidates: list[dict],
                 companions: list[dict], cfg: TessPrepConfig) -> list[dict]:
    """Return one accepted/rejected result per candidate; never write raw inputs.

    Product receipt/hash/identity/timing failures reject the star with an audit
    reason. All catalog companions, including unknown or excluded dispositions,
    must have valid ephemerides. Other companions' nominal transits are removed
    before target folding, including overlapping target events. BLS is computed
    once on the shared detrended star series and therefore is star-level context.
    """
    common = {"preprocessing_version": PREPROCESS_VERSION,
              "bls_scope": "star_level_all_known_transits_preserved",
              "baseline_policy": "all_known_transit_windows_excluded_sector_and_gap_local_rolling_median",
              "quality_policy": "QUALITY==0_finite_positive_flux_and_error",
              "time_coordinate": "BJD_TDB_minus_2457000", "products": []}
    def reject_all(reason):
        return [{"candidate_id": _candidate_id(row), "status": "rejected", "reason": reason,
                 "diagnostics": dict(common)} for row in candidates]
    if not candidates:
        return []
    try:
        tic_id = int(_first(candidates[0], "tic_id", "tid"))
        if any(int(_first(row, "tic_id", "tid")) != tic_id for row in [*candidates, *companions]):
            return reject_all("mixed_star_candidates")
        known = {_candidate_id(row): row for row in companions}
        known.update({_candidate_id(row): row for row in candidates})
        ephemerides = {}
        for identifier, row in known.items():
            try:
                ephemerides[identifier] = _ephemeris(row)
            except (KeyError, TypeError, ValueError, OverflowError):
                common["invalid_companion_id"] = identifier
                return reject_all("companion_missing_or_invalid_ephemeris")
        if not products:
            return reject_all("no_lightcurve_products")
        if any(int(product["tic_id"]) != tic_id for product in products):
            return reject_all("product_tic_mismatch")
        seen = set()
        sector_data = []
        for product in sorted(products, key=lambda p: (int(p["sector"]), p["relative_path"])):
            if product["relative_path"] in seen:
                continue
            seen.add(product["relative_path"])
            try:
                time, flux, diagnostics = _read_product(raw_root, product, cfg)
            except (OSError, KeyError, TypeError, ValueError, OverflowError, fits.verify.VerifyError) as exc:
                common["failed_product"] = product["relative_path"]
                common["input_error"] = f"{type(exc).__name__}:{exc}"
                return reject_all("invalid_raw_product")
            time, flux, detrend_info = detrend_sector(time, flux, list(ephemerides.values()), cfg)
            diagnostics.update(detrend_info)
            common["products"].append(diagnostics)
            sector_data.append((time, flux))
        time = np.concatenate([item[0] for item in sector_data])
        flux = np.concatenate([item[1] for item in sector_data])
        order = np.argsort(time, kind="stable")
        time, flux = time[order], flux[order]
        unique = np.r_[True, np.diff(time) > 0] if len(time) else np.array([], dtype=bool)
        common["n_overlapping_product_samples"] = int((~unique).sum())
        time, flux = time[unique], flux[unique]
        common["n_star_usable_points"] = len(time)
        if len(time) < cfg.min_usable_points:
            return reject_all("too_few_usable_points")
        common["time_min_btjd"] = float(time[0])
        common["time_max_btjd"] = float(time[-1])
        common["constant_flux"] = bool(np.ptp(flux) < 1e-12)

        results, pending = [], []
        for row in candidates:
            identifier = _candidate_id(row)
            other_mask = np.zeros(len(time), dtype=bool)
            for other_id, ephemeris in ephemerides.items():
                if other_id != identifier:
                    other_mask |= transit_mask(time, ephemeris)
            target_time, target_flux = time[~other_mask], flux[~other_mask]
            diagnostics = dict(common)
            diagnostics.update({"n_other_transit_masked": int(other_mask.sum()),
                                "n_target_usable_points": len(target_time),
                                "n_known_companions": len(ephemerides) - 1,
                                "epoch_btjd": ephemerides[identifier][1],
                                "duration_phase": ephemerides[identifier][2] / ephemerides[identifier][0]})
            diagnostics.update(_coverage(target_time, ephemerides[identifier], cfg))
            reason = ("too_few_usable_points_after_companion_mask" if len(target_time) < cfg.min_usable_points
                      else "insufficient_sampled_transit_events" if diagnostics["n_covered_transit_events"] < cfg.min_transit_events
                      else "accepted")
            result = {"candidate_id": identifier, "status": "accepted" if reason == "accepted" else "rejected",
                      "reason": reason, "diagnostics": diagnostics}
            results.append(result)
            if reason == "accepted":
                pending.append((result, target_time, target_flux, ephemerides[identifier]))
        if pending:
            bls = compute_bls_features(time, flux, cfg)
            for result, target_time, target_flux, ephemeris in pending:
                arrays, half_window = _views(target_time, target_flux, ephemeris, bls, cfg)
                result.update(arrays)
                result["diagnostics"].update({"bls": bls, "local_half_window": half_window})
        return results
    except (KeyError, TypeError, ValueError, OverflowError, RuntimeError) as exc:
        common["processing_error"] = f"{type(exc).__name__}:{exc}"
        return reject_all("preprocessing_error")
