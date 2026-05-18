# Fieldbook

Fieldbook is a local-first experiment ledger for AI research agents.

It is meant for ML research projects where experiments span many training jobs,
follow-up eval jobs, result artifacts, notes, and retries. The goal is not to
replace the training orchestrator, W&B, or custom analysis dashboards. The goal
is to give coding agents a durable source of truth for what was launched, what
finished, what failed, where the data lives, and what should happen next.

Fieldbook is agent-first. The expected interaction model is that a human gives
natural-language research direction, and a coding agent uses Fieldbook to
record jobs, refresh state, preserve provenance, export tables, and recover
context after switching experiments. Humans can run the CLI directly, but the
CLI and outputs are optimized for agents.

## Motivation

Modern ML research often has more live state than fits in one conversation:

- long-running jobs can finish or fail while the researcher works on another
  direction;
- follow-up evals may be launched days after the original training run;
- result tables need reproducible provenance, not just copied CSVs;
- debugging history matters when deciding whether to retry, skip, or trust a
  datapoint;
- collaborators need artifact exports that can be traced back to checkpoints,
  W&B runs, commands, and code revisions.

Fieldbook is designed around that workflow. It should be small enough to drop
into any ML repo, but structured enough that agents can recover context without
re-reading a long chat transcript.

## Intended Shape

Fieldbook will provide:

- a repo-local SQLite database, stored under `.experiments/`;
- a deterministic CLI for recording and querying experiments, runs, jobs,
  artifacts, metrics, and notes;
- compact agent-facing status summaries for context switching;
- machine-readable JSON for agent workflows and concise text summaries for
  human review;
- provenance-preserving CSV/JSON exports for collaborators and dashboards;
- a portable skill that teaches coding agents how to use the ledger;
- optional project-specific adapters, with Marin as the first target.

The database is the local source of truth. External systems such as W&B, Iris,
GCS, Slurm, or cloud storage are recorded as linked systems and artifact
pointers. Fieldbook may sync summaries to W&B, but it should not depend on W&B
as the only source of provenance.

## Non-Goals

The initial version will not include:

- a background polling daemon;
- an admin web UI;
- a replacement for MLflow, W&B, or a job scheduler;
- automatic ingestion of every metric time series;
- a Marin-only schema.

Custom dashboards should be built from the SQLite database and exported tables.
An admin UI can come later if the CLI and schema prove useful.

## Core Concepts

- **Experiment**: a research thread or question, such as "300M raw-PPL SNR" or
  "MoE mixture scaling ladder".
- **Run**: a scientific datapoint, model, mixture, or configuration whose
  provenance and metrics are tracked.
- **Job**: an execution attempt that trains, evaluates, collects, exports, or
  repairs one or more runs.
- **Artifact**: a durable pointer to a checkpoint, result file, plot, CSV,
  report, W&B run, or debug log.
- **Metric**: a summary observation tied to a run and usually backed by an
  artifact or external system.
- **Note**: a structured research, debug, or handoff entry.
- **Reconcile**: a refresh operation that inspects external systems and
  proposes ledger updates, reducing drift when humans or agents forget to log
  a job at launch time.

## First Implementation Phase

The first phase is tracked in OpenSpec under:

`openspec/changes/bootstrap-fieldbook-mvp/`

That phase should establish the portable MVP:

- initialize a local ledger;
- create and inspect experiments;
- record runs, jobs, artifacts, metrics, and notes;
- summarize active experiment state;
- support coding-agent context recovery through compact status, targeted
  drilldowns, next-action notes, and JSON output;
- support namespaced custom fields for repo-specific metadata;
- provide a first reconcile path for Marin-style manually launched jobs;
- export collaborator-ready tables with provenance columns.

The first implementation phase intentionally keeps the agent skill as a draft
usage guide. Publishing a stable, reusable skill is a follow-up once the CLI and
schema have been dogfooded.

## Why "Fieldbook"?

A fieldbook is where researchers keep observations, coordinates, sketches,
measurements, and follow-up notes while work is still in progress. That is the
role this project should play for agent-led ML research: practical, local,
portable, and reliable enough to return to after context switches.
