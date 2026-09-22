"""Bounded, read-only light-curve adapters for blind search (no ephemerides).

Internal times are BTJD (BJD TDB - 2457000), including Kepler inputs. Native
headers, TIMEZERO, file identities, QC counts and byte hashes stay in receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
from astropy.io import fits

from .protocol import TIME_OFFSETS, ValidationError

MAX_FILE_BYTES = 64 * 1024 ** 2
MAX_INPUT_BYTES = 512 * 1024 ** 2
MAX_POINTS = 250000


def _ones_complement(payload):
    """FITS 32-bit big-endian one's-complement sum, including original padding.

    https://fits.gsfc.nasa.gov/registry/checksum.html. Reading raw bytes also
    handles mission CHECKSUM-only HDUs (Astropy 6 assumes DATASUM=0 otherwise).
    Bounded 64 MiB sources cannot overflow the uint64 accumulation.
    """
    total = int(np.frombuffer(payload, dtype=">u4").sum(dtype=np.uint64))
    while total >> 32:
        total = (total & 0xffffffff) + (total >> 32)
    return total


@dataclass
class LightCurve:
    time: np.ndarray
    flux: np.ndarray
    error: np.ndarray
    segment: np.ndarray
    sources: list
    metadata: dict


def snapshot_file(path):
    """Read and hash the exact bounded bytes that will be interpreted."""
    path = Path(path).resolve()
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValidationError("Light-curve source must be a regular file of 1 byte to 64 MiB")
    with path.open("rb") as handle:
        payload = handle.read(MAX_FILE_BYTES + 1)
    if not 0 < len(payload) <= MAX_FILE_BYTES:
        raise ValidationError("Source changed size or exceeds 64 MiB")
    return payload, {"path": str(path), "filename": path.name,
                     "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
                     "local_mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                     "original_retrieved_at": None, "source_uri": path.as_uri()}


def _fits(payload, mission, target_id):
    if len(payload) % 2880:
        raise ValidationError("Incomplete FITS blocks")
    with fits.open(io.BytesIO(payload), memmap=False) as hdus:
        hdus.verify("exception")
        # Check the original serialized bytes BEFORE accessing any table data;
        # Astropy may otherwise reconstruct a table and normalize its padding.
        checksum_receipts = []
        for hdu in hdus:
            info = hdu.fileinfo()
            end = info["datLoc"] + info["datSpan"]
            if end > len(payload):
                raise ValidationError("Truncated FITS data block")
            if "CHECKSUM" in hdu.header and _ones_complement(payload[info["hdrLoc"]:end]) != 0xffffffff:
                raise ValidationError("FITS CHECKSUM failed")
            if "DATASUM" in hdu.header and _ones_complement(payload[info["datLoc"]:end]) != int(hdu.header["DATASUM"]):
                raise ValidationError("FITS DATASUM failed")
            checksum_receipts.append({"checksum_present": "CHECKSUM" in hdu.header,
                                      "datasum_present": "DATASUM" in hdu.header, "verification": "original_bytes_ones_complement"})
        if len(hdus) < 2 or not isinstance(hdus[1], fits.BinTableHDU) or hdus[1].data is None:
            raise ValidationError("Missing light-curve FITS table; pixel photometry is not implemented")
        primary, header, data = hdus[0].header, hdus[1].header, hdus[1].data
        def value(key, default=None):
            return header.get(key, primary.get(key, default))
        identity_key, quality_key = ("TICID", "QUALITY") if mission == "TESS" else ("KEPLERID", "SAP_QUALITY")
        if str(value(identity_key, "")) != str(target_id):
            raise ValidationError("FITS target identity differs from requested target")
        if str(value("TIMESYS", "")).upper() != "TDB" or str(value("TIMEREF", "")).upper() != "SOLARSYSTEM":
            raise ValidationError("Require explicit barycentric TDB FITS times")
        if str(value("TIMEUNIT", "")).lower() not in ("d", "day", "days"):
            raise ValidationError("FITS time unit must be days")
        reference = float(value("BJDREFI", value("BJDREF", np.nan))) + float(value("BJDREFF", 0))
        timezero = float(value("TIMEZERO", 0))
        if not np.isfinite([reference, timezero]).all() or not 2000000 < reference < 3000000:
            raise ValidationError("Invalid BJD reference or TIMEZERO")
        required = ("TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", quality_key)
        if not set(required).issubset(hdus[1].columns.names):
            raise ValidationError("Require native PDCSAP flux, errors and quality flags")
        if len(data) > MAX_POINTS:
            raise ValidationError("Too many source samples for the bounded pilot")
        arrays = [np.array(data[key], dtype=np.float64) for key in required]
        arrays[0] += (reference - TIME_OFFSETS["BTJD"]) + timezero
        metadata = {"format": "FITS", "flux_column": "PDCSAP_FLUX", "quality_column": quality_key,
                    "bjd_reference": reference, "timezero_days": timezero, "timesys": "TDB",
                    "timeunit": "day", "sector": value("SECTOR"), "quarter": value("QUARTER"),
                    "data_release": value("DATA_REL"), "pipeline_version": value("PROCVER"),
                    "native_cadence_days": value("TIMEDEL"), "target_id": str(target_id), "fits_integrity": checksum_receipts}
    return arrays, metadata


def _table(payload, suffix, time_system):
    if time_system not in TIME_OFFSETS:
        raise ValidationError("NPZ/CSV inputs require --time-system BJD_TDB, BTJD or BKJD")
    if suffix == ".npz":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_FILE_BYTES:
                raise ValidationError("Expanded NPZ exceeds 64 MiB")
        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            if not {"time", "flux", "flux_err", "quality"}.issubset(data.files):
                raise ValidationError("NPZ requires time, flux, flux_err and quality arrays")
            arrays = [np.array(data[key], dtype=np.float64) for key in ("time", "flux", "flux_err", "quality")]
    elif suffix == ".csv":
        data = pd.read_csv(io.BytesIO(payload), nrows=MAX_POINTS + 1)
        if not {"time", "flux", "flux_err", "quality"}.issubset(data.columns):
            raise ValidationError("CSV requires time, flux, flux_err and quality columns")
        arrays = [data[key].to_numpy(dtype=np.float64) for key in ("time", "flux", "flux_err", "quality")]
    else:
        raise ValidationError("Supported local formats: FITS, NPZ, CSV")
    arrays[0] += TIME_OFFSETS[time_system] - TIME_OFFSETS["BTJD"]
    return arrays, {"format": suffix[1:].upper(), "input_time_system": time_system,
                    "identity_validation": "operator_asserted_no_native_header", "timesys": "TDB", "timeunit": "day"}


def read_lightcurves(paths, *, mission, target_id, time_system=None, expected_hashes=None):
    if mission not in ("TESS", "Kepler") or not str(target_id).strip():
        raise ValidationError("Explicit mission and target identity required")
    paths = sorted({str(Path(p).resolve()) for p in paths})
    if not 1 <= len(paths) <= 20 or sum(Path(p).stat().st_size for p in paths) > MAX_INPUT_BYTES:
        raise ValidationError("Select 1–20 local products totaling at most 512 MiB")
    pieces, sources, total = [], [], 0
    for number, path in enumerate(paths):
        payload, receipt = snapshot_file(path)
        if expected_hashes is not None and receipt["sha256"] != expected_hashes[path]:
            raise ValidationError("Source bytes changed since job registration; create a new job")
        if Path(path).suffix.lower() in (".fits", ".fit"):
            arrays, meta = _fits(payload, mission, target_id)
            # Preserve verified original TESS acquisition receipts when present.
            p = Path(path)
            receipt_path = p.parent.parent.parent / "metadata/receipts" / (p.name + ".json")
            if mission == "TESS" and receipt_path.is_file():
                old = json.loads(receipt_path.read_text())
                if old.get("sha256") != receipt["sha256"] or old.get("size_bytes") != len(payload):
                    raise ValidationError("Existing acquisition receipt does not match source bytes")
                receipt.update(acquisition_receipt=old, acquisition_receipt_path=str(receipt_path),
                               original_retrieved_at=old.get("downloaded_utc"), source_uri=old.get("data_uri", receipt["source_uri"]))
        else:
            arrays, meta = _table(payload, Path(path).suffix.lower(), time_system)
        if any(a.ndim != 1 or len(a) != len(arrays[0]) for a in arrays) or len(arrays[0]) > MAX_POINTS:
            raise ValidationError("Light-curve arrays must be aligned, one-dimensional and bounded")
        t, f, e, q = arrays
        valid = np.isfinite(t) & np.isfinite(f) & np.isfinite(e) & (f > 0) & (e > 0) & (q == 0)
        if np.any((t[valid] + TIME_OFFSETS["BTJD"] <= 2000000) | (t[valid] + TIME_OFFSETS["BTJD"] >= 3000000)):
            raise ValidationError("Times are not plausible BJD TDB after explicit conversion")
        receipt.update(meta, n_raw=len(t), n_quality_rejected=int(np.count_nonzero(q != 0)),
                       n_invalid_samples=int(np.count_nonzero(~(np.isfinite(t) & np.isfinite(f) & np.isfinite(e) & (f > 0) & (e > 0)))),
                       n_after_quality=int(valid.sum()), quality_policy="strict_zero", flux_clipping="none")
        total += int(valid.sum())
        if total > MAX_POINTS:
            raise ValidationError("Combined light curve exceeds 250000 usable samples; narrow the explicit selection")
        pieces.append((t[valid], f[valid], e[valid], np.full(valid.sum(), number, dtype=np.int32)))
        sources.append(receipt)
    columns = [np.concatenate([p[k] for p in pieces]) for k in range(4)]
    order = np.argsort(columns[0], kind="stable")
    columns = [a[order] for a in columns]
    unique = np.r_[True, np.diff(columns[0]) > 0] if len(columns[0]) else np.array([], bool)
    columns = [a[unique] for a in columns]
    if len(columns[0]) < 200:
        raise ValidationError("Fewer than 200 finite, positive-error, quality-zero samples")
    if columns[0][-1] - columns[0][0] > 400:
        raise ValidationError("The bounded pilot accepts at most 400 days of baseline per job")
    return LightCurve(*columns, sources=sources, metadata={"mission": mission, "target_id": str(target_id),
        "time_system": "BTJD", "canonical_epoch": "BJD_TDB", "n_duplicate_times": int((~unique).sum()),
        "duplicate_policy": "first_in_sorted_product_path_order", "n_usable": len(columns[0]),
        "new_scientific_download_bytes": 0})


def detrend(curve, window_days=1.5, gap_cadences=5.):
    """Blind gap/product-local rolling median, no catalog masking or clipping.

    Long/high-duty-cycle transits can be attenuated. This is measured in controls,
    not disguised as the transit-protected labelled-benchmark preprocessing.
    """
    t, f, e = curve.time, curve.flux, curve.error
    trend = np.full(len(t), np.nan)
    segments = 0
    for product in np.unique(curve.segment):
        idx = np.flatnonzero(curve.segment == product)
        cadence = np.median(np.diff(t[idx])) if len(idx) > 1 else np.nan
        boundaries = np.r_[0, np.flatnonzero(np.diff(t[idx]) > gap_cadences * cadence) + 1, len(idx)]
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            local = idx[start:stop]
            if len(local) < 15:
                continue
            index = pd.to_timedelta(t[local] - t[local[0]], unit="D")
            trend[local] = pd.Series(f[local], index=index).rolling(
                pd.Timedelta(days=window_days), center=True, min_periods=15).median().to_numpy()
            segments += 1
    keep = np.isfinite(trend) & (trend > 0)
    if keep.sum() < 200:
        raise ValidationError("Insufficient supported samples after gap-local detrending")
    flux = f[keep] / trend[keep]
    formal = e[keep] / trend[keep]
    # Conservative white-noise floor; this does not correct correlated noise.
    adjacent = (np.diff(t[keep]) < 5 * np.median(np.diff(t[keep]))) & (np.diff(curve.segment[keep]) == 0)
    diff = np.diff(flux)[adjacent]
    noise = float(1.4826 * np.median(np.abs(diff - np.median(diff))) / np.sqrt(2)) if len(diff) else 0.
    error = np.maximum(formal, max(noise, 1e-10))
    metadata = {**curve.metadata, "detrending": {"method": "blind_gap_local_rolling_median_v1",
        "window_days": window_days, "gap_cadences": gap_cadences, "segments": segments,
        "n_unsupported": int((~keep).sum()), "catalog_masks": False, "clipping": "none",
        "error_floor_relative_flux": noise, "error_model": "max(formal/trend, robust_adjacent_difference_scatter)",
        "limitation": "No correlated-noise correction; long transits or high duty cycles may be attenuated."}}
    flattened = LightCurve(t[keep], flux, error, curve.segment[keep], curve.sources, metadata)
    return flattened, {"time": t[keep], "flux_raw_normalized": f[keep] / np.median(f[keep]),
                       "trend_normalized": trend[keep] / np.median(f[keep]), "flux_err_formal": formal}
