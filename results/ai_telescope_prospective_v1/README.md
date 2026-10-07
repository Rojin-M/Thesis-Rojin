# Frozen unseen-host AI-telescope scan

The unchanged four-view v2 model completed inference on all 90 registered hosts
outside its development cohort. These are the unreviewed remainder of the
original frozen 100-host manifest; the 10 previously examined by the pixel pilot
were explicitly excluded, with no replacements or score-dependent selection.

| Quantity | Result |
| --- | ---: |
| Registered / completed hosts | 90 / 90 |
| Failed hosts | 0 |
| Inference windows | 13,476 |
| Valid cadences | 1,491,027 |
| Detected segments before the per-host cap | 1,045 |
| Retained segments, at most 20 per host | 776 |
| Hosts with retained segments | 65 |
| Hosts reaching the 20-segment cap | 23 |
| Retained segments within the frozen duration prior | 307 |
| New public TPF bytes acquired | 4,292,786,880 |

The checkpoint, threshold (0.854588449), context normalization and scan geometry
were unchanged. Cohort membership was verified against all shared-v1 partitions
and the physical-expert development cohort. Input hashes, source hashes and
archive product sizes were registered before inference. All 96 output artifact
checksums verified, and all 90 registered targets are represented exactly once.

These are operational results, not an accuracy or discovery result. Catalog
ephemerides and labels were withheld throughout this scan, so there is no
measured recall, precision or false-alarm rate. The 307 duration-compatible
segments are an unvetted review queue, not planet candidates. A single broad
variation can create multiple segments; the per-host cap also means the queue
does not include every detected segment. The cohort is archival and limited to
one sector per host, not a random sky survey.

The high number of review segments, together with the separate 79-event audit
vetting, makes continuous-scan calibration and injection recovery the next
scientific priority. This cohort must not be used for hyperparameter tuning;
future labels can assess the already-frozen predictions. Production watcher
scoring remains unchanged.

- [Committed evidence summary](evidence.json)
- [Historical methods and remaining research](../../archive/legacy-docs/ai_telescope_research.md)

The review queue, event table, and full scan report remain in local ignored
outputs under `outputs/research/ai_telescope/prospective-v1/`; they are not part
of this public snapshot.
