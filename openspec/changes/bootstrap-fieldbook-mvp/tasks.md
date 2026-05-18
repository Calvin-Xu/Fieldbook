## 1. Project Skeleton

- [ ] 1.1 Create Python package structure with a `fieldbook` CLI entry point.
- [ ] 1.2 Add `pyproject.toml` with Python version, test configuration, and minimal runtime dependencies.
- [ ] 1.3 Add repository defaults for formatting, tests, and generated local state ignores.

## 2. Ledger Storage

- [ ] 2.1 Implement ledger path resolution with default `.experiments/ledger.sqlite`.
- [ ] 2.2 Implement `fieldbook init` to create the database, set WAL mode, and record schema version.
- [ ] 2.3 Add SQL-only migration infrastructure with numbered migrations, transactionality, and `PRAGMA user_version`.
- [ ] 2.4 Implement type-prefixed ULID-compatible stable sortable ID generation for core entities.
- [ ] 2.5 Enable SQLite foreign keys on every connection.

## 3. Core Schema

- [ ] 3.1 Add tables for experiments, runs, experiment-run links, jobs, artifacts, metrics, notes, reconcile events, and external sync events.
- [ ] 3.2 Add first-class columns for identity, status, timestamps, deleted state, and provenance links.
- [ ] 3.3 Add `attrs_json` columns for namespaced project-specific metadata.
- [ ] 3.4 Add indexes needed for status, updated time, experiment membership, job status, and metric lookup.
- [ ] 3.5 Add validation helpers for status enums, artifact type enums, UTC timestamps, `sha256:` content hashes, and namespaced attribute keys.
- [ ] 3.6 Add normalized tag tables and tag filtering for experiments.
- [ ] 3.7 Add stable exit-code handling for validation, not-found, ambiguity, ledger-busy, and internal errors.

## 4. Core CLI Commands

- [ ] 4.1 Implement experiment create/list/show/status commands with text and JSON output.
- [ ] 4.2 Implement run add/list/show/link commands.
- [ ] 4.3 Implement job add/update-status/list/show commands, including experiment-level jobs without run links.
- [ ] 4.4 Implement artifact add/list/show commands for job-level and run-level artifacts.
- [ ] 4.5 Implement metric add/import-csv/list commands for summary metrics.
- [ ] 4.6 Implement note add/list/resolve commands for research notes, debug notes, and next actions.
- [ ] 4.7 Implement soft-delete/archive commands for experiments, runs, jobs, artifacts, metrics, and notes.

## 5. Agent Workflow

- [ ] 5.1 Implement compact experiment status summaries with run counts, job counts by status, stale jobs, failed jobs, key artifacts, and next actions.
- [ ] 5.2 Implement stale-job detection with a configurable threshold.
- [ ] 5.3 Keep default CLI output concise and add explicit verbose/JSON paths for drilldown.
- [ ] 5.4 Add examples of agent context-switch workflows in the README or skill draft.
- [ ] 5.5 Add handoff-oriented commands or flags that summarize one experiment without dumping unrelated history.

## 6. Reconcile

- [ ] 6.1 Define the generic reconcile input model for runs, jobs, artifacts, metrics, notes, and custom attributes.
- [ ] 6.2 Implement file-based reconcile from CSV or JSON manifests in dry-run mode.
- [ ] 6.3 Implement apply mode for reconcile and record reconcile events.
- [ ] 6.4 Add a Marin-oriented example manifest that records Iris job paths, GCS artifact URIs, and W&B links through namespaced attributes.

## 7. Export

- [ ] 7.1 Implement long metric export with provenance columns.
- [ ] 7.2 Implement wide run export with selected metrics and provenance columns.
- [ ] 7.3 Record export files as artifacts in the ledger.
- [ ] 7.4 Implement metric coverage reporting for selected experiments and metric sets.

## 8. Draft Agent Skill

- [ ] 8.1 Draft an in-repo portable Fieldbook agent skill guide that tells agents how to initialize, refresh, inspect, and update a ledger.
- [ ] 8.2 Add command examples that avoid loading excessive context.
- [ ] 8.3 Add Marin-specific guidance as an optional reference, not core skill text.
- [ ] 8.4 Mark stable external skill packaging as deferred until after CLI dogfooding.

## 9. Tests And Fixtures

- [ ] 9.1 Add tests for fresh initialization, repeated initialization, WAL mode, and schema version.
- [ ] 9.2 Add tests for creating and querying experiments, runs, jobs, artifacts, metrics, and notes.
- [ ] 9.3 Add tests for JSON attributes and JSON-attribute filtering.
- [ ] 9.4 Add tests for stale-job status summaries and next-action notes.
- [ ] 9.5 Add tests for reconcile dry-run/apply behavior.
- [ ] 9.6 Add tests for long and wide exports.
- [ ] 9.7 Add a small Marin-inspired fixture that demonstrates training plus follow-up eval jobs without requiring Marin itself.
- [ ] 9.8 Add tests for schema upgrades, duplicate external identifiers, metric idempotency, and invalid custom attribute namespaces.
- [ ] 9.9 Add tests for deleted-record filtering, note type validation, init-from-subdirectory behavior, and nullable metric idempotency keys.

## 10. Validation

- [ ] 10.1 Run unit tests locally with `uv`.
- [ ] 10.2 Run OpenSpec status and verify the change remains apply-ready.
- [ ] 10.3 Manually exercise the README quickstart against a temporary repository.
- [ ] 10.4 Review exported CSV provenance columns against the intended collaborator-sharing workflow.
