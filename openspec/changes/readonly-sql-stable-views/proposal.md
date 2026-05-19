## Why

Fieldbook is intended to be agent-first, and agents need flexible read access without adding every useful query as a bespoke CLI command. Direct SQL reads are the right escape hatch, but the table schema should remain internal so future migrations can evolve safely. This phase adds a safe read-only SQL surface plus versioned views that become the stable query contract for agents, notebooks, exports, and future dashboards.

## What Changes

- Add `fieldbook db path` so agents can locate the active ledger deterministically.
- Add `fieldbook sql` for safe read-only SQL queries with JSON, NDJSON, and CSV output modes.
- Enforce a default row limit, explicit truncation semantics, query timeout, and output-size cap.
- Add stable `v_*_v1` SQLite views for experiments, runs, jobs, artifacts, metrics, summaries, attention queues, sync coverage, and reconcile logs.
- Document that SQL reads are supported through views, while direct SQL writes and table-shape dependencies are unsupported.
- Add tests covering read-only enforcement, output contracts, limits, type mapping, timeout behavior, and view column stability.

## Capabilities

### New Capabilities

- `readonly-sql-stable-views`: Read-only SQL access and versioned query views for agent-operated ledgers.

### Modified Capabilities

None. Prior Fieldbook phases are still tracked as separate OpenSpec changes.

## Impact

- SQLite schema migration adding stable views.
- New CLI command group `fieldbook db`.
- New top-level CLI command `fieldbook sql`.
- New SQL execution/output module.
- README and agent-skill updates for SQL safety, view contracts, and query examples.
