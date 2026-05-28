## 1. Specification And Review

- [x] 1.1 Treat the CC roadmap critique in session
  `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for
  `dashboard-mvp`.
- [x] 1.3 Validate `dashboard-mvp`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Begin implementation only after `advisory-leases-and-monitors` is
  implemented and pushed.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests that `dashboard serve` binds to `127.0.0.1` by
  default and requires an explicit flag for other hosts.
- [x] 2.2 Add failing tests that the dashboard route table is GET-only.
- [x] 2.3 Add failing tests that dashboard handlers query stable `_v1` views
  and do not read internal tables directly.
- [x] 2.4 Add failing tests for empty ledger, active experiment, and archived
  experiment page rendering.
- [x] 2.5 Add failing tests for experiment detail sections: run progress, job
  recovery, leases, validations, freshness, notes, artifacts, and external
  links.
- [x] 2.6 Add failing tests that action affordances are rendered as copyable
  commands or external links, not executed mutations.

## 3. View Contract

- [x] 3.1 Add or document dashboard-required stable views for active
  experiments, run progress, job recovery, lease ownership, validations,
  freshness, notes, artifacts, and refresh/reconcile history.
- [x] 3.2 Add view-shape tests for dashboard-required columns.
- [x] 3.3 Ensure dashboard pages use redacted/safe view conventions where
  available.

## 4. Dashboard Implementation

- [x] 4.1 Add `fieldbook dashboard serve`.
- [x] 4.2 Add lightweight local web app structure and templates/components.
- [x] 4.3 Add experiment index and experiment detail pages.
- [x] 4.4 Add run progress, job recovery, lease ownership, validation,
  freshness, note, artifact, and external-link sections.
- [x] 4.5 Add copyable command affordances for common next actions.

## 5. Docs And Skill

- [x] 5.1 Update README with dashboard launch and scope.
- [x] 5.2 Update Fieldbook skill to describe dashboard as read-only context,
  not the primary mutation path.
- [x] 5.3 Add dashboard smoke-test guidance.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [x] 6.4 Commit and push the implementation.
