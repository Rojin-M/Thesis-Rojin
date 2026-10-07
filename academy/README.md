# Exoplanet Research Academy

A local, shareable course for this thesis project: astronomy and data handling first,
then how ML actually learns, model architectures, current research, candidate
vetting, this repository’s results, and designing a defensible experiment.

Open **http://127.0.0.1:8765/#dashboard**. If you already have an Academy tab,
refresh it. The Research dashboard remains separate on port **8766**.
For the shortest written model history, read the repository's [model journey](../MODEL_JOURNEY.md).

## What the course contains

- **36 lessons in nine ordered units**, each with explanations, three learning
  objectives, a worked example, a project connection and six graded questions.
  Explanations introduce the idea before the notation, and every lesson ends
  with a recap and a common mistake explained. Technical depth and grading
  standards are preserved.
- **12 dedicated ML lessons**: neurons and logits; loss and backpropagation;
  batches, optimizers and overfitting; seeds and reproducibility; CNNs; linear,
  tree and recurrent baselines; attention/Transformers; self-supervision;
  transfer learning; DANN; ensembles/OOD/conformal coverage; recent research.
- **252 authored questions**: 164 single choice, 39 multiple select and 49
  numerical calculations. No essay answers, reflection requirements or
  self-assigned grades.
- **Nine interactive experiments**: transit depth/dilution, folding/aliases,
  base rates, multiple testing, gradient descent, seeds, a sliding convolution,
  attention and DANN gradient reversal. They are teaching simulations, not
  actual telescope analysis or fitted research models.
- Six runnable Python examples, including a tiny synthetic CNN training loop,
  attention arithmetic and a real PyTorch gradient-reversal operation.
- A searchable course map and glossary, source reading desk, project map,
  local gradebook, mistake review, spaced review and progress export/import.
- An **optional, ungraded astronomy research tour** after the capstone: real
  autonomous follow-up, alert brokers, recent exoplanet models and anomaly search.

Using the course or grading answers makes **no paid API calls**. There is no
LLM grader, account, analytics service or external runtime dependency. External
source links open only when you choose to follow them. Running the optional
Python examples requires the project’s local Python environment.

## Study path

| Unit | Lessons | Main skill |
| --- | --- | --- |
| 1. Read the sky | 1–4 | Flux, depth, orbital geometry, missions and impostors |
| 2. Turn data into detections | 5–8 | Arrays, cleaning, folding, BLS, TLS and aliases |
| 3. Learn to trust a result | 9–12 | Noise, metrics, splits, calibration and Bayes |
| 4. How a model learns | 13–16 | Forward pass, loss, gradients, optimization and seeds |
| 5. Choose a model with a reason | 17–20 | CNNs, baselines, Transformers and self-supervision |
| 6. Transfer and the frontier | 21–24 | Transfer, DANN, uncertainty and recent papers |
| 7. Become a careful vetter | 25–28 | Event checks, pixels, validation and our candidate case |
| 8. Understand this repository | 29–32 | Input contract, historical/fresh comparisons, services and backups |
| 9. Develop a research idea | 33–36 | Injections, ablations, literature gaps and study design |

Start with lesson 1 if the astronomy is new. For ML specifically, use
**Go to ML foundations** on the overview, or open
http://127.0.0.1:8765/#unit/learning. The seed lesson is
http://127.0.0.1:8765/#lesson/seeds. Prerequisites are recommended, not hard locks.

A useful session is one lesson: read the mechanism, calculate the example before
revealing its interpretation, change the lab controls, then take the check.
Allow roughly **20–30 hours** for a first pass with practice; reproducing research
and reading the primary papers takes additional time. Course completion measures
these learning objectives; becoming an independent researcher also requires
real analysis, literature work and review with experienced researchers.

## Grading and review

| Assessment | Questions | Passing requirement |
| --- | ---: | ---: |
| Lesson check | 6 | 5 correct (at least 80%) |
| Unit exam | 8 | 6 correct (75%) |
| Final assessment | 27 | 22 correct (at least 80%) |

Unit exams draw one question from each of their four lessons and add four
applied unit cases. The final draws three questions from each unit. Exams reuse
the course bank: this is a learning tool, not a proctored qualification.

Every question has equal weight. Multiple-select answers require the exact set
of correct choices, with no partial credit. Numerical questions display units
and an absolute tolerance: enter only the number, without a percent sign or unit.
Decimal and scientific notation work. A blank is **not** zero. You must answer
all questions with valid responses before receiving a grade.

After submission, every answer gets an explanation and a link to its lesson.
Answers lock for that attempt. Retake to try again with shuffled choices; both
best and latest grades are retained. Mixed practice and review do not award
lesson mastery. There is no manual “mark complete” button.

