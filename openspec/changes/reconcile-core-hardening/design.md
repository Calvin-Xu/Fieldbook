## Context

Fieldbook is pre-v1, and reconcile is the write boundary that lets agents refresh external job, artifact, metric, and note state without direct SQL writes. Current reconcile manifests can insert/update rows but cannot represent soft archival, sync attempts, or detailed audit history. Current planning happens before the apply transaction, leaving a time-of-check/time-of-use race.

## Goals / Non-Goals

**Goals:**

- Keep reconcile as the flexible write path for agents and future adapters.
- Preserve backward compatibility for current manifests that omit operation fields.
- Add soft archive operations while keeping hard delete out of the public surface.
- Make reconcile apply atomic across planning, writes, event recording, and operation audit.
- Record enough audit detail to answer what changed without duplicating large note bodies.
- Make sync events recordable before W&B writeback ships.

**Non-Goals:**

- No hard delete or purge operation.
- No live W&B/Iris/GCS adapters in this phase.
- No dashboard or stable SQL view layer in this phase.
- No complete entity history table; operation audit is bounded and event-oriented.

## Decisions

### Decision: Use `_op=upsert|archive` on manifest rows

All existing manifest rows default to `upsert`. A row with `_op=archive` soft-archives the resolved existing entity by setting `deleted_at` and, where the entity has a status field, setting `status=archived`. `_op=delete` is rejected with a validation error so Fieldbook does not grow a destructive path accidentally.

Supported operations:

- `runs`, `jobs`, `artifacts`, `metrics`, and `notes`: `upsert` and `archive`.
- `custom_attributes`: `upsert` only.
- `sync_events`: append or noop through idempotency; no `_op`.

### Decision: Keep sync events as a dedicated manifest section

JSON manifests gain `sync_events: [...]`. CSV manifests use `entity_type=sync_event`. Sync events are append-only unless an optional `idempotency_key` matches an existing event for the same target system and target identifier, in which case reconcile records a `noop`.

The `sync_events` table gains `reconcile_event_id` and `idempotency_key` so sync provenance can be traced to the reconcile event that recorded it.

Required sync-event fields are `target_system` and `status`. Optional fields are `target_identifier`, `run_id`, `job_id`, `error_message`, `idempotency_key`, and `attrs`. Valid statuses are `pending`, `synced`, `failed`, and `skipped`. `_op` is invalid on sync-event rows.

### Decision: Plan inside the transaction

Dry-run opens a deferred read transaction, builds the plan, returns it, and rolls back. Apply opens `BEGIN IMMEDIATE`, builds the plan, applies all operations, records the reconcile event and operation audit, then commits. This keeps planning and applying on one consistent snapshot and prevents concurrent writers from invalidating the plan during apply.

### Decision: Audit operations in a sibling table

`reconcile_events` keeps its summary count fields for existing readers and gains richer counts. A new `reconcile_operations` table stores one row per normalized operation with event ID, operation index, entity, action, entity ID, bounded input JSON, and field-level diff JSON for updates.

The full count shape is:

```json
{
  "insert": {"runs": 1},
  "update": {"jobs": 1},
  "archive": {"notes": 1},
  "sync_event": 1,
  "noop": {"sync_events": 1},
  "total": 5
}
```

`insert`, `update`, `archive`, and `noop` are per-entity dictionaries. `sync_event` is the number of sync-event rows inserted. Dry-run and apply return the same count shape. `reconcile_events.inserts_json` and `updates_json` stay as summary maps for existing readers; `counts_json` stores the full shape.

`reconcile_operations` columns:

- `id TEXT PRIMARY KEY`
- `reconcile_event_id TEXT NOT NULL REFERENCES reconcile_events(id)`
- `op_index INTEGER NOT NULL`
- `entity TEXT NOT NULL`
- `action TEXT NOT NULL`
- `entity_id TEXT`
- `input_json TEXT NOT NULL DEFAULT '{}'`
- `diff_json TEXT NOT NULL DEFAULT '{}'`

`(reconcile_event_id, op_index)` is unique. Indexes cover `(reconcile_event_id, op_index)` and `(entity, entity_id)`. Allowed actions are `insert`, `update`, `archive`, `noop`, and `sync_event`. Allowed entities are `runs`, `jobs`, `artifacts`, `metrics`, `notes`, `custom_attributes`, and `sync_events`.

Audit bodies are bounded. For note bodies longer than 200 Unicode characters, audit input and diff values record a SHA-256 hash, UTF-8 byte count, and 200-character preview rather than the full body.

### Decision: Add external-ID uniqueness with migration precheck

Runs and jobs get partial unique indexes on non-archived `(external_system, external_id)` where both fields are non-null. The migration must fail with an actionable error if existing ledgers already contain duplicates.

The migration precheck is implemented as a Python migration hook in `db.py` before applying version 5. It checks the same predicate as the partial unique indexes: `deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL`. The error message includes duplicate table names and row IDs.

### Decision: Add parent run links

`runs.parent_run_id` records provenance for runs derived from another run. The value must reference an existing run and must not equal the run's own ID.

### Decision: Add `fieldbook reconcile log`

`fieldbook reconcile log` returns recent reconcile events newest-first. `--event <id>` or `--operations` includes operation details. JSON event output includes stable `counts` with insert, update, archive, sync_event, noop, and total fields.

Supported filters are `--source`, `--since`, `--before`, and `--limit`. The default limit is 20. `--operations` without `--event` expands operations for the returned events only, still bounded by `--limit`.

### Decision: Treat unchanged upserts as noops

An upsert that resolves an existing row and produces no changed SQL fields records `noop` instead of `update`. This keeps reconcile logs useful and avoids writing `updated_at` when no ledger state changed.

### Decision: Apply in dependency order

Reconcile applies inserts and updates before archives. Within inserts and updates, entity order is runs, jobs, artifacts, metrics, notes, custom attributes, then sync events. Archives are single-row soft archives and do not cascade.

## Risks / Trade-offs

- **Risk: archive operation semantics differ by entity** -> Use soft-delete consistently and set `status=archived` only where the entity has a status column.
- **Risk: operation audit grows too large** -> Bound note body audit and store diffs rather than full pre-images.
- **Risk: unique-index migration fails on dogfood ledgers** -> Prefer failing early with duplicate row IDs to silently coalescing rows.
- **Risk: transaction changes disturb existing tests** -> Preserve dry-run/apply JSON shape where possible, while adding richer count and operation details.
