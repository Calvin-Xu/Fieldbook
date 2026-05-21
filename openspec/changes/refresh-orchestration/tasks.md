## 1. Specification And Review

- [x] 1.1 Run CC ideation review before implementation resumes for Phase 13.
- [x] 1.2 Re-read this OpenSpec change after Phase 12 lands and patch any dependency drift.
- [x] 1.3 Validate `refresh-orchestration`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec if it changed.

Do not begin implementation tasks until Phase 12 is implemented and 1.6 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for refresh config discovery, TOML parsing, source listing, and unknown source errors.
- [x] 2.2 Add failing tests for command-source dry-run snapshot, manifest, debug, reconcile dry-run, and refresh event output.
- [x] 2.3 Add failing tests for file-source snapshot copying and adapter execution.
- [x] 2.4 Add failing tests for `--apply` reconcile application, refresh event linkage to reconcile event ID, and status/readiness updates after a single-source apply.
- [x] 2.5 Add failing tests for refresh output that resolves or leaves unresolved jobs in `submitting` / `unknown_submit`.
- [x] 2.6 Add failing tests for helper failure, adapter failure, and reconcile failure stage reporting.
- [x] 2.7 Add failing tests for `refresh log`, `v_refresh_log_v1`, doctor refresh checks, stale snapshots, and suspected-secret warnings in snapshots.
- [x] 2.8 Add failing tests proving adapters still do not open or mutate the ledger directly.

## 3. Schema And Config

- [x] 3.1 Add migration for `refresh_events` and `v_refresh_log_v1`.
- [x] 3.2 Add config parser for `.fieldbook/refresh.toml` using stdlib `tomllib`.
- [x] 3.3 Add refresh source data structures for command and file sources.
- [x] 3.4 Add snapshot path helpers that write under `.experiments/refresh-snapshots/<source>/`.
- [x] 3.5 Ensure `.experiments/refresh-snapshots/` is covered by generated or documented git-ignore guidance.

## 4. Refresh Orchestrator And CLI

- [x] 4.1 Add `fieldbook refresh list-sources`.
- [x] 4.2 Add `fieldbook refresh run --source <name>` dry-run flow.
- [x] 4.3 Add explicit `fieldbook refresh run --all`.
- [x] 4.4 Add `fieldbook refresh run --apply`.
- [x] 4.5 Add `fieldbook refresh log` with text and JSON output.
- [x] 4.6 Add session stamping to refresh events when a valid current session exists.
- [x] 4.7 Add stable output envelope with source, status, stage, paths, counts, reconcile event ID, `submission_resolutions`, and truncation flags.

## 5. Adapter, Reconcile, Doctor, Docs

- [x] 5.1 Invoke existing adapters from snapshots without giving them ledger handles.
- [x] 5.2 Feed adapter manifests into reconcile dry-run/apply through existing reconcile APIs.
- [x] 5.3 Record refresh events for dry-run, applied, helper failure, adapter failure, reconcile failure, and skipped sources.
- [x] 5.4 Add doctor checks for failed refreshes, stale snapshots using a default 30-day threshold, suspected secrets in snapshots, unapplied manifests, and missing snapshot files referenced by refresh events.
- [x] 5.5 Update README and the Fieldbook agent skill with explicit refresh workflows, including documented Iris-plus-GCS multi-source ordering without adding config dependency graphs.
- [x] 5.6 Add a `launch-protocol.md` workflow recipe under the Fieldbook agent skill references documenting `db where` -> `session start/switch` -> `job add --status submitting` -> external launcher -> status update to acknowledged state / `unknown_submit` / `failed` -> refresh.
- [x] 5.7 Add a top-level Fieldbook skill section warning agents not to wait until after successful submission to create the job record.
- [x] 5.8 Add fixture refresh configs and source snapshots for Marin-inspired dogfood without importing Marin.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
