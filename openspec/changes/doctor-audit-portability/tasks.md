## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `doctor-audit-portability`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

## 2. Tests First

- [x] 2.1 Add failing doctor CLI tests for clean ledger output, JSON envelope, text output, check listing/selection, unknown checks, strict mode, and schema mismatch.
- [x] 2.2 Add failing doctor tests for invalid attrs JSON, dangling note entities, missing local artifacts, remote artifact skip, stale jobs, archived external ID reuse, sync-event soft-delete anomalies, and reconcile-log audit JSON anomalies.
- [x] 2.3 Add failing snapshot tests for export, inspect, metadata, replace behavior, single-file snapshot behavior, import to a new ledger, existing-output refusal, non-SQLite input, WAL mode, newer schema rejection, and missing metadata behavior.
- [x] 2.4 Add failing end-to-end audit/portability fixture coverage using a realistic experiment ledger.

## 3. Doctor Implementation

- [x] 3.1 Add doctor dataclasses for checks, issues, results, severities, and output envelopes.
- [x] 3.2 Add read-only doctor execution with exact schema-version checking, check registry, and selected-check filtering.
- [x] 3.3 Implement attrs JSON, note entity, local artifact, stale job, external ID, sync event, and reconcile log checks.
- [x] 3.4 Add text and JSON doctor output plus exit behavior for errors and `--strict`.

## 4. Snapshot Implementation

- [x] 4.1 Add snapshot metadata helpers and table-count helpers.
- [x] 4.2 Implement `fieldbook snapshot export` using a safe SQLite snapshot mechanism.
- [x] 4.3 Implement `fieldbook snapshot inspect` with read-only open and optional metadata loading.
- [x] 4.4 Implement `fieldbook snapshot import` to create or replace a full ledger and run migrations when needed.
- [x] 4.5 Reject newer-schema snapshots and document full-ledger-only semantics.

## 5. Docs And Skill

- [x] 5.1 Update README with doctor workflows, stable issue codes, reconcile/log follow-up, and snapshot privacy warning.
- [x] 5.2 Update Fieldbook skill with context-recovery audit steps and snapshot commands.
- [x] 5.3 Add query cookbook examples using only `v_*_v1` stable views.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [x] 6.4 Commit and push the implementation.
