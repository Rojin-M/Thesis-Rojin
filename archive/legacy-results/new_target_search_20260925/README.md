# New TESS target search: 25 September 2026

Snapshot: **25 September 2026, 12:59:23 UTC / 14:59:23 Vienna**.
The live worker continues after this snapshot; these files do not update themselves.

The earlier watcher followed only two known-object controls. The new discovery
configuration selected **18 targets not already in the project's TESS data or
research records**, from recent public SPOC light curves in sectors **103–106**.
At this snapshot, **4 targets had completed processing and saved 10 signal
proposals**; the remaining **14** were selected for later worker cycles. All ten
latest supported catalog checks were complete and `UNMATCHED`. Eight proposals
had valid reference CNN inputs and experimental model comparisons; two had
insufficient sampled transit coverage and received no invented score.

This is an **archival pilot**, not a new-planet announcement. The scored proposals
ranked low with the frozen CNN (approximately 0.00379–0.00513). Diagnostics include
gap-edge events, crowding, secondary excursions and near-duplicate periods.
Image-based source localization, contamination checks and search-wide recovery
and false-alarm calibration remain unfinished. `UNMATCHED` means no compatible
record in the supported snapshots; neither that label nor a model score is a
planet probability.

## Selection and acquisition evidence

The archive request constrained **both observation start and public release** to
the preceding 180 days. This avoids treating recently reprocessed old sectors as
recent observations. One successful 100-row metadata page described a bounded
sample from a reported 61,417 matching observations; it was not a complete archive
census. The exclusion audit contained **2,371 distinct TIC IDs**, using recorded
raw/processed TESS manifests, Kepler overlap and local research records. Catalog
periods and epochs did not choose the targets or seed blind BLS detection.

Broad archive requests experienced read timeouts. The first batch therefore
reused the **successful preflight response retrieved at 12:48:13 UTC**, after
verifying its bytes, SHA-256, query window and exclusions. Selection receipts
retain that original poll and provenance identity. Reuse does not claim a second
network retrieval. Subsequent target-specific archive requests independently
registered the selected science products and checked the recent observation
window before acquisition.

At this snapshot, verified new science downloads totalled **8,052,480 bytes**.
The export rechecked every completed download's size and SHA-256. The cumulative
ledger charged **42,487,280 bytes** including prior work, metadata and conservative
failure allowances, with no unsettled reservations at snapshot time.

## Inspect the results

Open [Candidates](http://127.0.0.1:8766/#candidates), choose **Archival pilot**, and
open a target dossier. [Watcher](http://127.0.0.1:8766/#watcher) shows selected TICs,
processing state, errors and remaining limits. The vetting helper and experimental
comparison worker use local models; this run does not call a paid conversational
AI service.

The tmux worker keeps processing while the host remains running. It handles at
most two products per cycle. The two historical controls plus these 18 targets
fill the initial **20-product cumulative cap**. Completing this batch does not
enable an unlimited rolling survey; more acquisition requires an explicit,
audited extension of the selection and resource policy. Restarting or clicking
**Check for new data** does not erase limits or create extra capacity.

- [summary.json](summary.json): dated counts, worker configuration, limits and ledger.
- [selection.json](selection.json): all 18 TICs, exclusion audit and original metadata receipt.
- [source_metadata.json](source_metadata.json): exact public archive response retained for verification.
- [products.json](products.json): product identities, processing states and checked download receipts.
- [jobs.json](jobs.json) and [processing_provenance.json](processing_provenance.json): processing identities and frozen source manifests.
- [candidates.json](candidates.json): ten proposal assessments, latest evidence, diagnostics and artifact checksums.
- [archive_failures.json](archive_failures.json): retained archive poll failures from this session.
- [validation.json](validation.json): focused regression and browser validation.

These are compact records exported from a consistent SQLite backup. They do not
contain every light curve, plot or model weight and are **not a full restore
archive**. Keep the live `outputs/research/` data and use the
[backup guide](../../docs/website_guide.md#where-logs-and-results-live) to
preserve a later full snapshot. The older 23 September backup predates this run.
