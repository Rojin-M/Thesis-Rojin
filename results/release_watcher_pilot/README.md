# Public metadata and finite dispatcher engineering control

Recorded 22 September 2026 (Vienna). This is an operational control, **not**
prospective discovery, model-performance evaluation or planet validation.

The official MAST CAOM Filtered/Products APIs were queried for exactly one
existing known-control TIC, **231663901**. The latest returned standard SPOC
light curve was sector **105**, filename processing build **0307**, **2,021,760
bytes**. Both bounded metadata pages were complete for this selected query.
This does not establish archive-wide or whole-sector completeness.

The real pilot froze that one product, an **8 MiB / 900-second** cumulative cap,
code and protocol identities, and the `known_object_control` cohort. It found
the source already cached, verified its original **9 September 2026** acquisition
receipt, SHA256 and native FITS integrity/time/target headers, then reused it.
**Zero new light-curve/pixel science bytes were downloaded.** The real public
query and processing path were exercised; live archive science transfer was not
needed. The downloader was separately exercised through actual local HTTP using
generated checksummed FITS and the real downstream detector/model/server.

All eight stages completed once in approximately **43.8 seconds** of charged
runtime. Three proposals remain in human review:

| Rank | Blind period (days) | CNN ranking score | Supported cached registry |
| --- | ---: | ---: | --- |
| 1 | 1.4304284535 | 0.9537986 | Compatible existing confirmed-planet identity |
| 2 | 4.9287493278 | 0.0063587 | UNMATCHED |
| 3 | 0.8427501844 | 0.0043735 | UNMATCHED |

Scores are uncalibrated evidence. Registry identities do not confirm these
proposals; UNMATCHED is not novelty. Image, neighbor, aperture, broader catalog,
calibration and survey-control gaps remain visible. No threshold/model was tuned.

A repeated live poll reused the release/product identities. Actual CLI restart
returned `already_complete` with no extra candidates, stage attempts, or network
transfers. All **14 prior jobs / 38 candidates** and their stage/evidence/artifact
rows remain byte-for-byte equal in SQLite values. All 14 original input files,
the checkpoint and normalizer passed unchanged hash checks. The database now has
**15 jobs / 41 candidates**; the new three belong to the known-control cohort.

Stage-04 metadata response content: **67,812 bytes**, including two initial API
verification responses and two implemented watcher polls. The durable ledger
also carries the previous **5,392,591 catalog bytes**: cumulative charge
**5,460,403 bytes**, leaving **2,142,023,245 bytes** before future polling.
These are a recorded snapshot; the metadata-only service can incur later bounded
metadata charges, always against that same cumulative cap.

[summary.json](summary.json) retains concrete identities, source hash, periods,
scores, budget, code/model preservation and browser results. Full local evidence:
`outputs/research/experiments/release-watcher-v1/`; replay/API/test logs:
`outputs/research/logs/04_*`; actual browser screenshots and result:
`outputs/research/watcher-browser/`. The final stage handoff records regression
outcomes and service state. See [watcher contracts and limitations](../../docs/release_watcher.md).

Validation: final full offline regression **204 tests, OK (1 opt-in live test skipped)**, 277.357 seconds.
Actual Chromium desktop/mobile and all real control plots passed with zero
JavaScript exceptions. All 794 prior artifact files passed their stored hashes.
