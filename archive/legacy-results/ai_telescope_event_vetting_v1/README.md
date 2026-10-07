# AI-telescope single-event vetting

The frozen 79-segment audit queue has been processed on all 17 hosts. Most
segments do not show convincing local aperture dimming under the specified
diagnostic: of 64 measurable segments, 53 have positive dimming below white-noise
S/N 5 and nine show no positive dimming. The other two remain follow-up cases
with periodicity and localization concerns. Fifteen segments lack enough clean
cadences on both sides to fit the local baseline.

These counts describe this candidate-enriched, reused audit queue. They do not
estimate a survey false-alarm rate or establish that weak segments are false
positives. The noise assumptions, segment boundaries and local baseline can
affect the measurements.

| Evidence | Coverage |
| --- | ---: |
| Original audit segments accounted for | 79/79 |
| Hosts with completed blind BLS and TLS | 17/17 |
| Segments with usable local pixel measurements | 64/79 |
| Hosts with Gaia evidence, including supplement | 17/17 |
| Individual visual-review plots | 79 |

The original bounded Gaia query completed on 16 hosts. TIC 314724818 exceeded
its 2,000-source cap; a separate, provenance-checked supplement recovered all
3,839 returned sources within a larger 20,000-source and 4 MiB bound. The
original run is unchanged. The consolidated event table clears only the two
Gaia-unavailable flags associated with that host.

## Follow-up cases and image checks

The two segments with local aperture S/N >= 5 belong to TIC 154927364:

| Segment | White-noise aperture S/N | Localization issue |
| --- | ---: | --- |
| `TIC154927364-s0040-i12937` | 9.49 | Difference centroid offset at least one pixel |
| `TIC154927364-s0040-i13065` | 7.70 | Difference source not localized |

Both overlap the second BLS solution at 3.33394 days. That solution reaches the
six-hour search-duration boundary and has an odd/even depth difference of 6.75
under the independent-sample error model. This is a reason to inspect
variability, aliases, eclipses and the baseline choice, rather than a planetary
disposition. These nearby segments may describe parts of one broader feature.
The dominant BLS/TLS period on this host is approximately 6.974 days, matching
the existing cohort's TOI-1647.01 period; the 3.334-day overlap must not be
misreported as a match to that known period.

Image spot checks also included the highest-ranked original audit segment,
`TIC437261733-s0036-i17672`. Despite its neural score of 0.934, the local pixel
aperture gives S/N 2.33 and no reliable difference centroid. The reviewed
examples on TIC 184869170 and TIC 229747848 show noisy or varying local flux;
their offset flags alone do not establish contamination by another star.

Across the full queue, flags include 29 overlaps with returned periodic-search
ephemerides, 20 centroid offsets of at least one pixel, and 41 unlocalized
difference sources. These flags overlap, and periodic overlap alone does not
establish significance. No segment has received a planet-candidate or confirmed
planet classification from this workflow.

## Evidence record

- [Committed evidence summary](evidence.json)
- [Methods and remaining research](../../legacy-docs/ai_telescope_research.md)

The original diagnostic report, gallery, and event tables remain in local
ignored outputs under `outputs/research/ai_telescope/`; they are not included in
this archived public snapshot.

All 231 original artifact checksums verified, and every gallery image maps to
one of the 79 unique registered segments. The focused event-vetting/pixel/review
suite passed 19 tests; the prospective membership and scan suite passed eight.
Synthetic checks cover baseline drift, missing pixels, off-target dimming,
two-sided baseline requirements, Gaia source identity and proper motion.

Current registry reconciliation, human astrophysical disposition, correlated
noise controls and continuous-scan injection recovery remain necessary. The
production watcher and its scoring model were not changed by these experiments.
