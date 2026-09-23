# Research website and automatic watcher guide

The research website displays saved signals, processing jobs and review evidence.
The automatic watcher checks the configured TESS targets and processes new public
light curves. They are separate processes: start both to use **Check for new data**.

Run the commands below from the repository root, `Thesis-Rojin`, in your remote
terminal. They assume the `.venv` environment from the [README](../README.md#environment)
is installed. A fresh database starts empty; existing records are retained.

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
  .venv/bin/python -u -m scripts.research watch-auto-serve
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
    'exec env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python -u -m scripts.research watch-auto-serve >> outputs/research/automatic-watcher.log 2>&1'
fi
```

Repeating this block reuses those existing session names. Services started in
other terminals still need to be checked separately. A running tmux session alone
does not establish worker health; inspect `watch-status` below.

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
| [Candidates](http://127.0.0.1:8766/#candidates) | Filter saved signal proposals by cohort and review state; open a target's dossier. |
| Candidate dossier | Inspect light curves, period/epoch, CNN score, catalog evidence and missing checks; save human review notes or export JSON/Markdown. |
| [Watcher](http://127.0.0.1:8766/#watcher) | Watched TICs, worker heartbeat, check requests, archive polls, processing queue, errors and remaining budget. |
| [Jobs](http://127.0.0.1:8766/#jobs) | Inspect each processing stage and recorded failures. |
| [Models](http://127.0.0.1:8766/#experiments) | Read recorded experiment status and available comparison reports. |
| [Protocol](http://127.0.0.1:8766/#protocol) | Inspect the saved research protocol and operating limits. |

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

### What to do after UNMATCHED

`UNMATCHED` means no compatible record was found in the supported catalog
snapshots checked. It does not establish a new planet. Follow the project's
[human-vetting checklist](../README.md#human-vetting-boundary):

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
for the automatic worker; processing may take several minutes. Its status moves
from **queued** to **running**, then **succeeded** or **failed**. Expand recorded
errors or the latest cycle for details. Repeated clicks reuse a pending request.

The equivalent terminal command is:

```bash
.venv/bin/python -m scripts.research watch-auto-check
```

The default worker also checks public availability every **six hours**, even
with the browser closed. A new, unprocessed product can lead to blind BLS signal
detection, trained CNN scoring, diagnostic/catalog checks and saved dossiers.
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

| Location | Contents |
| --- | --- |
| `outputs/research/automatic-watcher.log` | Automatic cycles, archive results, dispatch outcomes, `new_candidates` counts and errors. |
| `outputs/research/server.log` | Research website HTTP requests, response codes and server errors. |
| `outputs/research/research.sqlite3` | Durable job, proposal, evidence, review, poll, request and budget records. |
| [results/automatic_watcher_run/](../results/automatic_watcher_run/README.md) | Published 23 September snapshot: summary, real-data proposals, chronological activity and validation. |

`outputs/` is intentionally ignored by Git. Runtime files keep growing and may
contain machine-specific paths or review notes. `results/` holds compact,
reviewed snapshots suitable for committing; it is not updated automatically by
the worker. Earlier result folders remain historical snapshots with their
original counts. The separate Academy's local log is `forme/academy_web/server.log`.

A log entry with `status: "not_due"` means the worker is waiting for the next
scheduled archive poll. An automatic cycle marked `succeeded` can contain only
that idle tick. Check the poll result or Watcher's last successful poll time to
see when MAST was actually queried. `new_candidates: 0` is normal when nothing
new was processed; refreshing the page also does not launch detection.

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
`watch-status` includes `automation`, the latest check request, poll history,
queue errors and cumulative resource use.

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
  and exhausted limits remain visible. Clicking again does not bypass retry or
  resource limits. A normal successful check can also return zero new signals.

## Watchlist, limits and interpretation

Settings are in [research_automation_v1.json](../configs/research_automation_v1.json).
The defaults watch **TIC 231663901** and **TIC 150428135**, known-object controls.
Use the cohort filter to distinguish these signals from synthetic fixtures.
The live stream is TESS; Kepler data supports the trained-model work.

To change the list, **stop the worker and wait for it to exit before editing**.
Set `targets` to 1–20 distinct numeric TIC strings; use `cohort: "archival_pilot"`
for an exploratory archival list. Restart the worker to load the configuration.
Do not change source code or configuration during an active processing cycle:
product pilots preserve their original code/configuration identities.

The watcher observes the latest public standard SPOC light curve for each listed
TIC. It does not expand the target list or search all TESS pixels. A cycle handles
at most two products. The **20-product/target and 2 GiB cumulative limits** persist
across restarts; restarting does not reset consumed budget or previous attempts.

These are signal proposals for review. CNN scores rank evidence, and an unmatched
catalog result does not establish novelty. Control detections are not newly
discovered planets; full survey validation and confirmation remain outstanding.
See [watcher details](release_watcher.md) for provenance, retry and budget rules.
