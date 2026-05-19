## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `refresh-adapter-framework`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

## 2. Tests First

- [ ] 2.1 Add failing adapter registry tests for list and describe output.
- [ ] 2.2 Add failing adapter run tests for `iris-jobs-json`, `wandb-runs-json`, `metrics-csv`, and `artifacts-json`.
- [ ] 2.3 Add failing tests for malformed-row debug output, partial coverage, and `--strict`.
- [ ] 2.4 Add failing tests for hard parse failure with debug output and no manifest.
- [ ] 2.5 Add failing tests for stdin/stdout handling and rejecting output/debug stdout conflicts.
- [ ] 2.6 Add failing end-to-end fixture test: adapter output then reconcile apply.

## 3. Adapter Framework

- [ ] 3.1 Add adapter dataclasses/protocols for descriptions, run inputs, run results, debug rows, and manifest output.
- [ ] 3.2 Add adapter registry and common JSON/CSV input helpers.
- [ ] 3.3 Add manifest section counting and canonical empty-section output.
- [ ] 3.4 Add debug output writer with input row index, severity, message, and source row payload.

## 4. Source-Format Adapters

- [ ] 4.1 Implement `iris-jobs-json`.
- [ ] 4.2 Implement `wandb-runs-json`.
- [ ] 4.3 Implement `metrics-csv`.
- [ ] 4.4 Implement `artifacts-json`.
- [ ] 4.5 Add fixture inputs and expected outputs for clean and partial cases.

## 5. CLI, Docs, And Skill

- [ ] 5.1 Add `fieldbook adapter list`.
- [ ] 5.2 Add `fieldbook adapter describe <name>`.
- [ ] 5.3 Add `fieldbook adapter run <name> --input --output --debug-output --strict`.
- [ ] 5.4 Update README with adapter-to-reconcile examples.
- [ ] 5.5 Update the Fieldbook agent skill with the two-step refresh workflow.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
