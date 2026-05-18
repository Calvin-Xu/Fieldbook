## Why

ML research experiments increasingly span many training jobs, follow-up eval
jobs, artifacts, retries, and analysis passes. Chat history and ad hoc Markdown
logs are not a reliable source of truth for what ran, what failed, where the
results live, or how a collaborator-facing table was produced.

Fieldbook should provide a local-first experiment ledger that coding agents use
on behalf of researchers to recover context, refresh experiment state, preserve
provenance, and export reproducible research artifacts across ML repos, with
Marin as the first dogfood target.

## What Changes

- Add a portable Fieldbook MVP centered on a repo-local SQLite ledger under
  `.experiments/`.
- Add a deterministic CLI for initializing the ledger and recording/querying
  experiments, runs, jobs, artifacts, metrics, and notes. Humans may run the
  CLI, but the primary consumer is a coding agent.
- Add an agent-facing workflow for context switching back to an experiment:
  status summaries, stale/failed job visibility, missing artifact visibility,
  next-action notes, targeted drilldowns, and JSON output.
- Add namespaced custom fields so project-specific metadata can be stored
  without hardcoding Marin into the core schema.
- Add provenance-oriented exports so CSV/JSON artifacts can be shared with
  collaborators while retaining checkpoint, W&B, command, and source-job
  pointers.
- Add a first reconcile-oriented workflow that can inspect external systems and
  propose or apply ledger updates, reducing drift when a job was launched
  outside Fieldbook.
- Add Marin-inspired fixtures under tests, while keeping Marin-specific fields
  in namespaced attributes and outside the core schema.
- Defer background polling, admin dashboards, full W&B two-way sync, and
  scheduler ownership.

## Capabilities

### New Capabilities

- `ledger-core`: Local SQLite ledger initialization, schema management, and
  CRUD/query behavior for experiments, runs, jobs, artifacts, metrics, notes,
  and namespaced custom fields.
- `agent-workflow`: Agent-facing commands and conventions for context
  switching, status summaries, stale/failed job discovery, and next-action
  handoffs when humans drive research through natural language.
- `provenance-export`: Export of run and metric tables with provenance columns
  suitable for collaborators and custom dashboards.
- `reconcile`: Refresh/reconcile workflow for detecting external job/artifact
  state and updating or proposing updates to the ledger.

### Modified Capabilities

None.

## Impact

- New Python package and CLI for Fieldbook.
- New SQLite schema and migrations under the Fieldbook repository.
- New OpenSpec-backed development workflow for Fieldbook itself.
- Draft portable agent skill guidance in this change; stable skill packaging is
  deferred until after the CLI and schema are dogfooded.
- Marin is affected only as an integration target and source of realistic
  examples. Marin-inspired fixtures should live under `tests/fixtures/marin/`;
  Fieldbook core must remain ML-repo agnostic.
