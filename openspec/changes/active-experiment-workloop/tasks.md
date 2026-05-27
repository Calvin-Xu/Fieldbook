## 1. Specification And Review

- [x] 1.1 Treat the CC roadmap critique in session
  `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate for active
  experiment workloop scope.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for
  `active-experiment-workloop`.
- [x] 1.3 Validate `active-experiment-workloop`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [ ] 2.1 Add failing tests for `experiment workloop` JSON and Markdown output,
  bounded sections, and read-only default behavior.
- [ ] 2.2 Add failing tests for workloop refresh dry-run/apply behavior,
  selected source handling, `--refresh-all`, and post-refresh status.
- [ ] 2.3 Add failing tests for explicit workloop checkpoint behavior and body
  ingestion.
- [ ] 2.4 Add failing tests for `doctor --experiment` scoped output and omitted
  global issue counts.
- [ ] 2.5 Add failing tests for cleanup dry-run/apply of recovered debug notes
  and superseded validations.
- [ ] 2.6 Add failing tests proving cleanup does not mutate unrelated
  experiments.
- [ ] 2.7 Add failing docs/skill tests ensuring active experiment guidance uses
  `experiment workloop`.

## 3. Workloop Implementation

- [ ] 3.1 Add repository helpers that assemble the workloop report from existing
  status, triage, freshness, refresh, and doctor helpers.
- [ ] 3.2 Add `fieldbook experiment workloop`.
- [ ] 3.3 Add Markdown and JSON formatters for the workloop report.
- [ ] 3.4 Add explicit refresh flags and post-refresh recomputation.
- [ ] 3.5 Add explicit checkpoint flags and generated checkpoint body support.

## 4. Scoped Doctor And Cleanup

- [ ] 4.1 Add `fieldbook doctor --experiment <experiment>` filtering.
- [ ] 4.2 Add omitted global issue counts to scoped doctor output.
- [ ] 4.3 Add cleanup planner helpers for recovered debug notes and superseded
  validations.
- [ ] 4.4 Add `fieldbook experiment cleanup` with dry-run default and `--apply`.
- [ ] 4.5 Record cleanup apply summaries as validation or checkpoint evidence.

## 5. Docs And Skill

- [ ] 5.1 Update README context-switch guidance to prefer workloop.
- [ ] 5.2 Update the Fieldbook agent skill to prefer workloop.
- [ ] 5.3 Update workflow recipes for launch, refresh, failure triage, and
  handoff to include workloop.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
