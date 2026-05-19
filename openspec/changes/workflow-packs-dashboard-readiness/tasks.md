## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `workflow-packs-dashboard-readiness`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [x] 2.1 Add failing CLI tests for `experiment triage` JSON/Markdown and read-only behavior.
- [x] 2.2 Add failing CLI tests for `experiment closeout-checklist` JSON/Markdown and read-only behavior.
- [x] 2.3 Add failing migration/view tests for artifact locality classification, exact `v_artifacts_redacted_v1` columns, `v_notes_v1`, and `v_sync_events_v1`.
- [x] 2.4 Add failing recipe/template validation tests.
- [x] 2.5 Add failing dashboard contract sample-query tests.
- [x] 2.6 Add failing privacy-grep tests for committed recipes, templates, and dashboard docs.

## 3. Workflow Pack Implementation

- [x] 3.1 Add repository helpers for triage and closeout-checklist summaries, and register them as read-only in CLI dispatch.
- [x] 3.2 Add Markdown formatters for triage and closeout-checklist outputs.
- [x] 3.3 Add `fieldbook experiment triage`.
- [x] 3.4 Add `fieldbook experiment closeout-checklist`.
- [x] 3.5 Add workflow recipe Markdown files under the Fieldbook skill references.
- [x] 3.6 Add reconcile manifest and note-body templates.

## 4. Dashboard Readiness Implementation

- [x] 4.1 Add pure-SQL artifact URI locality classification.
- [x] 4.2 Add migration for `v_artifacts_redacted_v1`, `v_notes_v1`, and `v_sync_events_v1`.
- [x] 4.3 Add dashboard readiness contract docs.
- [x] 4.4 Add dashboard sample SQL query files.
- [x] 4.5 Update query cookbook with redacted artifact view examples.

## 5. Docs And Skill

- [x] 5.1 Update README with triage, closeout-checklist, recipe/template, and dashboard-readiness guidance.
- [x] 5.2 Update the Fieldbook agent skill to reference workflow recipes and dashboard contracts.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [x] 6.4 Commit and push the implementation.