Letter grades: A ≥90%, B ≥80%, C ≥70%, D ≥60%, F below 60%. Passing thresholds
are assessment-specific, so 6/8 on a unit exam is a passing C. Full course
mastery requires all 36 lesson checks, all nine unit exams and the final.

Missed answers return immediately in **Mistakes & spaced review**. Correct
answers return after 1 day, then 3 days, then 7 days on successive correct
attempts. Review batches contain at most ten questions, prioritizing mistakes.

## Keep your progress and previous notes

Grades, drafts, theme and review timing live in browser localStorage under
`exoplanet-academy:v2`. Use **Grades & progress → Export progress JSON** before
clearing browser data or changing browser/address/forwarded port. Importing a
matching-edition export regrades its stored answers locally before replacement.
A browser with disabled storage can still read lessons and grade answers; export
before leaving to preserve that session.

The old `exoplanet-academy:v1` record is left untouched. If it exists in this
browser, **Export previous Academy notes** preserves the old reflections, idea
forms and progress as JSON. Old manual completion ticks do not become grades in
the redesigned course. The course is self-contained; previous private notebooks
and browser profiles are not required.

The Academy does not automatically back up progress into the Research database,
create a Git commit or push anything. The course assets and authoring source in
`academy/` are versioned in Git.
Personal notes, browser profiles, saved grades, logs and live research data are
not part of this course export.

## Research sources and project facts

Project teaching was refreshed **28 September 2026**. Source access dates are
shown individually in the reading desk; this content date does not imply that
every external link or service policy was reverified.

Open **http://127.0.0.1:8765/#research-updates** for the optional final research
section (about 25 minutes). Navigation, overview, reading desk, final lesson and
final-assessment results all link to it. Eight guided stops explain BTSbot/SEDM,
Rubin brokers, ExoMiner++, unfolded-light-curve Transformers, RAVEN, DESI anomaly
search, critical reading of EXOVEIL/Astro-Hunters and proposed decision-aware AI.
A native workflow selector contrasts new telescope measurements, broker queues
and our archival watcher; ungraded reflections reveal interpretations without
saving answers. Galaxy representation learning and DESC provide wider context.

Each stop includes inputs, mechanism, evidence, limits, project connections and
direct primary links. Dates distinguish events, submissions, revisions, publication
and source access; preprints and proposals are explicit. Figures are native HTML/CSS,
with no remote assets or runtime requests. Selected-study results are attributed,
not independently reproduced or combined into a cross-paper leaderboard.
Deep links use `#research-updates/` followed by `btsbot`, `brokers`, `exominer`,
`transit-search`, `raven`, `anomalies`, `reading-claims` or `next-decisions`.

Open **http://127.0.0.1:8765/#project** for the served evidence snapshot:

- The captured schema-2 archival watcher had **18 selected targets**, a six-hour
  polling interval and at most two products per cycle. The two-control setup is
  explicitly dated September 23; neither represents full archive coverage.
- The authoritative scorer is **frozen_Kepler_shared_v1_CNN_seed42**. Saved
  `model_score` rows from September 26 establish checkpoint/normalizer identity
  as checked September 28. The sigmoid score is not a planet probability.
  Comparison models and research-only event detectors have not replaced it.
- Historical three-seed adaptation results remain visible. Reused 82-row
  classifier comparisons are separated from the fresh 14-candidate audit
  (3 positive, 11 negative). Static v4 ranks better on the fresh cohort;
  nonlinear has 13/14 versus 12/14 correct at threshold 0.5. Of 295 registered
  candidates, 281 lacked native 120-second products; all 14 available passed
  unchanged preparation. This small, selected sample has no universal winner.
- Separate detector tables show the historical 79-host trapezoidal audit,
  90-host physical audit and fresh 99-host recovery study, with registered and
  observable denominators, event counts and inverted-control rates. Calibrated
  v3 loses five events while reducing controls by about 48%; both v3 settings
  already meet the fresh mean budget. The hybrid failed and every method missed
  all 25 fresh 500-ppm injections. These are injections, not new planet discoveries.
- Lessons teach cross-fitting, complementary experts, physical assumptions,
  one-to-one event matching, rejected routing and calibration transfer. Proposed
  contamination, multi-sector and larger classifier studies are labeled as plans.
  The TIC 150428135 case remains a September 23 teaching dossier.

The public snapshot in `source/project_evidence.json` is compiled into course
assets. Copyable provenance paths can be opened in an editor; they are not broken
parent-directory browser links. No database, checkpoints, host list or private
notes are served. Research on port 8766 remains the live-record interface.

**Progress compatibility:** version 2, assessment revision `2026-09-23.1`, all
36 lessons, nine units, 252 question IDs/options/keys/order and the storage key
remain stable. `contentRevision=2026-09-28.3` records editorial changes without
archiving existing grades. Imports/exports remain compatible. The historical
watcher quiz prompt is dated; its options and correct answer are unchanged.

