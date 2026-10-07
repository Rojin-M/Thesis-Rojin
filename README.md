# Kepler-to-TESS exoplanet discovery pipeline

This repository has been cleaned to keep the active research path readable and reproducible. The public-facing project now focuses on the working thesis narrative, the current model choice, and a small set of frozen evidence artifacts. Older exploratory runs and legacy configs are archived under [archive](archive/README.md) so the active project remains understandable.

## Start here

| Need | Read |
| --- | --- |
| Understand the current thesis story | [Thesis storyline](STORYLINE.md) |
| See the current model decision and evidence gate | [Model journey](MODEL_JOURNEY.md) |
| Inspect the public evidence bundle | [Evidence index](results/README.md) |
| Start or operate the website and watcher | [Website and watcher guide](docs/website_guide.md) |
| Learn the project methods and background | [Research Academy](academy/README.md) |

The active research checkpoint is intentionally small: it keeps the narrative, reproduction configs, and the strongest retained evidence without dragging the repository through every exploratory experiment.

## What is active now

| Path | Purpose |
| --- | --- |
| `configs/` | Active frozen run and protocol configs |
| `results/` | Curated public evidence and compact reproduction bundles |
| `scripts/research/` | Research website, watcher and evidence store |
| `academy/` | Shareable course and project teaching website |
| `docs/` | Setup and operational guides |
| `data/`, `outputs/`, `logs/` | Local-only data, transient outputs and logs; not the public story |
| `archive/` | Archived legacy experiments, configs and result folders |
| `tests/` | Regression and reproduction checks |

The expected public workflow is: choose a model from the model journey, rerun the relevant config, check the stored evidence bundle, then decide whether the new result changes the narrative.

## Research question and current status

> Can a shared transit model transfer from labelled Kepler examples to TESS and support a reproducible blind-search workflow without claiming a new planet discovery?

The project remains a bounded discovery workflow, not a confirmed-survey planet search. The current branch keeps the strongest evidence and frozen project artifacts, while the rest of the exploratory work is archived for provenance rather than active use.

## Continue from this checkpoint

The clean continuation path is:

1. Read [STORYLINE.md](STORYLINE.md) and [MODEL_JOURNEY.md](MODEL_JOURNEY.md).
2. Open the compact evidence list in [results/README.md](results/README.md).
3. Use the active configs in [configs](configs).
4. Reuse the local operational guide in [docs/website_guide.md](docs/website_guide.md).
5. Keep new experimental results in a dated result folder, then add them to the evidence index only if they genuinely change the project story.

This keeps the repo navigable while still allowing legitimate follow-on research.

## Reproducibility and artifacts

The project deliberately separates public evidence from heavy local artifacts. If a result is published in the repo, it should include:

- a frozen config
- a compact evidence summary
- a checksum manifest or hash list
- the minimum prepared inputs or model artifact needed to verify the result
- a short README explaining the cohort and limits

Large raw data and long-running outputs remain local. They are not part of the minimal public thesis story.

## Archive policy

Legacy exploratory configs and old results are stored under [archive](archive/README.md). They are retained for provenance and possible later recovery, but they are not part of the active research path.

## Environment

The reference environment uses Linux, Python 3.9+, and the project environment in `.venv`. Use the commands in the project docs to start the Academy or the research website, then keep all evidence in the compact result folders.

## Validate

Run the offline test suite from the repository root after installing the reference dependencies. This excludes opt-in live-catalog tests:

```bash
env -u RUN_LIVE_CATALOG_TESTS OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
	.venv/bin/python -m unittest discover -s tests -v
```

## Practical next step

The next meaningful research step is to choose one active model decision, freeze its config, and add one new dated result package with a short README and checksum manifest. That gives a readable continuation path without reintroducing the whole experiment backlog.
