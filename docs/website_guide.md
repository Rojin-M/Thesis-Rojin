# Research website and automatic watcher guide

The research website displays saved signals, processing jobs and review evidence.
Open **Models** for the model journey and recorded adaptation runs; a candidate
dossier shows the actual active score identity and any fallback reason. The
[written model journey](../MODEL_JOURNEY.md) links every decisive report.
The automatic watcher can discover a bounded set of additional archival TESS
targets and process their public light curves. They are separate processes:
start both to use **Check for new data**.

Run the commands below from the repository root, `Thesis-Rojin`, in your remote
terminal. They assume the `.venv` environment from the [README](../README.md#environment-and-checks)
is installed. A fresh database starts empty; existing records are retained.

## Everyday commands for both websites

The shareable [Academy course](../academy/README.md) uses port **8765**;
its `#project` page teaches the September 28 deployment/evaluation snapshot with
separate classifier and detector tables. Existing Academy grades remain compatible.
The optional final section at **http://127.0.0.1:8765/#research-updates** teaches
BTSbot telescope follow-up, Rubin brokers and recent ML astronomy through a
workflow comparison and cited examples. Reach it from the menu or final lesson;
it does not add assessments or change course completion.

Research uses **8766**. With the project's `.venv`, `tmux` and `curl` installed,
run this helper from the repository root:

| Operation | Command |
| --- | --- |
| Start both, reusing healthy sessions | `bash scripts/websites.sh start` |
| Restart both and release their previous listeners | `bash scripts/websites.sh restart` |
| Restart Academy only | `bash scripts/websites.sh restart academy` |
| Restart Research only | `bash scripts/websites.sh restart research` |
| Check both HTTP services | `bash scripts/websites.sh status` |
| Start/open browser tabs, or print the addresses | `bash scripts/websites.sh open` |
| Read recent logs | `bash scripts/websites.sh logs` |
| Stop both website servers | `bash scripts/websites.sh stop` |
| Stop an old recovery listener on 8767 | `bash scripts/websites.sh stop recovery` |

Logs go to `outputs/academy/server.log` and `outputs/research/server.log`.
Sessions are named `exoplanet-academy` and `exoplanet-research`. They survive
terminal disconnection while the host remains running; they do not restart
automatically after reboot. If a port belongs to an unmanaged process, the
helper reports it for inspection; stop it in its original terminal with Ctrl+C.

The helper manages HTTP servers only. Start the automatic watcher using the
next section and the optional [comparison worker](mission_adaptation_experiments.md#completed-pilot-and-automatic-candidate-comparisons)
separately. Website restarts preserve saved research data and browser grades.

To clear stale VS Code forwards, stop forwarding the old **8765**, **8766** and
**8767** rows in the **Ports** panel, then forward **8765 → local 8765** and
**8766 → local 8766**. Research requires the same local port; use **Change Local
Port** if necessary. Removing a forward and stopping a server are separate
operations. Do not use `tmux kill-server`, which would also stop the workers.

## Start the website and watcher

Choose one start method. Do not start another copy if the services are already
running, and do not run the older metadata-only `watch-serve` alongside the
automatic worker. Inspect existing sessions with `tmux ls`.

For a short interactive session, initialize once and run the website in one terminal:

```bash
.venv/bin/python -m scripts.research init
.venv/bin/python -m scripts.research serve --host 127.0.0.1 --port 8766
```

Run the worker in a second terminal, also at the repository root:

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv/bin/python -u -m scripts.research watch-auto-serve \
  --config configs/research_discovery_v1.json
```

These foreground processes print logs in their terminals. **Ctrl+C** stops the
process in that terminal. The worker finishes its bounded current cycle before
exiting, so a stop can take several minutes.

For work that should continue after disconnecting, use these named tmux sessions:

```bash
mkdir -p outputs/research
.venv/bin/python -m scripts.research init
if ! tmux has-session -t exoplanet-research 2>/dev/null; then
  tmux new-session -d -s exoplanet-research -c "$PWD" \
    'exec .venv/bin/python -u -m scripts.research serve --host 127.0.0.1 --port 8766 >> outputs/research/server.log 2>&1'
fi
if tmux has-session -t exoplanet-watcher 2>/dev/null; then
  printf '%s\n' 'Stop the older metadata-only watcher before starting the automatic worker.'
elif ! tmux has-session -t exoplanet-auto-watcher 2>/dev/null; then
  tmux new-session -d -s exoplanet-auto-watcher -c "$PWD" \
    'exec env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python -u -m scripts.research watch-auto-serve --config configs/research_discovery_v1.json >> outputs/research/automatic-watcher.log 2>&1'
fi
```

Repeating this block reuses those existing session names. Services started in
other terminals still need to be checked separately. A running tmux session alone
does not establish worker health; inspect `watch-status` below.
If the existing worker uses the older two-control configuration, stop it and
wait for it to exit before rerunning this block. Reusing its session does not
change the running configuration.

To view a session, use `tmux attach -t exoplanet-auto-watcher`. Detach without
stopping it by pressing **Ctrl+B**, releasing both keys, then pressing **D**.
The services continue after VS Code or SSH disconnects while the server and
sessions stay running. These commands do not arrange automatic startup after a
server reboot. Saved results remain on disk.

## Connect through VS Code

1. In the remote VS Code window, open the **Ports** panel and choose **Forward a Port**.
2. Enter remote port **8766**.
3. Ensure its **Forwarded Address** uses local port **8766** too. If VS Code assigns
   another local port, right-click the row and choose **Change Local Port**, then
   set **8766**. Free any conflicting local application or old forward first.
4. Use **Open in Browser**, or open [the dashboard](http://127.0.0.1:8766/#overview).

The server checks the browser's host and port. Use `http://127.0.0.1:8766` or
`http://localhost:8766`; a different local port is not supported with this server
configuration. Recreate the forward after reconnecting to the server. Closing a
forward only disconnects the browser; it does not stop the server-side watcher.
The separate learning Academy uses port **8765**.

## Find your way around

| Page | What to use it for |
| --- | --- |
| [Overview](http://127.0.0.1:8766/#overview) | Counts, recent jobs, watcher status and an immediate data check. |
| [Candidates](http://127.0.0.1:8766/#candidates) | Sort proposals by CNN score, added date, review update, period or target; filter by cohort, review and registry state. |
| Candidate dossier | Inspect light curves, period/epoch, CNN score, catalog evidence and missing checks; save human review notes or export JSON/Markdown. |
| [Watcher](http://127.0.0.1:8766/#watcher) | Discovery scope and selected TICs, worker heartbeat, check requests, archive polls, processing queue, errors and remaining budget. |
| [Jobs](http://127.0.0.1:8766/#jobs) | Inspect each processing stage and recorded failures. |
| [Models](http://127.0.0.1:8766/#experiments) | Read recorded experiment status and available comparison reports. |
| [Protocol](http://127.0.0.1:8766/#protocol) | Inspect the saved research protocol and operating limits. |

## Sort and filter candidates

**Candidates** opens with **Highest CNN score** across all cohorts. This is a
review ranking, not a claim that the first row is the most likely real planet.
Use the **Archival proposals · highest CNN score** shortcut to focus on the
archival cohort, or the adjacent unmatched shortcut to combine that cohort with
the latest recorded `UNMATCHED` registry status. Unmatched does not prove novelty.

The **Sort by** menu also offers lowest CNN score, newest/oldest added, recently
updated review, shortest/longest period and target ID. Sorting applies to all
matching database records before pagination. Combine it with **Cohort**,
**Review status** and **Registry status**, then select **Apply filters**. Applying
filters returns to the first page; next/previous pages and automatic refresh
keep the selection. The page URL preserves the selected options for bookmarks.

**Added · local time** is when this proposal was saved in the research database,
shown in your browser's local time. It is not the date of the light-curve
observation or archive release. **Recently updated review** uses the candidate's
saved review update time; newly created candidates initially use their creation
time. The Overview's **Recent candidate dossiers** stays newest-first and also
shows the Added date.

## Use the vetting helper

The research website already has an **automated vetting helper inside each
candidate dossier**. Open **Candidates**, choose the appropriate cohort, and
click a target. The helper combines the trained CNN ranking with catalog checks,
diagnostic measurements and plots, review flags, and an evidence checklist.
The automatic worker saves this evidence when processing a new product;
opening the dossier displays the saved results.

Use **Review attention** to find flags, **Light curves & diagnostic plots** to
inspect the signal, and **Evidence checklist** to see completed and missing
checks. The CNN score is a ranking score, not a calibrated planet probability.
Missing evidence remains visible even when processing has succeeded.

The candidate list has a separate **Probability / experimental benchmark**
column. Open a dossier's **Probability and benchmark estimate** card for its
scope, calibration identity, audit metrics and supporting provenance.
**Planet probability: unavailable** means the project has no validated estimate
of this signal's actual chance of being a planet.

An **Experimental TESS benchmark estimate**, when available, applies temperature
scaling to the same retained reference CNN's logit. Its temperature is fitted on
81 labelled TESS validation rows and evaluated on 82 separate audit rows.
These curated inputs use known catalogue periods and epochs, with CP/KP as the
positive class. Their population and input construction differ from blind-search
proposals. A displayed percentage therefore describes the experimental benchmark
estimate; it is **not the target's planet probability**, a confirmation, or a
confidence interval. The raw CNN ranking and human review remain unchanged.

An unavailable benchmark estimate includes its reason. Missing or incompatible
calibration/model provenance must not be replaced with a guessed percentage.
To inspect the reference-calibration reproduction command and its options, run:

```bash
.venv/bin/python -m scripts.experiments.calibrate_reference --help
```

The **Experimental model comparison** card now shows TESS-only, Kepler-only,
fine-tuned, pooled and DANN scores from the completed three-seed pilot. They are
additional rankings on the same saved input. The original reference CNN remains
the main score: DANN did not demonstrate an improvement in this pilot. Neither
score means planet probability. The **Models** page shows the completed study
and the automatic comparison service's heartbeat. While that service is running,
newly completed watcher jobs receive these comparisons automatically. See the
[comparison commands](mission_adaptation_experiments.md#completed-pilot-and-automatic-candidate-comparisons).

### What to do after UNMATCHED

`UNMATCHED` means no compatible record was found in the supported catalog
snapshots checked. It does not establish a new planet. Follow the project's
human-vetting checklist:

1. Inspect the original and folded light curves and individual events. Check
   whether repeated dips support the proposed period.
2. Review the odd/even, secondary-event, period-alias and coverage diagnostics;
   record possible variability or instrumental explanations.
3. Check the missing source-localization evidence. Native centroid measurements
   and crowding estimates are partial; difference images, nearby-source checks
   and aperture comparisons still need additional work.
4. Seek independent evidence in other sectors and extend the catalog/literature
   review. Coordinate, TCE, eclipsing-binary and literature searches are outside
   the current automated checker's coverage.
5. In **Human review**, select **in review** or **on hold**, enter your reviewer
   name and evidence/reasoning, and click **Save review**. Record what remains
   unresolved; export the report for another reviewer before deciding on follow-up.

The helper supports human vetting; complete scientific validation remains
unfinished. Its existing CNN inference and diagnostics run locally without paid
LLM API calls. Conversational AI Q&A has **not** been added to either the research
website or the Academy; that remains a possible later addition.
See [scoring and vetting details](scoring_vetting.md) for the implemented methods
and their limits.

## Check for new data

On **Watcher** or **Overview**, click **Check for new data**. The request is saved
for the automatic worker. With the discovery configuration, it requests a new
bounded target-discovery check while selection capacity remains, plus processing
of eligible selected products. A full selection reuses its saved target list;
processing may take several minutes. Its status moves
from **queued** to **running**, then **succeeded** or **failed**. Expand recorded
errors or the latest cycle for details. Repeated clicks reuse a pending request.

The equivalent terminal command is:

```bash
.venv/bin/python -m scripts.research watch-auto-check
```

The discovery worker checks archive metadata every **six hours**, even with the
browser closed. Existing eligible queue work is processed on every worker cycle;
it does not wait six hours for another metadata check. A newly selected,
unprocessed product can lead to blind BLS signal detection, trained CNN scoring,
diagnostic/catalog checks and saved dossiers in the `archival_pilot` cohort.
A successful check may find no new products or save no additional proposals.
Existing completed products are reused rather than creating duplicate signals.

**Refresh results**, browser reload, and the automatic **30-second** list refresh
read saved results. They do not request another archive check. Automatic refresh
runs on Overview, Candidates, Jobs and Watcher while the page is visible and idle;
editing filters pauses it. Candidate review pages do not automatically refresh,
so unsaved notes stay in place.

## Where logs and results live

The website already exposes persisted activity: **Watcher → Recent polls and
observed changes** shows actual archive checks; **Finite acquisition and
processing queue** shows products, attempts and errors. Open **Jobs → a job →
Audit history** for stage attempts and events. A candidate dossier contains its
evidence and human review history. These views read the database, not raw text logs.
The discovery card, backed by `automation.discovery`, shows the latest selection,
selected TIC IDs, bounded source scope, remaining budget, exhaustion and errors.
“Latest batch that added targets” is the last selection event, not a new batch
on every refresh. Selected targets are not completed products or proposals.
The discovery budget is a selection-time snapshot; the global budget includes
later charges. Selection exhaustion allows the remaining selected products to
finish, at most two per cycle, but does not authorize another batch beyond the
cumulative 20-product cap.

| Location | Contents |
| --- | --- |
| `outputs/research/automatic-watcher.log` | Automatic cycles, archive results, dispatch outcomes, `new_candidates` counts and errors. |
| `outputs/research/server.log` | Research website HTTP requests, response codes and server errors. |
| `outputs/research/research.sqlite3` | Durable job, proposal, evidence, review, poll, request and budget records. |
| [results/automatic_watcher_run/](../results/automatic_watcher_run/README.md) | Historical 23 September two-control run: summary, real-data proposals, chronological activity and validation. |
| [Archived 25 September target search](../archive/legacy-results/new_target_search_20260925/README.md) | Dated 18-target selection and first processing results beyond the historical controls. |

`outputs/` is intentionally ignored by Git. Runtime files keep growing and may
contain machine-specific paths or review notes. `results/` holds compact,
reviewed snapshots suitable for committing; it is not updated automatically by
the worker. Earlier result folders remain historical snapshots with their
original counts. The separate Academy's local log is `outputs/academy/server.log`.

The [frozen vetting dataset](../results/vetting_snapshot_20260923/README.md)
preserves a full database snapshot and its referenced files in Git. It includes
plot data, evidence history, catalog snapshots, processing records, input light
curves and the retained CNN/normalizer. Future watcher results and review notes
need a new snapshot; pushing only source code does not back them up.
The main README contains the complete
[backup, restore-check, commit and push commands](../README.md#back-up-and-push-new-vetting-data).
New watcher downloads are saved under `outputs/research/watcher/products/`,
not automatically added to tracked processed datasets in `data/`. The watcher
does not create new `results/` snapshots or push to GitHub.

A metadata log entry with `status: "not_due"` means the next scheduled archive
check is not due. The same worker cycle can still process existing eligible
queue entries, so `not_due` does not establish that the whole cycle was idle.
Check the discovery/poll result or Watcher's last successful poll time to see
when MAST was actually queried, and the queue and dispatch results to see what
was processed. `new_candidates: 0` can be normal; refreshing the page also does
not launch detection.

## Useful status, log and stop commands

```bash
.venv/bin/python -m scripts.research status
.venv/bin/python -m scripts.research watch-status
tmux ls
tail -n 60 outputs/research/server.log
tail -n 60 outputs/research/automatic-watcher.log
tail -F outputs/research/automatic-watcher.log
```

The log files above are written by the tmux start commands. **Ctrl+C** exits
`tail -F` without stopping the worker. `status` reports saved counts;
`watch-status` includes `automation`, its `discovery` status, the latest check
request, poll history, queue errors and cumulative resource use.

Stop either tmux service independently:

```bash
tmux send-keys -t exoplanet-auto-watcher C-c
tmux send-keys -t exoplanet-research C-c
```

Use only the line for the service you intend to stop. Before restarting the
worker, wait for `watch-status` to report `automation.service_state: "stopped"`
and for its tmux session to end. Then rerun the tmux start block.

## Loading, connection and worker problems

- **Browser cannot connect:** confirm the website process is running and check
  `http://127.0.0.1:8766/api/health` in the browser. In VS Code, remove the stale
  forward and recreate remote **8766 → local 8766**. Use that row's browser action.
- **Page stays on loading:** hard-refresh with **Ctrl+Shift+R** on Windows/Linux
  or **Cmd+Shift+R** on Mac. Use **Check server connection** or **Retry loading**
  if offered, then inspect the server log and port mapping.
- **`Unrecognized Host` error:** check that the browser address uses `127.0.0.1`
  or `localhost` and port **8766**, matching the server's configured port.
- **Check button disabled / worker stopped or stale:** use `watch-status` and the
  worker log. A stale heartbeat means its running state is unverified. Confirm
  whether the original process is alive before restarting; do not launch a second
  worker to work around its lock.
- **Check failed, paused or no new candidates:** inspect the Watcher error,
  source completeness, queue, retry time and budget. Archive/network failures
  and exhausted limits remain visible. A requested check bypasses metadata
  scheduling/backoff, but preserves failure circuits, processing retry deadlines
  and resource limits. A normal successful check can return zero new signals.

## Discovery scope, limits and interpretation

The commands above use
[research_discovery_v1.json](../configs/research_discovery_v1.json):
`schema_version: 2`, `targets: []`, a `discovery` settings object and
`cohort: "archival_pilot"`. This configuration selects additional targets from a
bounded public standard SPOC metadata search. An empty configured target list
means discovery supplies the targets; the selected IDs appear in the discovery
card. This is an archival pilot beyond the existing controls, not a search of
all TESS pixels or a complete archive census.

Selection excludes TIC IDs already present in the local processed/raw TESS
sources, the recorded Kepler overlap, and local candidate IDs. Known periods
and epochs do not choose targets or seed blind detection. The live source is
TESS; Kepler data supports the trained-model work and overlap exclusions.

The older [research_automation_v1.json](../configs/research_automation_v1.json)
remains the schema-1 explicit list for **TIC 231663901** and **TIC 150428135**.
Those saved results are historical known-object controls. Use the cohort filter
to distinguish them from `archival_pilot` proposals and synthetic fixtures.

**Stop the worker and wait for it to exit before changing its configuration.**
Restart it with the desired `--config` path. Do not change source code or
configuration during an active processing cycle: product pilots preserve their
original code/configuration identities.

A cycle handles at most two products. The **20-product and 20-target initial
selection limits and 2 GiB byte limit are cumulative across the database**,
including the earlier control run. Its two selected products/targets leave at
most **18 new product/target slots**, with remaining bytes potentially imposing
a tighter bound. Restarts and repeated checks do not reset consumed budget or
previous attempts. Discovery exhaustion, source errors and budget exhaustion
remain visible in the discovery card.

These are signal proposals for review. CNN scores rank evidence, and an unmatched
catalog result does not establish novelty. Control detections are not newly
discovered planets; full survey validation and confirmation remain outstanding.
See [watcher details](release_watcher.md) for provenance, retry and budget rules.
