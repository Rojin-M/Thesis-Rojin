# TLS and target-pixel feasibility pilot v1

This prespecified run evaluated the first 10 hosts in the frozen prospective
cohort. It downloaded one matching public SPOC target-pixel file per host,
verified byte identities, ran catalog-blind BLS and TLS, and produced aperture
photometry and difference images around both inferred ephemerides.

- Targets completed: **10/10**, with no failures.
- Public target-pixel bytes: **672,851,520** across 10 files.
- Median end-to-end target runtime: **25.2 seconds**.
- BLS/TLS period-and-epoch agreements: **3/10**.
- Raw TPFs: `data/raw/tess/target_pixels/`.
- Receipts: `data/raw/tess/metadata/target_pixel_receipts/`.
- Full local evidence: `outputs/research/tls_pixel_pilot/pilot-v1/`.

TIC 164786087 is the clearest follow-up from this feasibility sample: BLS and
TLS independently recovered about 4.081 days, both sampling gates passed, TLS
SDE was 13.11, the odd/even mismatch was 0.85 sigma, and both difference-image
centroids were within about 0.4 pixel of the reference source. This is a
candidate-like diagnostic pattern, not a validation or confirmation.

TIC 369480087 also had BLS/TLS agreement near 1.093 days, but at lower signal
strength. TIC 136916387 agreed near 11.8 days but failed the two-detector
sampling gates and showed a roughly 1.15-pixel difference-image displacement
with background dimming, so it is deprioritized.

The remaining hosts did not have matched BLS/TLS ephemerides in this run.
Some BLS solutions were outside TLS's stricter two-transit period support; the
pipeline now uses a shared period ceiling for future comparisons.

The pixel centroid uncertainty is a pixel-noise Monte Carlo approximation.
These ten hosts have no labels, so this run validates data flow and generates
physical diagnostic features; it does not train or measure the accuracy of a
pixel expert. A learned supermodel integration requires a frozen, host-disjoint
labelled TPF cohort and calibration before prospective scores are viewed.
