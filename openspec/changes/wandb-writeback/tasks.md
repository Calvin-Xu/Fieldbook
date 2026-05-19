## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `wandb-writeback`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [x] 2.1 Add failing migration tests for sync-event provenance columns, manifest-only sync idempotency uniqueness, writeback retry history, and `v_wandb_writeback_coverage_v1`.
- [x] 2.2 Add failing planner tests for metric glob selection, target resolution, field namespacing, first-write guardrails, and idempotency.
- [x] 2.3 Add failing apply tests using a fake W&B writer for success, failure, retries, and `--allow-rewrite`.
- [x] 2.4 Add failing CLI tests for JSON dry-run envelope, explicit `--writer` on apply, fake writer, missing real writer dependency, and writeback log filters.
- [x] 2.5 Add failing error-redaction tests for bearer tokens, API keys, passwords, and secret-looking values.
- [x] 2.6 Add failing doctor/view tests for failed writeback events, duplicate writeback retry keys, and coverage output.

## 3. Schema And Views

- [x] 3.1 Add migration for `sync_events.origin`, `source_entity_type`, `source_entity_id`, `target_field`, and `payload_summary_json`.
- [x] 3.2 Backfill existing sync events with `origin='manifest'`.
- [x] 3.3 Add SQL constraints for allowed origins and metric-only source entity type.
- [x] 3.4 Add `v_wandb_writeback_coverage_v1` with stable columns and latest-event semantics.
- [x] 3.5 Update existing stable-view tests for the new view.
- [x] 3.6 Replace the existing sync-event idempotency unique index with a manifest-only unique partial index.

## 4. Writeback Planning And Execution

- [x] 4.1 Add writeback dataclasses for selected metrics, planned writes, skipped writes, errors, and results.
- [x] 4.2 Implement target resolution for explicit, source-run, and parent-run W&B targets.
- [x] 4.3 Implement metric glob selection and deterministic target-field construction.
- [x] 4.4 Implement source-anchored idempotency planning against existing sync events.
- [x] 4.5 Add `WandbSummaryWriter` protocol, fake writer, and real-writer import boundary.
- [x] 4.6 Implement apply execution with per-metric sync-event insertion and transaction boundaries.
- [x] 4.7 Add error redaction before storing or emitting writer failures.
- [x] 4.8 Update reconcile sync-event planning to reject manifest rows with `origin='writeback'`.
- [x] 4.9 Update doctor sync-event checks for manifest-only duplicate warnings and failed/stale writeback rows.

## 5. CLI, Docs, And Skill

- [x] 5.1 Add `fieldbook writeback wandb`.
- [x] 5.2 Add `fieldbook writeback log`.
- [x] 5.3 Add README examples for W&B dry-run/apply, namespacing, first-write acknowledgement, and fake writer tests.
- [x] 5.4 Update the Fieldbook agent skill with safe W&B writeback workflow.
- [x] 5.5 Update query cookbook with `v_wandb_writeback_coverage_v1` examples.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [x] 6.4 Commit and push the implementation.
