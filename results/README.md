# Active thesis evidence

This directory indexes the compact evidence retained for the Kepler-to-TESS domain-adaptation and discovery thesis. Detailed checkpoints, predictions, caches, and live reports remain in ignored local `outputs/` and `data/` directories.

| Evidence | Role | Main limitation |
| --- | --- | --- |
| [Kepler–TESS input audit](tess/input_audit/README.md) | Measures preprocessing and feature-distribution shift | Descriptive; does not prove what caused a model error |
| [Shared-transfer benchmark](tess/shared_transfer/README.md) | Freezes the Phase-1 CNN reference results | Single seed and previously consulted labelled tests |
| [Candidate-registry control](tess/candidate_vetting/README.md) | Verifies recognition of a known confirmed signal in current public catalogs | Catalog matching is not planet validation or proof of novelty |

These are the only active result groups. Earlier practical-work model sweeps are not part of the thesis evidence index.

The benchmark and catalog checker answer different questions:

- Model metrics measure ranking and classification on labelled examples.
- Registry matching asks whether a compatible public record is present at a recorded time.
- Human and observational vetting asks whether an unmatched signal is astrophysical and plausibly planetary.

None of the committed results constitutes a new candidate or confirmed-planet claim. See the [main README](../README.md) for the active workflow and planned `discovery_v1` protocol.
