## ADDED Requirements

### Requirement: Support explicit reconcile operations
The system SHALL support explicit reconcile row operations while preserving current upsert behavior.

#### Scenario: Default operation is upsert
- **WHEN** a reconcile manifest row omits `_op`
- **THEN** the system treats the row as `_op=upsert`

#### Scenario: Archive existing entity
- **WHEN** a reconcile manifest row for a run, job, artifact, metric, or note has `_op=archive`
- **THEN** the system soft-archives the resolved existing row and records an `archive` reconcile operation

#### Scenario: Archive already archived entity
- **WHEN** a reconcile manifest archives a row that is already archived
- **THEN** the system records a `noop` operation and does not change the row

#### Scenario: Reject delete operation
- **WHEN** a reconcile manifest row has `_op=delete`
- **THEN** the system rejects the manifest with a validation error

#### Scenario: Reject unsupported operation
- **WHEN** a reconcile manifest row has an operation other than `upsert` or `archive`
- **THEN** the system rejects the manifest with a validation error

#### Scenario: Reject custom attribute archive
- **WHEN** a reconcile manifest custom attribute row has `_op=archive`
- **THEN** the system rejects the manifest with a validation error

#### Scenario: Strip operation field before SQL
- **WHEN** reconcile applies a manifest row with `_op`
- **THEN** `_op` is used only for planning and is not written into entity SQL columns or attrs

#### Scenario: Unchanged upsert is noop
- **WHEN** an upsert resolves an existing row and no persisted field would change
- **THEN** the system records a `noop` operation and leaves `updated_at` unchanged

### Requirement: Reconcile with a consistent transaction snapshot
The system SHALL plan and apply reconcile operations using one consistent database snapshot.

#### Scenario: Dry-run transaction
- **WHEN** a user runs reconcile in dry-run mode
- **THEN** the system opens a read transaction, builds the plan, rolls back, and leaves the ledger unchanged

#### Scenario: Apply transaction
- **WHEN** a user runs reconcile with apply enabled
- **THEN** the system opens a `BEGIN IMMEDIATE` transaction, builds the plan, applies all operations, records audit rows, and commits

#### Scenario: Atomic failure
- **WHEN** any operation in an applied reconcile manifest fails
- **THEN** the system rolls back all entity writes, sync-event writes, reconcile events, and reconcile operation audit rows from that manifest

### Requirement: Deduplicate manifest-local external identifiers
The system SHALL resolve duplicate run and job external identifiers within one manifest before applying SQL writes.

#### Scenario: Duplicate run external identifier in manifest
- **WHEN** a manifest contains multiple run rows without explicit IDs that share the same non-null `(external_system, external_id)`
- **THEN** the planner treats them as one target run and uses the last row's supplied fields in source order for overlapping values

#### Scenario: Duplicate job external identifier in manifest
- **WHEN** a manifest contains multiple job rows without explicit IDs that share the same non-null `(external_system, external_id)`
- **THEN** the planner treats them as one target job and uses the last row's supplied fields in source order for overlapping values

#### Scenario: Dedupe does not cross entity types
- **WHEN** a run row and a job row share the same external system and external identifier
- **THEN** the planner treats them as separate entity targets

### Requirement: Ingest sync events through reconcile
The system SHALL allow reconcile manifests to append external sync events.

#### Scenario: Validate sync event fields
- **WHEN** a sync event omits `target_system` or `status`, or has a status outside `pending`, `synced`, `failed`, or `skipped`
- **THEN** the system rejects the manifest with a validation error

#### Scenario: Reject sync event operation field
- **WHEN** a sync event row includes `_op`
- **THEN** the system rejects the manifest with a validation error

#### Scenario: Insert sync event
- **WHEN** a manifest contains a `sync_events` entry
- **THEN** the system records a sync event in the same reconcile transaction and links it to the reconcile event

#### Scenario: Idempotent sync event
- **WHEN** a sync event has an `idempotency_key` matching an existing sync event with the same target system and target identifier
- **THEN** the system records a `noop` reconcile operation and does not insert a duplicate sync event

#### Scenario: Sync-only manifest
- **WHEN** a manifest contains only `sync_events`
- **THEN** reconcile can dry-run or apply successfully

#### Scenario: Sync-only manifest without experiment
- **WHEN** a sync-only manifest is applied without an experiment reference
- **THEN** the reconcile event is recorded with `experiment_id=NULL`

### Requirement: Record bounded reconcile operation audit
The system SHALL persist one bounded operation audit row for every planned reconcile operation.

#### Scenario: Operation audit schema
- **WHEN** the ledger is migrated
- **THEN** `reconcile_operations` has `id`, `reconcile_event_id`, `op_index`, `entity`, `action`, `entity_id`, `input_json`, and `diff_json` columns, with unique `(reconcile_event_id, op_index)`

#### Scenario: Audit insert update archive and noop
- **WHEN** reconcile applies operations
- **THEN** each operation is recorded with event ID, zero-based operation index, entity, action, affected entity ID, normalized input JSON, and diff JSON

