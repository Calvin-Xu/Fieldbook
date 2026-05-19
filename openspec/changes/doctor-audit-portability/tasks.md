## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `doctor-audit-portability`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

## 2. Tests First

- [ ] 2.1 Add failing doctor CLI tests for clean ledger output, JSON envelope, text output, check listing/selection, unknown checks, strict mode, schema mismatch, and ledger-busy behavior.
- [ ] 2.2 Add failing doctor tests for invalid attrs JSON, dangling note entities, missing/unreadable local artifacts, remote artifact skip, stale jobs, duplicate external IDs, sync-event soft-delete/idempotency anomalies, and reconcile-log audit JSON anomalies.
- [ ] 2.3 Add failing snapshot tests for export, inspect, metadata, replace behavior, single-file snapshot behavior, import to a new ledger, existing-output refusal, non-SQLite/non-Fieldbook input, WAL mode, migration failure cleanup, and older/newer schema behavior.
- [ ] 2.4 Add failing end-to-end audit/portability fixture test using a Marin-inspired ledger.

## 3. Doctor Implementation

- [ ] 3.1 Add doctor dataclasses for checks, issues, results, severities, and output envelopes.
- [ ] 3.2 Add read-only doctor execution with exact schema-version checking, check registry, and selected-check filtering.
- [ ] 3.3 Implement attrs JSON, note entity, local artifact, stale job, external ID, sync event, and reconcile log checks.
- [ ] 3.4 Add text and JSON doctor output plus exit behavior for errors and `--strict`.

## 4. Snapshot Implementation

- [ ] 4.1 Add snapshot metadata helpers and table-count helpers.
- [ ] 4.2 Implement `fieldbook snapshot export` using a safe SQLite snapshot mechanism.
- [ ] 4.3 Implement `fieldbook snapshot inspect` with read-only open and optional metadata loading.
- [ ] 4.4 Implement `fieldbook snapshot import` to create or replace a full ledger and run migrations when needed.
- [ ] 4.5 Reject newer-schema snapshots and document full-ledger-only semantics.

## 5. Docs And Skill

- [ ] 5.1 Update README with doctor workflows, stable issue codes, reconcile/log follow-up, and snapshot privacy warning.
- [ ] 5.2 Update Fieldbook skill with context-recovery audit steps and snapshot commands.
- [ ] 5.3 Add query cookbook examples using only `v_*_v1` stable views.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
