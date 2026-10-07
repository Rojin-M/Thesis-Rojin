# Transit-preserving test-time memory

This project now includes a bounded multi-timescale fast-weight memory experiment
inspired by [Titans](https://proceedings.neurips.cc/paper_files/paper/2025/file/a4ca07aa108036f80cbb5b82285fd4b1-Paper-Conference.pdf)
and Google's [Nested Learning / HOPE](https://research.google/blog/introducing-nested-learning-a-new-ml-paradigm-for-continual-learning/).
It is explicitly not a reproduction of either architecture.

The experiment asks whether an online memory can learn target-specific brightness
behaviour without learning away transit-shaped negative excursions. Three modes
process identical seeded curves:

- frozen memory after warmup;
- ordinary test-time adaptive memory; and
- adaptive memory whose updates pause after an observable-only negative-surprise
  trigger.

No injected transit truth enters the protection rule. Memory resets between
targets. The pilot records retained transit depth, residual signal-to-noise,
baseline error, and protection rates for transit and quiet cadences.

```bash
.venv/bin/python -m scripts.experiments.adaptive_memory
```

The synthetic engineering pilot demonstrates the expected tradeoff. Ordinary
adaptation improves baseline tracking but erases much of the transit. Protection
recovers some of that lost depth while retaining most of the baseline benefit.
Frozen memory preserves more depth in this small scenario. These outcomes are a
reason to continue the experiment, not evidence of improved exoplanet detection.

The follow-up benchmark runs the same six fixed injections on cached real TESS
photometry, with each injection applied before normalization, memory, detrending,
and BLS. It also repeats the four fixed negative controls:

```bash
.venv/bin/python -m scripts.experiments.adaptive_memory_real
```

Raw BLS recovered 4/6 injections with alerts in 2/4 negative controls. Frozen,
adaptive, and protected memory recovered 4/6, 2/6, and 3/6 respectively; their
negative-control alert counts were 3/4, 2/4, and 2/4. The protected version did
not outperform the baseline. This negative result prevents promoting memory to
the watcher and shows that protection should be learned jointly with the search
objective rather than inserted as an untrained residual transform.

Before joining the expert-fusion system, this arm must pass a larger frozen
protocol across disjoint TESS/Kepler hosts. The comparison must include BLS,
TLS, a fixed neural sequence baseline, frozen memory, ordinary adaptive memory
and protected memory. Primary outcomes are
recovery at fixed false-alarm burden, depth distortion, performance by stellar
variability/depth/duration, compute, and quiet-cadence false protection. Host and
sector splits must remain disjoint, memory must reset per target, and protection
thresholds must be fixed without test labels.
