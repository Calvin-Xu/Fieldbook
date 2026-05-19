## Why

Fieldbook's reconcile path is the main way agents refresh experiment state after jobs run outside the ledger. The current implementation supports insert/update manifests, but it cannot archive stale rows, record sync events, inspect detailed reconcile history, or guarantee that planning and applying happen against the same database snapshot. Those gaps make adapter-driven refresh risky before dogfooding.

## What Changes

- Add reconcile operation support with `_op=upsert|archive`; missing `_op` remains `upsert`.
- Explicitly reject `_op=delete` and any other unsupported operation.
- Add `runs.parent_run_id` for provenance between related runs.
- Add partial unique constraints for non-archived run/job external identifiers.
- Add sync-event ingestion through reconcile manifests.
- Add full bounded reconcile operation audit records.
- Add a stable full reconcile `counts` shape while preserving legacy insert/update summary fields.
- Run reconcile dry-run planning inside a read transaction and reconcile apply planning plus writes inside one `BEGIN IMMEDIATE` transaction.
- Add `fieldbook reconcile log` for recent events and per-operation drilldown.

## Capabilities

### New Capabilities

- `reconcile-core-hardening`: Hardened reconcile operations, sync-event ingestion, operation audit, and reconcile log inspection.

### Modified Capabilities

None. Existing MVP capabilities remain active; this phase adds the next reconcile-specific capability before the baseline specs are archived.

## Impact

- SQLite schema migration for run parent links, reconcile operation audit, sync-event provenance, and external-ID uniqueness.
- Reconcile manifest format gains optional `_op` and `sync_events`.
- Reconcile output gains richer counts and operation audit identifiers.
- CLI gains `fieldbook reconcile log`.
- Tests cover migration safety, transactionality, archive/noop behavior, sync-event idempotency, operation audit truncation, and command output.
