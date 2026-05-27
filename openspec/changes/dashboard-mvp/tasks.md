## 1. Specification And Review

- [x] 1.1 Treat the CC roadmap critique in session
  `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for
  `dashboard-mvp`.
- [x] 1.3 Validate `dashboard-mvp`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [ ] 1.6 Begin implementation only after `advisory-leases-and-monitors` is
  implemented and pushed.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [ ] 2.1 Add failing tests that `dashboard serve` binds to `127.0.0.1` by
  default and requires an explicit flag for other hosts.
- [ ] 2.2 Add failing tests that the dashboard route table is GET-only.
- [ ] 2.3 Add failing tests that dashboard handlers query stable `_v1` views
  and do not read internal tables directly.
- [ ] 2.4 Add failing tests for empty ledger, active experiment, and archived
  experiment page rendering.
- [ ] 2.5 Add failing tests for experiment detail sections: run progress, job
  recovery, leases, validations, freshness, notes, artifacts, and external
  links.
- [ ] 2.6 Add failing tests that action affordances are rendered as copyable
  commands or external links, not executed mutations.

## 3. View Contract

- [ ] 3.1 Add or document dashboard-required stable views for active
  experiments, run progress, job recovery, lease ownership, validations,
  freshness, notes, artifacts, and refresh/reconcile history.
- [ ] 3.2 Add view-shape tests for dashboard-required columns.
- [ ] 3.3 Ensure dashboard pages use redacted/safe view conventions where
  available.

## 4. Dashboard Implementation

- [ ] 4.1 Add `fieldbook dashboard serve`.
- [ ] 4.2 Add lightweight local web app structure and templates/components.
- [ ] 4.3 Add experiment index and experiment detail pages.
- [ ] 4.4 Add run progress, job recovery, lease ownership, validation,
  freshness, note, artifact, and external-link sections.
- [ ] 4.5 Add copyable command affordances for common next actions.

## 5. Docs And Skill

- [ ] 5.1 Update README with dashboard launch and scope.
- [ ] 5.2 Update Fieldbook skill to describe dashboard as read-only context,
  not the primary mutation path.
- [ ] 5.3 Add dashboard smoke-test guidance.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
