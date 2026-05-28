## 1. Specification And Review

- [x] 1.1 Treat the CC roadmap critique in session
  `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for
  `advisory-leases-and-monitors`.
- [x] 1.3 Validate `advisory-leases-and-monitors`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Begin implementation only after `active-experiment-workloop` is
  implemented and pushed.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for lease claim/list/show/release JSON and text
  output.
- [x] 2.2 Add failing tests for duplicate claim conflicts, same owner/session
  idempotency, expired takeover, and force takeover audit.
- [x] 2.3 Add failing tests for heartbeat updates, stale heartbeat doctor
  warnings, and no auto-release from stale heartbeat.
- [x] 2.4 Add failing tests for lease rejection on archived or missing
  entities and doctor warnings for orphaned leases.
- [x] 2.5 Add failing tests proving lease attrs do not mutate authoritative
  job/run/experiment state.
- [x] 2.6 Add failing tests for status/context/workloop lease summaries and
  bounded examples.
- [x] 2.7 Add failing tests for stable lease views and retry depth derived from
  job retry lineage.

## 3. Schema And Views

- [x] 3.1 Add a migration for leases, constraints, indexes, and history.
- [x] 3.2 Add stable views for active leases, stale leases, lease history, and
  ownership summaries by experiment/run/job.
- [x] 3.3 Ensure view output filters archived/deleted entities consistently
  with existing `_v1` view conventions.

## 4. Repository And CLI

- [x] 4.1 Add repository helpers for claim, heartbeat, release, force takeover,
  expired takeover, list, and show.
- [x] 4.2 Add `fieldbook lease claim|heartbeat|release|list|show`.
- [x] 4.3 Add JSON envelopes and concise text output for agent workflows.
- [x] 4.4 Add validation for entity type, ownership fields, timestamps,
  release reasons, and attrs JSON.

## 5. Agent Surfaces, Doctor, Docs

- [x] 5.1 Add lease summaries to experiment status, context, and workloop.
- [x] 5.2 Add doctor checks for stale heartbeat, expired lease, orphaned
  entity, active lease on ended session, and conflicting active lease history.
- [x] 5.3 Update README and Fieldbook skill guidance for babysit loops and
  parallel-agent coordination.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [x] 6.4 Commit and push the implementation.
