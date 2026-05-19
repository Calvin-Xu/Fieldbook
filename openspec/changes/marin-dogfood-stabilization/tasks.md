## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `marin-dogfood-stabilization`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

## 2. Tests And Smoke Checks

- [ ] 2.1 Add or update tests for external-repo invocation documentation and dogfood issue-list schema helpers.
- [ ] 2.2 Smoke-test `uv run --project <FIELDBOOK_CHECKOUT> fieldbook --help` from the Marin checkout.
- [ ] 2.3 Smoke-test ledger init, status/context, reconcile, doctor, snapshot, and export from Marin using the sidecar invocation.

## 3. Dogfood Execution

- [ ] 3.1 Create a local Marin dogfood ledger without modifying Marin dependencies.
- [ ] 3.2 Record the realistic local-only experiment, runs, jobs, artifacts, metrics/summary observations, and Markdown notes.
- [ ] 3.3 Run one adapter or record an adapter-gap issue-list entry.
- [ ] 3.4 Run one reconcile dry-run and apply.
- [ ] 3.5 Run doctor and snapshot export/inspect/import.
- [ ] 3.6 Export collaborator-style metrics or coverage table.

## 4. Findings And Documentation

- [ ] 4.1 Write `openspec/changes/marin-dogfood-stabilization/dogfood/report.md`.
- [ ] 4.2 Write `openspec/changes/marin-dogfood-stabilization/dogfood/issues.json`.
- [ ] 4.3 Update README/skill if dogfood reveals missing guidance.
- [ ] 4.4 Patch only fix-in-phase Fieldbook blockers discovered during dogfood and ensure each has `fixed_by_commit`.

## 5. Validation And Implementation Review

- [ ] 5.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 5.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 5.3 Patch CC blockers and rerun validation.
- [ ] 5.4 Commit and push the implementation.
