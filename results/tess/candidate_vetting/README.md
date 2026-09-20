# Candidate-registry checker control result

This Phase 2 result is a **positive control**, not a discovery claim. On 21 September 2026 local time, the checker received the published TOI-700 d signal parameters for TIC `150428135` and independently refreshed or revalidated its public catalog sources.

| Input or result | Value |
| --- | --- |
| Candidate label | TOI-700.02 |
| TIC | 150428135 |
| Period | 37.4236838 days |
| Epoch | 2458330.486155 BJD-TDB |
| Result | `CONFIRMED_PLANET` |
| Required-source coverage | `COMPLETE` |
| NASA confirmed match | TOI-700 d |
| ExoFOP match | TOI-700.02, `CP` |
| NASA TOI mirror | TOI-700.02, `CP` |

The four source checks succeeded. ExoFOP's TOI and Community Candidate snapshots were conditionally revalidated against files last modified on 20 September 2026; the NASA Planetary Systems and TOI TAP queries returned current responses. The report preserved retrieval times, catalog update fields, response hashes, applied tolerances, and direct-match residuals in [`toi_700_d_control.json`](toi_700_d_control.json).

ExoFOP recorded target-level counts of 3 imaging, 3 spectroscopy, and 16 time-series observations. These counts describe public evidence attached to the target, not a percentage of research completed and not proof that a team is actively observing it now.

The control demonstrates that the implemented path can recognize an already confirmed planet without confusing the other three TOI-700 signals on the same TIC. Unit tests separately cover candidates, community candidates, false positives, false alarms, controversial records, same-host/different-period signals, small-integer aliases, source conflicts, incomplete ephemerides, malformed catalogs, missing sources, and outages.

Re-run the live control from the repository root:

```bash
.venv/bin/python -m scripts.vetting.check_candidate \
  --tic-id 150428135 \
  --candidate-id TOI-700.02 \
  --period-days 37.4236838 \
  --epoch-bjd-tdb 2458330.486155 \
  --duration-hours 3.365
```

The live catalogs can change. New runs therefore belong in ignored `outputs/vetting/`; this committed control records what the sources returned at the timestamp in the JSON file. `UNMATCHED` from this tool would mean only “no compatible record in all required current snapshots,” never “new planet.”