The guided tour and its reviewed source metadata are authored in
`source/research_extension.json` and compiled by `source/build_course.py` into
`curriculum.js`. Keep source IDs stable; extend the optional data, not the lesson
or exam arrays. The reading desk and primary-source lists share the same records.

## Start the Academy

From your clone’s repository root, use Python 3.9 or newer; the website itself
needs only Python’s standard library:

```bash
python3 academy/serve.py --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/#dashboard**. With a remote VS Code session, forward
**8765** in the **Ports** panel, then choose **Open in Browser**. Keep the same
browser and forwarded address to keep using the same locally saved grades.
**Ctrl+C** stops a foreground server. `Address already in use` means an existing
process owns that port; check it before starting another copy.

For both sites, install the research environment from the
[root README](../README.md#environment-and-checks), plus `tmux` and `curl`, then use:

```bash
bash scripts/websites.sh start
bash scripts/websites.sh status
bash scripts/websites.sh restart academy
bash scripts/websites.sh logs academy
```

The helper runs servers in named tmux sessions and reuses healthy sessions.
`restart research` restarts Research alone; `restart` restarts both. `stop`
stops the two website servers. The watcher and comparison worker have their
own lifecycle. See the [website operating guide](../docs/website_guide.md#everyday-commands-for-both-websites)
for ports, old forwards, troubleshooting and worker startup.

Closing the browser does not stop a tmux server. A tmux process survives a
terminal disconnect, but not a host reboot. Static lesson edits are served on
refresh with `Cache-Control: no-store`.

## Files included

- `source/build_course.py`: authored lessons, examples, sources and questions.
- `source/project_evidence.json`: reviewed public metric snapshot and provenance.
- `source/research_extension.json`: optional guided tour and dated primary sources.
- `curriculum.js`: generated course data, ready to serve without a build step.
- `index.html`, `app.js`, `styles.css`, `favicon.svg`: the course interface.
- `grading.js`, `labs.js`: local grading and interactive teaching experiments.
- `serve.py`: the local HTTP server.
- `../tests/test_academy.py`, `../tests/test_academy_grading.cjs` and
  `../tests/test_academy_progress.cjs`: executable checks.

## Maintain and verify the course

Author core content in `academy/source/build_course.py`, reviewed project metrics
and provenance in `academy/source/project_evidence.json`, and optional literature
in `academy/source/research_extension.json`; regenerate the strict
JSON-wrapped `curriculum.js` rather than hand-editing both copies:

```bash
.venv/bin/python academy/source/build_course.py
.venv/bin/python -m unittest tests.test_academy tests.test_websites -v
```

The suite checks curriculum/reference integrity, runs the Python examples,
executes the actual JavaScript grader, math and application progress tests, and
tests HTTP behavior on an ephemeral local port. Install Node 18 or newer to run
the JavaScript grader checks; it is found from
`NODE` or PATH. Without Node that check is explicitly skipped. Node is not
needed to use the website. Socket-restricted environments skip the
HTTP group; run with local sockets available to cover it.

During development, isolated Chromium checks covered all lessons and unit exams,
final assessment,
wrong/missing answers, best/latest scores, drafts across refresh, mistake review,
all nine labs, progress export/reset/import, preserved legacy notes, rejected
imports, mobile layout, theme, keyboard navigation and disabled storage. Browser
profiles and screenshots are not included in the published course.

When changing the meaning or key of an assessment, update `D['revision']` and
verify migration behavior. Earlier-edition records are archived separately;
imports from another edition are rejected instead of silently granting mastery.
Keep source status, project facts, explanations and worked answers consistent.

## Optional extension authoring contract

Edit the existing structure in `source/research_extension.json`: `title`, `lead`,
`minutes`, `sourcePolicy`, `workflows`, `cards` and `sources`. Each card has a
stable `id`, `shortTitle`, `title`, `status`, `hook`, `input`, `mechanism`,
`evidence`, `limit`, `connection`, source IDs in `sources` and lesson IDs in
`lessons`; `related` readings and a `reflection` are optional. Keep IDs stable
so saved links continue to work. The builder merges source records into the
reading desk and compiles the remaining data into `D['researchExtension']`.

The `#research-updates` route stays outside `modules`, `units` and the assessment
bank. Navigation, overview, reading desk, capstone and final results already link
to it. Verify new claims against primary sources and retain cohort denominators,
publication status, limitations and individual access dates. Advance only
`contentRevision` for compatible editorial updates; keep the assessment revision
and answer contract stable. Regenerate, run the checks above with Node and local
sockets available, then refresh the existing server and inspect the changed routes
at desktop and mobile sizes. Static content changes require no service restart.
