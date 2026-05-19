## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for `agent-sessions-locality`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [ ] 1.6 Commit and push the reviewed spec.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [ ] 2.1 Add failing tests for ledger ID init, preservation, and legacy backfill.
- [ ] 2.2 Add failing tests for `db where` and `.fieldbook` ledger resolution.
- [ ] 2.3 Add failing tests for experiment idempotency keys.
- [ ] 2.4 Add failing tests for session start, current, switch, end, list, archived experiment handling, and marker behavior.
- [ ] 2.5 Add failing tests for reconcile-event and note session stamping.
- [ ] 2.6 Add failing tests for doctor stale-session and ledger-locality warnings.

## 3. Schema And Storage

- [ ] 3.1 Add migration `009_agent_sessions_locality.sql` for experiment idempotency, sessions, reconcile-event session ID, and `v_sessions_v1` / `v_experiment_session_history_v1`.
- [ ] 3.2 Add ledger ID stamping/backfill inside migration 009 and avoid duplicate runtime rewrites.
- [ ] 3.3 Add `.fieldbook` config parsing and ledger-resolution metadata helpers.
- [ ] 3.4 Add session repository helpers and best-effort current-session resolution.
- [ ] 3.5 Update reconcile, sync-event, and note creation paths to stamp valid session lineage.

## 4. CLI And Doctor

- [ ] 4.1 Add `fieldbook db where` and register it in the read-only command set.
- [ ] 4.2 Add `experiment create --idempotency-key`.
- [ ] 4.3 Add `fieldbook session start|switch|end|current|list`, including `--intent`, `--force-archived`, and list filters `--experiment`, `--agent`, `--open`, and `--limit`.
- [ ] 4.4 Add Markdown handoff generation for `session switch`, reusing the shape of `.codex/skills/fieldbook/templates/handoff-note.md`.
- [ ] 4.5 Add doctor checks for stale sessions and ledger locality.
- [ ] 4.6 Update snapshot metadata sidecar to include `ledger_id`.

## 5. Docs And Skill

- [ ] 5.1 Update README with phase numbering, ledger locality, idempotent experiment creation, and session workflows.
- [ ] 5.2 Update the Fieldbook agent skill with the session/context-switch workflow and ledger-locality checks.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