#### Scenario: Audit sync event
- **WHEN** reconcile inserts or noops a sync event
- **THEN** the operation audit records entity `sync_events` and action `sync_event` or `noop`

#### Scenario: Audit update diff
- **WHEN** reconcile updates an existing row
- **THEN** the operation audit records only fields whose values changed

#### Scenario: Bound note body audit
- **WHEN** an audited operation input includes a note body longer than 200 Unicode characters
- **THEN** the audit input stores body byte count, SHA-256 hash, and a 200-character preview instead of the full body

#### Scenario: Bound note body diff audit
- **WHEN** an audited update diff includes an old or new note body longer than 200 Unicode characters
- **THEN** the diff value stores body byte count, SHA-256 hash, and a 200-character preview instead of the full body

### Requirement: Record full reconcile counts
The system SHALL expose a stable reconcile count shape for dry-runs, applied events, and reconcile logs.

#### Scenario: Count shape
- **WHEN** reconcile returns counts
- **THEN** `insert`, `update`, `archive`, and `noop` are per-entity dictionaries, `sync_event` is an inserted sync-event count, and `total` is the number of planned operations

#### Scenario: Persist count shape
- **WHEN** reconcile applies operations
- **THEN** `reconcile_events.counts_json` stores the full count shape while `inserts_json` and `updates_json` retain legacy summary maps

### Requirement: Apply reconcile operations in dependency order
The system SHALL apply reconcile operations in deterministic dependency order without cascading archive operations.

#### Scenario: Apply inserts and updates in dependency order
- **WHEN** a manifest contains inserts or updates across entity types
- **THEN** the system applies them in run, job, artifact, metric, note, custom attribute, and sync-event order

#### Scenario: Apply archives after upserts
- **WHEN** a manifest contains both upsert and archive operations
- **THEN** the system applies upserts before archives, and archives only the explicitly targeted rows

### Requirement: Expose reconcile logs
The system SHALL expose recent reconcile events and operation details through the CLI.

#### Scenario: List reconcile events
- **WHEN** a user runs `fieldbook reconcile log`
- **THEN** the system returns recent reconcile events newest-first with stable counts for `insert`, `update`, `archive`, `sync_event`, `noop`, and `total`

#### Scenario: Default reconcile log limit
- **WHEN** a user runs `fieldbook reconcile log` without `--limit`
- **THEN** the system returns at most 20 events

#### Scenario: Show one reconcile event
- **WHEN** a user runs `fieldbook reconcile log --event <id>`
- **THEN** the system returns the selected event with its operation audit rows

#### Scenario: Filter reconcile log
- **WHEN** a user supplies `--source`, `--since`, `--before`, or `--limit`
- **THEN** the system returns only matching reconcile events

#### Scenario: Expand operations for bounded event list
- **WHEN** a user supplies `--operations` without `--event`
- **THEN** the system expands operations for only the returned event list bounded by `--limit`

### Requirement: Track run parent provenance
The system SHALL allow runs to reference a parent run.

#### Scenario: Store parent run
- **WHEN** a run is created or reconciled with a valid `parent_run_id`
- **THEN** the system stores the parent run link

#### Scenario: Reject missing parent run
- **WHEN** a run is created or reconciled with `parent_run_id` that does not reference an existing run
- **THEN** the system rejects the write with a validation error

#### Scenario: Reject self parent
- **WHEN** a run is created or reconciled with `parent_run_id` equal to its own ID
- **THEN** the system rejects the write with a validation error

### Requirement: Enforce active external identifier uniqueness
The system SHALL prevent duplicate active run and job external identifiers.

#### Scenario: Reject duplicate active run external identifier
- **WHEN** a non-archived run already has a non-null `(external_system, external_id)`
- **THEN** another non-archived run cannot use the same pair

#### Scenario: Allow archived external identifier reuse
- **WHEN** a run or job with an external identifier is archived
- **THEN** a new non-archived run or job may use the same external identifier

#### Scenario: Migration blocks pre-existing duplicates
- **WHEN** a ledger migration finds pre-existing non-archived duplicate run or job external identifiers
- **THEN** migration aborts with an actionable error that includes the conflicting table names and row IDs

#### Scenario: Migration precheck mirrors unique index predicate
- **WHEN** migration checks for duplicate external identifiers
- **THEN** it considers only rows where `deleted_at IS NULL` and both `external_system` and `external_id` are non-null

### Requirement: Preserve sync event attributes
The system SHALL store namespaced sync-event attributes from reconcile manifests.

#### Scenario: Sync event attrs roundtrip
- **WHEN** a sync-event manifest entry includes `attrs`
- **THEN** the system validates and stores those attributes on the sync event row

### Requirement: Resolve metric archives
The system SHALL archive metrics by ID or by the same idempotency key used for metric upsert.

#### Scenario: Archive metric by id
- **WHEN** a metric reconcile row has `_op=archive` and an existing metric ID
- **THEN** the system soft-archives that metric

#### Scenario: Archive metric by metric key
- **WHEN** a metric reconcile row has `_op=archive` and supplies run, metric name, step, split, source job, and source artifact fields matching an existing metric
- **THEN** the system soft-archives that metric
