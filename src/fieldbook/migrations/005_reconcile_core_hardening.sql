ALTER TABLE runs ADD COLUMN parent_run_id TEXT REFERENCES runs(id);

CREATE INDEX IF NOT EXISTS idx_runs_parent
ON runs(parent_run_id)
WHERE parent_run_id IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE reconcile_events ADD COLUMN counts_json TEXT NOT NULL
DEFAULT '{"insert":{},"update":{},"archive":{},"sync_event":0,"noop":{},"total":0}';

ALTER TABLE sync_events ADD COLUMN reconcile_event_id TEXT REFERENCES reconcile_events(id);

ALTER TABLE sync_events ADD COLUMN idempotency_key TEXT;

CREATE TABLE IF NOT EXISTS reconcile_operations (
    id TEXT PRIMARY KEY,
    reconcile_event_id TEXT NOT NULL REFERENCES reconcile_events(id),
    op_index INTEGER NOT NULL,
    entity TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_id TEXT,
    input_json TEXT NOT NULL DEFAULT '{}',
    diff_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (reconcile_event_id, op_index)
);

CREATE INDEX IF NOT EXISTS idx_reconcile_ops_event
ON reconcile_operations(reconcile_event_id, op_index);

CREATE INDEX IF NOT EXISTS idx_reconcile_ops_entity
ON reconcile_operations(entity, entity_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_external_unique
ON runs(external_system, external_id)
WHERE deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_external_unique
ON jobs(external_system, external_id)
WHERE deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_events_idempotency
ON sync_events(target_system, COALESCE(target_identifier, ''), idempotency_key)
WHERE idempotency_key IS NOT NULL;
