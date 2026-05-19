## Why

Fieldbook is now usable as a local, agent-first experiment ledger, but context
switching still depends on conversational memory and ad hoc ledger-path
discipline. Agents need a durable way to answer "which ledger am I using?",
"which experiment am I working on?", and "what handoff should the next agent
read?" without adding a daemon or a global active-experiment singleton.

This phase adds ledger identity, worktree locality checks, idempotent
experiment creation, and advisory agent sessions. It deliberately leaves
refresh/freshness orchestration for the next phase after sessions are dogfooded.

## What Changes

- Stamp an immutable `ledger_id` into every ledger and expose it through
  `fieldbook db where`.
- Add a minimal `.fieldbook` config with only a `ledger` pointer for worktrees
  that intentionally share one ledger.
- Add experiment idempotency keys so parallel agents can converge on one
  experiment row instead of creating duplicates.
- Add advisory sessions and `fieldbook session start|switch|end|current|list`
  for agent context switching.
- Stamp valid session lineage onto reconcile events and notes when available.
- Add doctor warnings for stale sessions and likely worktree ledger-locality
  mistakes.
- Add a root `PHASES.md` mapping phase numbers to OpenSpec changes and test
  files.

## Capabilities

### New Capabilities

- `agent-sessions-locality`: ledger identity, locality discovery, idempotent
  experiment creation, and advisory agent sessions for context switching.

### Modified Capabilities

- `provenance-export`: reconcile events may now carry session lineage.
- `markdown-notes-agent-context`: notes written during a session may carry
  best-effort session lineage in attrs.

## Impact

- SQLite migration for ledger/session metadata and experiment idempotency.
- New `fieldbook db where` and `fieldbook session ...` CLI commands.
- Extended experiment create behavior.
- Doctor check additions.
- README, skill, and phase-index updates.
