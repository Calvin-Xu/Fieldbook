CREATE TABLE IF NOT EXISTS refresh_events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    experiment_id TEXT REFERENCES experiments(id),
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    snapshot_path TEXT,
    manifest_path TEXT,
    debug_path TEXT,
    reconcile_event_id TEXT REFERENCES reconcile_events(id),
    counts_json TEXT NOT NULL DEFAULT '{}',
    command_argv_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_refresh_events_source_finished
ON refresh_events(source, finished_at);

CREATE INDEX IF NOT EXISTS idx_refresh_events_status_finished
ON refresh_events(status, finished_at);

CREATE VIEW IF NOT EXISTS v_refresh_log_v1 AS
SELECT
    id AS refresh_event_id,
    source,
    experiment_id,
    session_id,
    status,
    stage,
    started_at,
    finished_at,
    snapshot_path,
    manifest_path,
    debug_path,
    reconcile_event_id,
    counts_json,
    command_argv_json,
    error_message,
    attrs_json
FROM refresh_events;
