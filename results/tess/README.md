# Kepler–TESS thesis evidence

This directory contains the three active evidence groups supporting the discovery pipeline.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| [Input audit](input_audit/README.md) | Kepler and TESS inputs are structurally compatible but distributionally different | The causal source of the transfer gap |
| [Shared transfer](shared_transfer/README.md) | Frozen seed-42 source-to-target metrics after common preprocessing | A statistically established domain-adaptation gain |
| [Candidate vetting](candidate_vetting/README.md) | A known multi-signal target is matched by signal ephemeris across public catalogs | That an unmatched signal is new or planetary |

## Frozen boundary

The input audit and shared-transfer export close Phase 1: the labelled benchmark. The checker begins Phase 2: candidate evidence handling. Future DANN experiments, prospective FFI searches, watcher runs, human-vetting dossiers, and submitted cTOIs must receive separate versions and must not silently modify these exports.

The shared preparation retained 5,385 Kepler candidates and all 2,208 TESS candidates. On the fixed 335-candidate TESS test subset, the frozen CNN results were:

| Input version | Accuracy | F1 | AP | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| v0 | 0.7254 | 0.7294 | 0.8021 | 0.7767 |
| shared_v1 | 0.7194 | 0.7099 | 0.7991 | 0.7828 |

The shared CNN did not improve TESS AP in this run. These are single-seed metrics on a previously consulted labelled benchmark, not expected discovery yield or uncertainty estimates. The active thesis model path is the CNN and planned domain-adversarial extension.

The registry control recognized TOI-700 d as `CONFIRMED_PLANET`. Its source counts and status describe public catalog evidence, not a percentage of research completed. An `UNMATCHED` future report will mean only that no compatible entry was found in the required snapshots at that time.

See the [main README](../../README.md) for setup, retained commands, the planned comparison matrix, and the human-vetting boundary.
