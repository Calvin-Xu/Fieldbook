## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `workflow-packs-dashboard-readiness`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [ ] 2.1 Add failing CLI tests for `experiment triage` JSON/Markdown and read-only behavior.
- [ ] 2.2 Add failing CLI tests for `experiment closeout-checklist` JSON/Markdown and read-only behavior.
- [ ] 2.3 Add failing migration/view tests for artifact locality classification, exact `v_artifacts_redacted_v1` columns, `v_notes_v1`, and `v_sync_events_v1`.
- [ ] 2.4 Add failing recipe/template validation tests.
- [ ] 2.5 Add failing dashboard contract sample-query tests.
- [ ] 2.6 Add failing privacy-grep tests for committed recipes, templates, and dashboard docs.

## 3. Workflow Pack Implementation

- [ ] 3.1 Add repository helpers for triage and closeout-checklist summaries, and register them as read-only in CLI dispatch.
- [ ] 3.2 Add Markdown formatters for triage and closeout-checklist outputs.
- [ ] 3.3 Add `fieldbook experiment triage`.
- [ ] 3.4 Add `fieldbook experiment closeout-checklist`.
- [ ] 3.5 Add workflow recipe Markdown files under the Fieldbook skill references.
- [ ] 3.6 Add reconcile manifest and note-body templates.

## 4. Dashboard Readiness Implementation

- [ ] 4.1 Add pure-SQL artifact URI locality classification.
- [ ] 4.2 Add migration for `v_artifacts_redacted_v1`, `v_notes_v1`, and `v_sync_events_v1`.
- [ ] 4.3 Add dashboard readiness contract docs.
- [ ] 4.4 Add dashboard sample SQL query files.
- [ ] 4.5 Update query cookbook with redacted artifact view examples.

## 5. Docs And Skill

- [ ] 5.1 Update README with triage, closeout-checklist, recipe/template, and dashboard-readiness guidance.
- [ ] 5.2 Update the Fieldbook agent skill to reference workflow recipes and dashboard contracts.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
