"""Real-photometry injection/recovery benchmark for adaptive test-time memory.

The injection grid and cached TESS target are inherited from the frozen blind
detection control experiment.  Truth is used only after each BLS search.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.experiments.adaptive_memory import MemoryConfig, MultiTimescaleTestTimeMemory
from scripts.research.detection import SearchConfig, phase_distance, search
from scripts.research.detection_controls import DESCRIPTIVE_WHITE_SNR, _selection, evaluate_proposals
from scripts.research.lightcurves import LightCurve, read_lightcurves
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "adaptive_memory_real_injection_v1"
MODES = ("raw", "frozen", "adaptive", "protected")


def normalized_curve(curve, flux=None):
    """Return relative flux without changing times, masks, or provenance."""
    values = np.asarray(curve.flux if flux is None else flux, dtype=np.float64)
    median = float(np.median(values))
    if not np.isfinite(median) or median <= 0:
        raise ValueError("Light-curve median must be finite and positive")
    return LightCurve(curve.time.copy(), values / median, curve.error / median,
                      curve.segment.copy(), curve.sources, {**curve.metadata, "normalization": "global_median"})


def inject_box(curve, period, depth, duration_hours, phase_fraction=.37):
    """Inject into real raw photometry before any preprocessing."""
    epoch = float(curve.time[0] + phase_fraction * period)
    mask = np.abs(phase_distance(curve.time, period, epoch)) < duration_hours / 48
    injected = LightCurve(curve.time.copy(), curve.flux * (1 - depth * mask), curve.error.copy(),
                          curve.segment.copy(), curve.sources, {**curve.metadata, "synthetic_injection": True})
    return injected, {"period_days": float(period), "epoch_bjd_tdb": epoch + 2457000,
                      "duration_hours": float(duration_hours), "injected_depth": float(depth)}


def memory_curve(curve, mode, memory):
    """Apply observable-only memory and expose its residual as relative flux."""
    relative = normalized_curve(curve)
    if mode == "raw":
        return relative, {"protection_fraction": 0.0}
    output = memory.run(relative.flux, mode)
    # Preserve the detector's expected positive relative-flux convention.  All
    # modes enter the same downstream detrending and BLS implementation.
    residual_flux = 1 + output["residual"]
    if not np.isfinite(residual_flux).all() or np.any(residual_flux <= 0):
        raise ValueError("Memory produced invalid residual flux")
    transformed = LightCurve(relative.time, residual_flux, relative.error, relative.segment,
                             relative.sources, {**relative.metadata, "memory_mode": mode})
    return transformed, {"protection_fraction": output["protection_fraction"]}


def proposals_only(result):
    return result["proposals"]


def run_benchmark(root, memory_config, search_config, periods, depths, duration_hours):
    selection = _selection(root)
    entry = selection[0]
    base = read_lightcurves(entry["paths"], mission=entry["mission"], target_id=entry["target_id"])
    memory = MultiTimescaleTestTimeMemory(memory_config)
    rows = []
    for period in periods:
        for depth in depths:
            injected, truth = inject_box(base, period, depth, duration_hours)
            for mode in MODES:
                print(f"injection p={period} depth={depth} mode={mode}", flush=True)
                candidate, diagnostics = memory_curve(injected, mode, memory)
                found = proposals_only(search(candidate, search_config))
                evaluation = evaluate_proposals(found, truth, float(candidate.time[0]), float(np.ptp(candidate.time)))
                rows.append({"kind": "injection", "period_days": period, "depth": depth, "mode": mode,
                             "direct_recovery": evaluation["direct_recovery"],
                             "recovered_with_sampling_gate": evaluation["recovered_with_sampling_gate"],
                             "strongest_snr": max((p["depth_snr_white"] for p in found), default=None),
                             "proposal_count": len(found), **diagnostics, "evaluation": evaluation})

    median = float(np.median(base.flux))
    negatives = {
        "flux_permutation_seed_2401": np.random.default_rng(2401).permutation(base.flux),
        "flux_inversion": 2 * median - base.flux,
        "white_noise_seed_2402": median + np.random.default_rng(2402).normal(0, base.error),
        "white_noise_seed_2403": median + np.random.default_rng(2403).normal(0, base.error),
    }
    for label, flux in negatives.items():
        negative = LightCurve(base.time.copy(), flux, base.error.copy(), base.segment.copy(),
                              base.sources, {**base.metadata, "negative_control": label})
        for mode in MODES:
            print(f"negative {label} mode={mode}", flush=True)
            candidate, diagnostics = memory_curve(negative, mode, memory)
            found = proposals_only(search(candidate, search_config))
            above = sum(p["depth_snr_white"] >= DESCRIPTIVE_WHITE_SNR and
                        p["diagnostics"]["sampling_gate_passed"] for p in found)
            rows.append({"kind": "negative", "label": label, "mode": mode,
                         "proposal_count": len(found), "proposals_above_reference": above,
                         "strongest_snr": max((p["depth_snr_white"] for p in found), default=None), **diagnostics})

    summary = {}
    for mode in MODES:
        injections = [r for r in rows if r["kind"] == "injection" and r["mode"] == mode]
        controls = [r for r in rows if r["kind"] == "negative" and r["mode"] == mode]
        summary[mode] = {
            "injections_recovered": sum(r["direct_recovery"] for r in injections),
            "injections_total": len(injections),
            "negative_controls_with_alert": sum(r["proposals_above_reference"] > 0 for r in controls),
            "negative_controls_total": len(controls),
            "mean_protection_fraction": float(np.mean([r["protection_fraction"] for r in injections])),
        }
    source = entry["paths"][0]
    return {"schema_version": 1, "version": VERSION, "status": "complete", "generated_at": utc_now(),
            "source": {"mission": entry["mission"], "target_id": entry["target_id"], "path": str(source),
                       "sha256": file_sha256(source), "split": entry["split"]},
            "injections": {"periods_days": periods, "depths": depths, "duration_hours": duration_hours,
                           "placement": "multiplicative_box_before_normalization_memory_detrending_and_BLS"},
            "memory_config": asdict(memory_config), "search_config": asdict(search_config), "rows": rows,
            "summary": summary,
            "claims": {"real_cached_photometry": True, "outperformance_established": False,
                       "survey_false_alarm_calibrated": False, "search_ready": False,
                       "tls_run": False, "titans_or_hope_reproduction": False},
            "limitations": ["One selected TESS TRAIN target and six injections are an engineering comparison, not a held-out survey estimate",
                "The 7.1 white-noise S/N value is descriptive and does not establish a false-alarm rate",
                "Known astrophysical signals remain in the injection curves", "TLS dependency and adapter are absent",
                "The memory prototype is Titans/HOPE-inspired, not a reproduction"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/adaptive_memory_real_v1.json")
    parser.add_argument("--output", default="results/adaptive_memory_real_v1")
    args = parser.parse_args(argv)
    values = json.loads((ROOT / args.config).read_text())
    memory_config = MemoryConfig(**{**values["memory"], "learning_rates": tuple(values["memory"]["learning_rates"])}).validate()
    protocol = json.loads((ROOT / values["protocol"]).read_text())
    search_config = SearchConfig.from_protocol(protocol)
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output already exists; choose a new versioned directory")
    output.mkdir(parents=True, exist_ok=True)
    spec = {"version": VERSION, "config": values,
            "source_sha256": file_sha256(ROOT / "scripts/experiments/adaptive_memory_real.py")}
    result = run_benchmark(ROOT, memory_config, search_config, values["periods_days"], values["depths"], values["duration_hours"])
    result["spec_sha256"] = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    (output / "spec.json").write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    (output / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = ["# Real-photometry adaptive-memory benchmark", "", "Cached TESS engineering control; no discovery or survey-readiness claim.", "",
             "| Mode | Injection recovery | Negative controls above S/N reference |", "| --- | ---: | ---: |"]
    for mode in MODES:
        row = result["summary"][mode]
        lines.append(f"| {mode} | {row['injections_recovered']}/{row['injections_total']} | {row['negative_controls_with_alert']}/{row['negative_controls_total']} |")
    raw = result["summary"]["raw"]
    best = max(result["summary"], key=lambda m: (result["summary"][m]["injections_recovered"],
                                                  -result["summary"][m]["negative_controls_with_alert"]))
    result["claims"]["outperformance_established"] = bool(
        result["summary"][best]["injections_recovered"] > raw["injections_recovered"] and
        result["summary"][best]["negative_controls_with_alert"] <= raw["negative_controls_with_alert"])
    # Rewrite after the derived claim is computed.
    (output / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines += ["", f"Best lexicographic engineering result: **{best}**. Outperformance under the predeclared rule: **{result['claims']['outperformance_established']}**.",
              "", "TLS was not run because its dependency and adapter are absent from the reference environment.", ""]
    (output / "README.md").write_text("\n".join(lines))
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "README.md")}
    (output / "complete.json").write_text(json.dumps({"status": "complete", "completed_at": utc_now(),
        "spec_sha256": result["spec_sha256"], "files": files}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "complete", "output": str(output), "summary": result["summary"],
                      "outperformance_established": result["claims"]["outperformance_established"]}, indent=2))


if __name__ == "__main__":
    main()
