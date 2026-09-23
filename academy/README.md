# Exoplanet Research Academy

A local, shareable course for this thesis project: astronomy and data handling first,
then how ML actually learns, model architectures, current research, candidate
vetting, this repository’s results, and designing a defensible experiment.

Open **http://127.0.0.1:8765/#dashboard**. If you already have an Academy tab,
refresh it. The Research dashboard remains separate on port **8766**.

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
| 8. Understand this repository | 29–32 | Input contract, finished DANN results, services and backups |
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

The reading desk was checked **23 September 2026**. It includes foundational
CNN/DANN/attention/calibration sources and recent ExoMiner++, Transformer transit
search, RAVEN and 2026 RAVEN survey work. The June 2026 EXOVEIL and August 2026
Astro-Hunters manuscripts are explicitly labeled preprints, with their selection
and sample-size limits. This is a curated reading path, not an exhaustive
leaderboard; external publications and documentation can change.

Project facts are a **dated teaching snapshot**, not a live feed:

- The watcher checks two configured TESS control targets, not the whole archive.
- The five-arm, three-seed DANN pilot is complete. DANN mean audit AP was 0.6934,
  pooled 0.7067 and fine-tuned 0.7644 on the same 82-row pilot audit. No DANN
  benefit was demonstrated; convergence was not established at the short budget.
- The original reference CNN stays primary; comparison scores are appended with
  provenance. The 44 stored comparison proposals include real and synthetic
  controls; they are not 44 new planets.
- Unmatched is a limited catalog-check result. The highlighted 25.3244-day signal
  has unresolved timing/source evidence and no established planet probability.
- Live watcher updates are automatic; dated snapshots and remote backups are
  separate explicit operations.

The **Your project** page links each pipeline stage to a lesson and gives local
paths for the source, result receipts and operating guide. For live status and
candidate dossiers, open Research on port 8766. For watcher and backup commands,
use `docs/website_guide.md` and the snapshot guide it references.

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
[root README](../README.md#environment), plus `tmux` and `curl`, then use:

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
- `curriculum.js`: generated course data, ready to serve without a build step.
- `index.html`, `app.js`, `styles.css`, `favicon.svg`: the course interface.
- `grading.js`, `labs.js`: local grading and interactive teaching experiments.
- `serve.py`: the local HTTP server.
- `../tests/test_academy.py` and `../tests/test_academy_grading.cjs`: executable checks.

## Maintain and verify the course

Author content in `academy/source/build_course.py`; regenerate the strict
JSON-wrapped `curriculum.js` rather than hand-editing both copies:

```bash
.venv/bin/python academy/source/build_course.py
.venv/bin/python -m unittest tests.test_academy tests.test_websites -v
```

The suite checks curriculum/reference integrity, runs the Python examples,
executes 15 tests against the actual JavaScript grader and math functions, and
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
