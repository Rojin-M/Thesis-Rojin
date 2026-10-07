"""Transit-preserving multi-timescale test-time memory engineering pilot.

This is a small Titans/HOPE-inspired fast-weight memory, not a reproduction of
either architecture.  It tests the central failure mode before a larger model is
trained: online adaptation can learn away transit-shaped negative excursions.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256

VERSION = "transit_preserving_test_time_memory_v1"


@dataclass(frozen=True)
class MemoryConfig:
    warmup: int = 64
    learning_rates: tuple = (.08, .02, .005)
    momentum: float = .8
    forgetting: float = .0005
    fast_baseline_rate: float = .08
    slow_baseline_rate: float = .008
    scale_rate: float = .02
    protection_sigma: float = 3.5
    protection_hold: int = 3
    gradient_clip: float = 5.0

    def validate(self):
        if type(self.warmup) is not int or not 16 <= self.warmup <= 10000:
            raise ValueError("Invalid memory warmup")
        if (not 1 <= len(self.learning_rates) <= 8 or any(
                type(x) not in (int, float) or not 0 < x <= .5 for x in self.learning_rates)):
            raise ValueError("Invalid memory learning rates")
        for name in ("momentum", "forgetting", "fast_baseline_rate", "slow_baseline_rate",
                     "scale_rate", "protection_sigma", "gradient_clip"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid " + name)
        if not (0 <= self.momentum < 1 and 0 <= self.forgetting < .1
                and 0 < self.slow_baseline_rate < self.fast_baseline_rate <= .5
                and 0 < self.scale_rate <= .5 and 1 <= self.protection_sigma <= 10
                and 0 < self.gradient_clip <= 100 and type(self.protection_hold) is int
                and 0 <= self.protection_hold <= 100):
            raise ValueError("Memory settings exceed supported bounds")
        return self


def _checked_flux(flux):
    value = np.asarray(flux, dtype=np.float64)
    if value.ndim != 1 or len(value) < 32 or not np.isfinite(value).all():
        raise ValueError("Expected a finite one-dimensional light curve")
    return value


class MultiTimescaleTestTimeMemory:
    """Online fast weights with observable-only protection of negative surprises."""

    def __init__(self, config=MemoryConfig()):
        self.config = config.validate()

    def run(self, flux, mode="protected"):
        if mode not in ("frozen", "adaptive", "protected"):
            raise ValueError("Memory mode must be frozen, adaptive or protected")
        flux = _checked_flux(flux)
        c = self.config
        center = float(np.median(flux[:c.warmup]))
        mad = float(np.median(np.abs(flux[:c.warmup] - center)))
        scale = max(1.4826 * mad, abs(center) * 1e-6, 1e-8)
        fast = slow = center
        weights = np.zeros((len(c.learning_rates), 5), dtype=np.float64)
        velocity = np.zeros_like(weights)
        prediction = np.empty_like(flux)
        protected = np.zeros(len(flux), dtype=bool)
        surprise = np.zeros(len(flux), dtype=np.float64)
        hold = 0
        previous = center
        for index, observed in enumerate(flux):
            key = np.asarray([1., (previous - slow) / scale, (fast - slow) / scale,
                              (fast - previous) / scale, min(index / max(len(flux) - 1, 1), 1.)])
            memory_residual = float(np.mean(weights @ key)) * scale
            predicted = slow + memory_residual
            prediction[index] = predicted
            surprise[index] = (observed - predicted) / scale
            detected = index >= c.warmup and surprise[index] <= -c.protection_sigma
            if mode == "protected" and (detected or hold > 0):
                protected[index] = True
                hold = c.protection_hold if detected else hold - 1
            can_update = index < c.warmup or (mode == "adaptive") or (
                mode == "protected" and not protected[index])
            if mode == "frozen" and index >= c.warmup:
                can_update = False
            if can_update:
                target = (observed - slow) / scale
                error = float(np.mean(weights @ key) - target)
                gradient = np.clip(error * key, -c.gradient_clip, c.gradient_clip)
                for row, rate in enumerate(c.learning_rates):
                    velocity[row] = c.momentum * velocity[row] + (1 - c.momentum) * gradient
                    weights[row] = (1 - c.forgetting) * weights[row] - rate * velocity[row]
                fast += c.fast_baseline_rate * (observed - fast)
                slow += c.slow_baseline_rate * (observed - slow)
                scale += c.scale_rate * (max(abs(observed - predicted), 1e-8) - scale)
                scale = max(scale, abs(center) * 1e-6, 1e-8)
            previous = observed
        residual = flux - prediction
        return {"prediction": prediction, "residual": residual, "surprise": surprise,
                "protected": protected, "protection_fraction": float(protected.mean())}


def synthetic_curve(seed, depth, period=80, duration=4, size=800):
    rng = np.random.default_rng(seed)
    time = np.arange(size, dtype=np.float64)
    baseline = 1 + .003 * np.sin(2 * np.pi * time / 137) + .0015 * np.sin(2 * np.pi * time / 43)
    baseline += .000003 * np.maximum(time - 400, 0)
    mask = np.zeros(size, dtype=bool)
    for start in range(96, size, period):
        mask[start:start + duration] = True
    flux = baseline - depth * mask + rng.normal(0, .0007, size)
    return {"time": time, "flux": flux, "baseline": baseline, "transit_mask": mask,
            "depth": depth, "period": period, "duration": duration}


def evaluate_run(curve, output):
    mask = curve["transit_mask"]
    quiet = ~mask
    residual = output["residual"]
    observed_depth = float(np.median(residual[quiet]) - np.median(residual[mask]))
    noise = float(1.4826 * np.median(np.abs(residual[quiet] - np.median(residual[quiet]))))
    return {"retained_depth": observed_depth, "depth_retention_fraction": observed_depth / curve["depth"],
            "residual_noise": noise, "retained_depth_snr": observed_depth / max(noise, 1e-12),
            "baseline_rmse": float(np.sqrt(np.mean((output["prediction"][quiet] - curve["baseline"][quiet]) ** 2))),
            "protection_fraction": output["protection_fraction"],
            "protected_transit_fraction": float(output["protected"][mask].mean()),
            "protected_quiet_fraction": float(output["protected"][quiet].mean())}


def run_pilot(config, seeds=(11, 23, 47), depths=(.002, .005, .01)):
    memory = MultiTimescaleTestTimeMemory(config)
    rows = []
    for seed in seeds:
        for depth in depths:
            curve = synthetic_curve(seed, depth)
            for mode in ("frozen", "adaptive", "protected"):
                rows.append({"seed": seed, "injected_depth": depth, "mode": mode,
                             **evaluate_run(curve, memory.run(curve["flux"], mode))})
    summary = {}
    for mode in ("frozen", "adaptive", "protected"):
        selected = [row for row in rows if row["mode"] == mode]
        summary[mode] = {name: float(np.mean([row[name] for row in selected])) for name in
                         ("depth_retention_fraction", "retained_depth_snr", "baseline_rmse",
                          "protected_transit_fraction", "protected_quiet_fraction")}
    return {"schema_version": 1, "version": VERSION, "status": "complete", "generated_at": utc_now(),
            "config": asdict(config), "seeds": list(seeds), "depths": list(depths), "rows": rows,
            "summary": summary,
            "claims": {"titans_reproduction": False, "hope_reproduction": False,
                       "real_data_validated": False, "improvement_established": False,
                       "search_ready": False},
            "limitations": ["Synthetic engineering curves only", "Fast-weight memory is Titans/HOPE-inspired, not an architecture reproduction",
                "Protection uses observable residual surprise but is not yet jointly trained", "No BLS/TLS recovery or false-alarm study yet"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/adaptive_memory_pilot_v1.json")
    parser.add_argument("--output", default="results/adaptive_memory_pilot_v1")
    args = parser.parse_args(argv)
    values = json.loads((ROOT / args.config).read_text())
    config = MemoryConfig(**{**values, "learning_rates": tuple(values["learning_rates"])}).validate()
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Adaptive-memory output already exists; choose a new versioned output")
    output.mkdir(parents=True, exist_ok=True)
    spec = {"version": VERSION, "config": asdict(config),
            "source_sha256": file_sha256(ROOT / "scripts/experiments/adaptive_memory.py")}
    summary = run_pilot(config)
    summary["spec_sha256"] = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    (output / "spec.json").write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = ["# Transit-preserving test-time memory pilot", "", "Synthetic engineering test; not a Titans/HOPE reproduction or a discovery result.", "",
             "| Mode | Mean depth retention | Mean retained-depth S/N | Baseline RMSE |", "| --- | ---: | ---: | ---: |"]
    for mode, row in summary["summary"].items():
        lines.append(f"| {mode} | {row['depth_retention_fraction']:.3f} | {row['retained_depth_snr']:.3f} | {row['baseline_rmse']:.6f} |")
    lines += ["", "The next valid step is injection before preprocessing on real target-pixel/light-curve data, with BLS/TLS and fixed false-alarm comparisons.", ""]
    (output / "README.md").write_text("\n".join(lines))
    files = {name: file_sha256(output / name) for name in ("spec.json", "summary.json", "README.md")}
    (output / "complete.json").write_text(json.dumps({"status": "complete", "completed_at": utc_now(),
        "spec_sha256": summary["spec_sha256"], "files": files}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "complete", "output": str(output), "summary": summary["summary"]}, indent=2))


if __name__ == "__main__":
    main()
