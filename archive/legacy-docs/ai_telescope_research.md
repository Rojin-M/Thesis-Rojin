# Archive-based AI telescope

The AI telescope ranks events in public TESS target-pixel observations. It does
not control a spacecraft. Its four inputs are aperture light curves, pixel
sequences, pointing/background proxies, and SPOC/TIC header context. The context
is not a Gaia-trained representation; the new Gaia queries support downstream
event review only.

## Existing exploratory evidence

The original 827 usable hosts supplied 4,996 paired windows. Light/pixel
pretraining improved event average precision from 0.5106 for scratch training to
0.5480. Adding instrument and host context produced AP 0.5618 and event recall
0.3803 at a threshold selected on calibration windows. These are measurements on
a reused, validation-derived audit set. Continuous-scan false alarms, planet
classification, and generalization to an unbiased target population were not
established by those scores.

The frozen model subsequently scanned 122,552 regularly spaced windows on the
same 827 hosts. Ephemerides were applied after inference to measure known-signal
recovery, which was 510/861 overall. Duration, common-time and known-secondary
triage produced 79 unmatched audit segments on 17 hosts. Segments are not
necessarily distinct astrophysical events: several can come from one broad
variation, and the segmentation depends on overlapping inference windows.

## Single-event vetting

`scripts.experiments.ai_telescope_event_vetting` consumes the exact frozen audit
queue, verifies its upstream artifacts, and processes all 79 segments. It uses
the existing local TPFs and verified light curves, adding:

- A single-event difference image using the actual segment bounds and midpoint.
  A linear baseline uses nearby data on both sides; other detected segments and
  known primary transits are excluded from baseline fitting.
- Signed aperture depths for the pipeline aperture, a core around the TIC WCS
  position, an expanded aperture, and background where available. Missing
  aperture pixels remain unavailable rather than being silently replaced by zero.
- A difference centroid compared with the TIC WCS position. Pixels must exceed
  a descriptive white-noise S/N of three to enter its positive-flux centroid.
- A bounded Gaia DR3 cone query, retaining exact source IDs, response bytes,
  query text, retrieval time and checksum. Positions are propagated to the
  sector midpoint where proper motions exist and projected onto the stamp.
- Blind BLS and TLS searches once per host, using the full light curve. Matching
  a segment to a returned ephemeris is descriptive; it is not a significance test.
- A plot and evidence record for every segment, including unavailable diagnostics.

The run saves JSON/NPZ evidence, a CSV table, a Markdown report and a standalone
HTML gallery in `outputs/research/ai_telescope/event-vetting-v1/`. Successful
host artifacts have checksummed receipts and can be reused on restart. A
completed workflow can contain explicitly unavailable scientific diagnostics;
the report separates these from successful measurements.

Crowded Gaia cones that exceed the original 2,000-source cap can be recovered
with `scripts.experiments.ai_telescope_gaia_supplement` after the original run
finishes. Its separate, checksummed `gaia-supplement-v1` artifacts retain up to
20,000 sources per cone within the same 4 MiB response bound. The consolidated
event table clears only successfully recovered Gaia-unavailable flags; original
pixel measurements, plots and model outputs stay frozen.

Depth uncertainties assume independent samples. Centroid Monte Carlo fixes the
selected support and omits correlated noise, selection uncertainty and WCS
errors. Offset flags therefore require image review and do not automatically
reject a target. A Gaia positional counterpart within three arcseconds is
provisional; nearby sources alone do not prove contamination, and Gaia G fluxes
are not TESS-band dilution estimates. The cone includes a margin outside the
stamp, but it is not a complete model of contaminating light.

