# Fieldbook Phases

Fieldbook phase numbers are forward-only implementation milestones. OpenSpec
change IDs stay semantic; this file maps phase numbers to change IDs and test
files.

| Phase | OpenSpec change | Primary tests | Summary |
| :--- | :--- | :--- | :--- |
| 1 | `bootstrap-fieldbook-mvp` | `tests/test_phase1_storage.py` | Storage, migrations, schema, IDs, and core persistence invariants. |
| 2 | `bootstrap-fieldbook-mvp` | `tests/test_phase2_cli.py` | Core experiment, run, job, artifact, metric, and note CLI. |
| 3 | `bootstrap-fieldbook-mvp` / `reconcile-core-hardening` | `tests/test_phase3_workflows.py` | Agent workflows, reconcile, export, and sync-event hardening. |
| 4 | `bootstrap-fieldbook-mvp` | `tests/test_phase4_end_to_end.py` | End-to-end agent quickstart and skill dogfood. |
| 5 | `readonly-sql-stable-views` | `tests/test_phase5_sql_views.py` | Read-only SQL command and stable `_v1` views. |
| 6 | `refresh-adapter-framework` | `tests/test_phase6_adapters.py` | Local refresh adapters that emit reconcile manifests. |
| 7 | `doctor-audit-portability` | `tests/test_phase7_doctor_snapshot.py` | Doctor checks, snapshots, portability, and audit guidance. |
| 8 | `marin-dogfood-stabilization` | `tests/test_phase8_dogfood_contract.py` | Marin sidecar dogfood and dashboard-prerequisite issue capture. |
| 9 | `wandb-writeback` | `tests/test_phase9_wandb_writeback.py` | Opt-in W&B summary writeback with sync-event provenance. |
| 10 | `workflow-packs-dashboard-readiness` | `tests/test_phase10_workflow_dashboard.py` | Workflow packs, redacted artifact view, and dashboard-readiness contract. |
| 11 | `agent-sessions-locality` | `tests/test_phase11_agent_sessions_locality.py` | Ledger identity, worktree locality, experiment idempotency, and advisory agent sessions. |

## Numbering Rules

- Assign phase numbers when drafting the OpenSpec change.
- Never reuse phase numbers, even if a phase is later split or withdrawn.
- Use semantic OpenSpec change IDs instead of numeric prefixes.
- Keep tests named `tests/test_phaseN_<slug>.py`.
- Phase numbers appear only in `tests/test_phaseN_*.py` and this file. They do
  not appear in OpenSpec change IDs or capability names.
- Phase numbers are allocated at proposal commit time, not implementation
  start.
- If a phase is split after drafting, the second part gets the next phase
  number rather than `N-a`, `N.1`, or another sub-number.
- Phase 3 was scoped before this split rule existed; future splits should not
  use Phase 3 as precedent for sharing one phase number.
