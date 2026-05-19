## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `reconcile-core-hardening`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [ ] 1.6 Commit and push the reviewed spec.

## 2. Tests First

- [ ] 2.1 Add failing migration tests for parent runs, external-ID uniqueness, sync-event provenance, and operation audit tables.
- [ ] 2.2 Add failing reconcile tests for `_op`, archive, delete rejection, internal dedupe, transactionality, sync events, idempotency, and bounded audit.
- [ ] 2.3 Add failing CLI tests for `fieldbook reconcile log`.
- [ ] 2.4 Add failing regression tests showing existing upsert manifests still work.

## 3. Schema And Validation

- [ ] 3.1 Add migration `005_reconcile_core_hardening.sql` and bump schema version.
- [ ] 3.2 Add Python migration precheck for duplicate run/job external IDs before applying v5.
- [ ] 3.3 Add validation constants/helpers for reconcile operations and sync-event statuses.
- [ ] 3.4 Add parent-run validation and external-ID uniqueness tests.

## 4. Reconcile Planner And Apply

- [ ] 4.1 Parse `_op` from JSON/CSV manifests and reject unsupported operations.
- [ ] 4.2 Add `sync_events` manifest loading.
- [ ] 4.3 Plan dry-run inside a deferred transaction and apply inside `BEGIN IMMEDIATE`.
- [ ] 4.4 Deduplicate manifest-local run/job rows by external identifier before SQL planning.
- [ ] 4.5 Apply insert/update/archive/sync-event/noop operations in deterministic dependency order and strip `_op` before SQL writes.
- [ ] 4.6 Persist reconcile events and bounded reconcile operation rows.

## 5. CLI, Docs, And Skill

- [ ] 5.1 Add `fieldbook reconcile log` with recent-event and per-event operation output.
- [ ] 5.2 Update README and Fieldbook agent skill for `_op`, archive, sync events, and reconcile logs.
- [ ] 5.3 Update `tests/fixtures/marin/eval_completion_manifest.json` to include at least one sync event and archive example.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