Public data interfaces follow the [ESA Gaia archive query documentation](https://www.cosmos.esa.int/web/gaia-users/archive/writing-queries)
and [MAST TESS product documentation](https://archive.stsci.edu/missions-and-data/tess/data-products).

## Unreviewed-host scan

`scripts.experiments.ai_telescope_prospective` preserves the original frozen
100-host manifest and excludes the 10 hosts examined in the earlier pixel
feasibility pilot. All remaining 90 hosts must be absent from both the physical
expert cohort and every shared-v1 partition. There are no replacement hosts and
no selection by model scores or catalog outcomes.

The experiment freezes its model/checkpoint provenance, threshold, scan geometry,
source hashes, input light-curve hashes, and host list before scanning. Public TPF
sizes are checked before download against an 8 GiB cap. Acquisition receipts and
per-host results support restart; failed acquisitions remain in the registered
denominator. The earlier scan's model and threshold are reused without tuning.

Output lives in `outputs/research/ai_telescope/prospective-v1/`. The report counts
hosts, windows, valid cadences, detected segments and segments within the already
frozen duration prior. These are operational outputs, not accuracy estimates.
This cohort is archival and limited to one cached sector per host; it is not a
random sky sample. It is host-disjoint from development, while the exposure
history of the earlier 10-host subset remains explicit in the specification.

## Continuous-scan injections and controls

`scripts.experiments.ai_telescope_continuous_validation` evaluates the frozen
v2 model on complete sectors rather than centered training windows. Each of 78
calibration and 79 audit hosts receives one condition from a preassigned repeated
grid: 500, 1,000, 2,000 or 5,000 ppm; one, 2.5 or five hours; and a single,
periodic or timing-variable event pattern. A spatially coherent trapezoid is
injected through a robust target-PSF estimate. A second inference uses real
per-pixel residuals inverted around their median as an empirical null control.

Threshold selection uses only calibration controls and counts events inside the
already frozen 0.50-to-7.04-hour duration prior. The lowest predeclared threshold
meeting at most one control event per 27 exposure-days is frozen before audit
aggregation. This selected 0.900000 instead of the original 0.854588. On 1,776
audit exposure-days, the control rate fell from 2.569 to 0.745 per 27 days, while
system recovery fell from 31/79 to 21/79 and event recovery from 60/276 to
41/276. At 0.900000, only 2/25 500-ppm systems and 3/27 single-event systems were
recovered.

This establishes an overlap-aware operating point and quantifies its sensitivity
cost. It also rejects threshold adjustment as a sufficient fix. The inverted
control is not the full astrophysical false-positive population, and the
trapezoidal injections do not replace physical transit models. The results are
in `outputs/research/ai_telescope/continuous-validation-v1/` and summarized in
`results/ai_telescope_continuous_validation_v1/`.

## Continuous-scan-aware v3

`scripts.experiments.ai_telescope_continuous_training` starts from v2 and uses
only training and selection hosts. For each of 670 hosts, it creates one
spatially coherent low-depth single transit and selects the hardest of four
valid inverted-residual windows under v2. Fine-tuning mixes those 1,340 windows
with the original labelled windows; epoch selection uses a predeclared combined
event-AP, injection-AP and hard-control objective on selection hosts.

The complete-sector protocol was then repeated with identical calibration/audit
hosts and injection conditions. Calibration selected threshold 0.86. On audit,
v3 recovered 28/79 systems and 53/276 events while producing 0.517 control
events per 27 exposure-days. v2 recovered 21/79 and 41/276 at 0.745 controls per
27 days. Ten paired hosts improved and three worsened (two-sided exact McNemar
p=0.092). This was the strongest continuous detector result on that reused,
small audit. Single-event recovery remains 4/27 and 500-ppm recovery
5/25. The run is summarized in `results/ai_telescope_continuous_v3/`.

## Frozen physical-injection comparison

`scripts.experiments.ai_telescope_physical_benchmark` compares frozen v2 and v3
with Astropy BLS and TLS on the original 90 development-disjoint hosts. Their
earlier v2 scan is disclosed; "unseen" means excluded from training, checkpoint
selection, and calibration, rather than never processed by any model. Existing
neural thresholds (0.90 and 0.86) are retained. BLS/TLS thresholds use only the
78 original calibration hosts and the same target of at most one inverted
control event per 27 exposure-days, then freeze before evaluation begins.

Each evaluation host receives a preassigned depth (500, 1,000, 2,000 or 5,000
ppm) and one of three equally represented modes: single, periodic, or TTV.
The [batman model](https://lkreidberg.github.io/batman/docs/html/tutorial.html)
uses circular orbits, quadratic limb darkening, synthetic stellar density,
and seven samples per cadence integration. The radius ratio is solved for the
requested instantaneous central depth; actual sampled depth is recorded. A
static empirical median-image template distributes the loss across the pixels.
The template is not a deblended instrument PRF, assumed density and limb
darkening are not measured host parameters, and additional photon noise is not
drawn. TTV shifts are synthetic rather than a dynamical orbital solution.

Both classical searches receive the aperture sum of exactly the same pixel
cube used by the neural light branch, with a declared blind 1.5-day detrending
window and no catalog masks. [TLS](https://transitleastsquares.readthedocs.io/en/latest/Python%20interface.html)
provides the trial-period grid also searched by
[BLS](https://docs.astropy.org/en/stable/timeseries/bls.html); their durations and
shape families differ. Each retains one strongest periodic hypothesis. Neural
models retain all segments meeting their frozen duration prior. This is a
comparison of those bounded pipelines, with separate results for isolated and
timing-variable events, rather than an exhaustive optimization of BLS/TLS.

Original, injected, and inverted observations are searched independently. A
truth event requires at least two good cadences and 50% of its expected in-event
sampling. One-to-one matching uses half the true transit duration. The primary
metric credits only injected-event matches absent on the original observation,
reducing chance matches to existing variations. All registered hosts remain in
the denominator; no search failure may be silently dropped. Raw matches,
incremental matches, multi-event temporal-pattern recovery, host Wilson intervals,
and paired host comparisons are also reported. These matching rules differ from
the earlier trapezoidal audit, so percentages should not be directly compared
between the two experiments.

Model weights, threshold provenance, source files, library versions, cohort,
injection schedule, and input hashes freeze in `spec.json`. Per-case receipts
are checksummed and resumable; `complete.json` is written only after all 78
calibration and 90 evaluation hosts finish. Outputs live under
`outputs/research/ai_telescope/physical-benchmark-v1/`. Empirical inverted alert
rates and alerts on original observations are reported separately; neither
estimates the survey astrophysical false-positive rate.

The completed benchmark recovered additional injected events on 13/90 hosts
with v2, 17/90 with v3, 1/90 with the conservatively calibrated BLS pipeline, and
17/90 with TLS. Their inverted-control event rates were respectively 0.900,
1.369, 0.000 and 0.587 per 27 exposure-days. v3 therefore did not repeat the
earlier simultaneous improvement in recovery and controls, and its calibration
budget did not transfer to this cohort. The v3–v2 paired exact p-value is 0.219.
TLS recovered 88/330 individual events versus v3's 44/330, although v3 found
4/30 registered single-transit systems and TLS found none. Five single-transit
injections lacked sufficient observational coverage; all 90 hosts remain in the
registered denominator. BLS's selected depth-S/N threshold of 100 is conservative;
this result compares the registered pipelines rather than establishing a general
BLS performance limit. See the
[full comparison and figure](../results/ai_telescope_physical_benchmark_v1/README.md).

## Fresh recovery follow-up

A separate follow-up is implemented in
`scripts/experiments/ai_telescope_recovery.py`. It retains v3's weights, adds a
local sideband event search over 0.5–12 hour durations, and calibrates each branch
before evaluating 99 newly frozen hosts. The cohort excludes every earlier
TESS role, the original prospective cohort, Kepler proximity matches, and linked
sky groups. Incomplete apertures fail the new comparison instead of treating
missing pixels as zero flux.

The new calibration selects exact observed-score boundaries for BLS, TLS and
the single-event search. It reserves half the declared rate budget and checks
both a Poisson upper estimate and a host-bootstrap upper estimate. Neural
threshold selection also checks higher thresholds because event grouping can
be nonmonotone. These are operational margins, not a distribution-shift
guarantee. The hybrid splits its budget between the unchanged neural model and
the new event search. This is a detector supplement, not a newly trained v4
neural network. The original 90-host experiment remains sealed.

All 99 fresh hosts completed; 96 had observable injections, totaling 326 events.
Calibrated v3 retains 21/99 incremental host recoveries while reducing inverted
alerts from 0.332 to 0.172 per 27 exposure-days. Individual event recovery falls
from 58 to 53. Both old and new v3 settings meet the alert target on this new
cohort, so this is evidence of a useful operating-point tradeoff, not a universal
calibration-transfer guarantee. Single-transit recovery remains 4/33, and every
method misses all 25 registered 500 ppm injections.

The new single-event search recovers only 2/99 hosts; its hybrid with the more
tightly budgeted neural branch recovers 5/99 with 0.405 inverted alerts per
27 days. This proposal is rejected. TLS recovers 22/99 hosts and 105/326 events
at 0.393 control alerts per 27 days. BLS recovers none under the stricter margin.
Its exact threshold is no longer limited by a coarse grid, but sensitivity is
still inadequate. A calibration-only diagnostic shows that the old empirical
budget would select BLS 72.5968 instead of 100; that diagnostic threshold was
not used to rescore either evaluated cohort. See the
[fresh recovery report and figure](../results/ai_telescope_recovery_v1/README.md).

## Remaining evidence needed

1. Human review, current TOI/planet registry checks, and astrophysical disposition
   of the 307 unseen-host retained segments, including whether several segments
   represent one event.
2. Add background-source and eclipsing-binary injections under separate
   protocols. The frozen physical-transit comparison is complete; it does not
   establish v3 superiority or justify production deployment.
3. Improve low-depth and single-event recovery using training/selection hosts
   only. Existing calibration/audit hosts and the 90-host benchmark remain
   excluded from training. Redesign informed by benchmark outcomes requires a
   fresh confirmatory cohort; neither the original 90 hosts nor the new 99-host
   recovery cohort is now an unexamined test. The sideband/hybrid supplement did
   not solve this limitation.
4. Repeated v3 training seeds and independently retrained modality ablations before stronger
   model-comparison claims, followed by multi-sector tests.
5. Integration into the watcher and website only once the scientific behavior is
   improved and independently validated. These experiment runners do not change
   production scoring.

The reproducible entry points and detached-run commands are recorded in the
machine's personal `forme/COMMANDS.md`; their configurations are under `configs/`.
