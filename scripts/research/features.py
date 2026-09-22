"""shared_v1 geometry and scalar semantics, using only blind proposal ephemerides.

This adapter does not change the frozen benchmark. It reuses its functions with
inferred transit protection/companion masks and records that domain difference.
"""
from dataclasses import asdict, replace

import numpy as np

from scripts.data.shared_preprocessing import SharedConfig, candidate_features, ephemeris, KEYS
from scripts.data.tess_preprocessing import detrend_sector, SCALAR_NAMES
from scripts.data.kepler_pipeline_lib import compute_bls_features
from .contracts import validate_shared_inputs
from .lightcurves import read_lightcurves
from .protocol import ValidationError

VERSION = "blind_shared_v1"


def build_features(inputs, candidates):
    if not 1 <= len(candidates) <= 3:
        raise ValidationError("Feature worker accepts 1–3 proposals from one bounded job")
    rows = []
    for c in candidates:
        if c["detection"].get("ephemeris_origin") != "blind_search" or c["detection"].get("used_catalog_ephemeris") is not False:
            raise ValidationError("The proposal adapter requires independently estimated ephemerides")
        eph = c["ephemeris"]
        rows.append({"candidate_id": c["id"], "period": eph["period_days"],
                     "epoch_bjd": eph["epoch_bjd_tdb"], "duration_hours": eph["duration_hours"]})
    companions = {row["candidate_id"]: ephemeris(row) for row in rows}
    curve = read_lightcurves(inputs["paths"], mission=inputs["mission"], target_id=inputs["target_id"],
                            time_system=inputs.get("time_system"), expected_hashes=inputs["sha256"])
    cfg = SharedConfig()
    parts, receipts, cadences = [], [], []
    for number in np.unique(curve.segment):
        take = curve.segment == number
        t, f = curve.time[take], curve.flux[take]
        native = curve.sources[int(number)].get("native_cadence_days")
        cadence = float(native) * 86400 if native is not None else float(np.median(np.diff(t))) * 86400
        if not np.isfinite(cadence) or cadence <= 0:
            raise ValidationError("No usable cadence for shared preprocessing")
        t, f, details = detrend_sector(t, f, list(companions.values()), replace(cfg, cadence_seconds=cadence))
        parts.append((t, f)); cadences.append(cadence)
        receipts.append({"source_sha256": curve.sources[int(number)]["sha256"], "cadence_seconds": cadence, **details})
    t, f = (np.concatenate([p[k] for p in parts]) for k in (0, 1))
    order = np.argsort(t, kind="stable")
    t, f = t[order], f[order]
    cfg = replace(cfg, cadence_seconds=float(np.median(cadences)))
    # EXACT legacy context: 2000 linear periods, 20 durations, likelihood power.
    # Do not substitute the detector's white-noise depth S/N or best period here.
    bls = compute_bls_features(t, f, cfg)
    results = []
    for row in rows:
        result = candidate_features(t, f, row, companions, cfg, bls)
        result.pop("folded", None)
        result["diagnostics"]["coverage_interpretation"] = "sampling_at_blind_inferred_ephemeris_not_detection_significance"
        result["diagnostics"]["n_inferred_companions"] = result["diagnostics"].pop("n_known_companions")
        if result["status"] == "accepted":
            arrays = {key: value[None, ...] for key, value in result["arrays"].items() if key in KEYS}
            result["contract_validation"] = validate_shared_inputs(arrays)
            result["arrays"] = arrays
        results.append(result)
    return {"candidates": results, "version": VERSION, "config": asdict(cfg), "products": receipts,
            "scalar_names": list(SCALAR_NAMES), "legacy_bls": bls,
            "period_unit": "day", "duration_unit": "hour", "epoch_system": "BJD_TDB",
            "internal_time_system": "BTJD", "ephemeris_source": "blind_proposals_only",
            "preprocessing_difference": "Protect all inferred proposal windows during shared gap/product detrending; mask other inferred proposals before each fold. Benchmark uses catalog windows and typically more products.",
            "legacy_scalar_semantics": {"odd_even": "alternating_local_phase_bins_not_events", "bls_snr": "star_level_BLS_log_likelihood_not_depth_SNR", "bls_duration": "hours", "bls_period": "days"},
            "limitations": ["Inferred false proposals can mask real samples; unmasked detection arrays remain attached.",
                            "Missing or incorrect inferred companions differ from the labelled training pipeline.",
                            "No test-set selection, normalization fitting, catalog ephemerides or score veto."]}
