# Automatic watcher: public download and saved review proposals

Snapshot: **23 September 2026, 13:35:58 UTC / 15:35:58 Vienna**.
This records the automatic watcher's engineering operation on two known-object
controls. It does not establish a new planet or a prospective survey result.

## What changed since the previous pilot

The [earlier release pilot](../release_watcher_pilot/README.md) retained **15 jobs
and 41 proposals**, using a cached TIC 231663901 light curve. The automatic
watcher subsequently downloaded the previously unprocessed **TIC 150428135,
sector 97** standard SPOC light curve: **3,962,880 bytes**. Its archive release
date is 8 December 2025; this was newly processed by this installation, not newly
released on the snapshot date.

The new job completed all eight stages, from metadata to dossier, in **52.82
seconds of charged dispatch runtime**. Catalog refresh is separate from that
duration. The database now contains **16 successful jobs and 44 proposals**:
**17 real-data known-object-control proposals and 27 synthetic fixtures**.

| New proposal | Blind period (days) | CNN ranking score | Supported catalog result |
| --- | ---: | ---: | --- |
| `966fa860109b4427b72565747796ed77` | 16.051396 | 0.984954 | `CONFIRMED_PLANET`: compatible existing record |
| `53a84bf4a2574b6482d4483e5edb7bc3` | 13.839302 | 0.004257 | `UNMATCHED` |
| `e3fc176f07ce4b7a91651ccf7d07bb30` | 25.324354 | 0.014582 | `UNMATCHED` |

All three remain unreviewed, with transit-diagnostic, centroid, contamination
and control evidence categories incomplete. Scores are uncalibrated ranking
values. A compatible catalog identity does not independently validate a proposal;
`UNMATCHED` does not establish novelty.

Across all 17 real-data proposals, the saved registry assessments are **6
unmatched, 3 confirmed-planet matches, 1 known-planet match, 2 ambiguous matches
and 5 incomplete lookups**. These counts describe signals, not distinct planets.
The [candidate export](candidates.json) preserves their IDs, periods, scores,
review states, flags and missing checks; synthetic fixtures are excluded.
The highest score among the unmatched proposals is **0.014582**, for TIC
150428135 at 25.324354 days. This is a low model ranking, not an established
promising new planet or a calibrated probability.

## Activity and failures

[activity.jsonl](activity.jsonl) contains **25 chronological structured events**
for 23 September: archive polls, manual requests, dispatches, the audited recovery,
download receipt, eight completed stages and three proposal creations. Times are
UTC. This is a compact export of persisted records, not a complete raw log.

| Time (UTC) | Recorded event |
| --- | --- |
| 12:50 | First acquisition rejected MAST's HTTP 302 redirect; the failed attempt remained charged. |
| 13:03 | An explicit replacement pilot recorded the inspected transport fix and remaining original budgets. |
| 13:03–13:04 | Second acquisition succeeded; detection, CNN scoring and dossier creation saved three proposals. |
| 13:05 | A requested archive check succeeded with no additional products or proposals. |
| 13:22 | A requested check failed with a retryable MAST read timeout. |
| 13:33 | A later requested check succeeded with no additional products or proposals. |

At the snapshot the service was running, waiting for its next scheduled poll
at **19:33 UTC**. The ledger held **20,343,801 charged bytes** against the **2 GiB**
cap, with no unsettled reservations. Charges include conservative failed-attempt
allowances; they are not the same as successfully transferred science bytes.
The original failed pilot and its attempt/budget history remain recorded.

## Evidence and logs

- [summary.json](summary.json): snapshot counts, configuration, budgets, product
  checksum and official URLs, processing source/model identities and stage times.
- [candidates.json](candidates.json): all real-data proposal assessments at the snapshot.
- [activity.jsonl](activity.jsonl): compact chronological processing/check history.
- [validation.json](validation.json): regression and previously recorded browser checks.
- Local `outputs/research/automatic-watcher.log`: full automatic cycle logs,
  new-proposal counts, failures and idle `not_due` ticks.
- Local `outputs/research/server.log`: research website requests and errors.
- Local `outputs/research/research.sqlite3`: persisted jobs, evidence, reviews,
  archive polls, check requests and resource accounting.

The public export was derived from a consistent SQLite backup without rerunning
the detector or changing reviews. The downloaded FITS file's size and SHA-256
were rechecked against its receipt. The recorded processing source predates later
browser-loading fixes; its original manifest is preserved rather than relabelled
as the final repository version.

The final offline regression ran **276 tests in 289.367 seconds: OK, one opt-in
live-catalog test skipped**. JavaScript syntax, local documentation links and
export consistency checks passed. The running website's health, overview and
watcher endpoints returned HTTP 200. Previously recorded browser checks cover
seven automatic-refresh/review-form behaviors and four loading/recovery cases,
with no recorded JavaScript exceptions; their summaries are in `validation.json`.

The database, raw logs, browser profiles, downloaded photometry and model files
remain ignored local runtime artifacts. The files in this result group are a
dated, reviewable snapshot for Git; they do not update when the watcher runs.
The separate [frozen vetting dataset](../vetting_snapshot_20260923/README.md)
now also preserves the database, all referenced evidence files, selected input
photometry and retained model in a checksummed archive with restore instructions.
See the [website log guide](../../docs/website_guide.md#where-logs-and-results-live)
for live monitoring and the [vetting guide](../../docs/website_guide.md#use-the-vetting-helper)
for the next review steps.
