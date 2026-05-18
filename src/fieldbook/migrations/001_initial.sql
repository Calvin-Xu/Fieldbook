CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experiment_tags (
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (experiment_id, tag)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    external_system TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    run_id TEXT NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, run_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT REFERENCES experiments(id),
    run_id TEXT REFERENCES runs(id),
    name TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    command TEXT,
    launcher TEXT,
    external_system TEXT,
    external_id TEXT,
    failure_reason TEXT,
    code_commit TEXT,
    code_dirty INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    job_id TEXT REFERENCES jobs(id),
    type TEXT NOT NULL,
    uri TEXT NOT NULL,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    step TEXT,
    split TEXT,
    source_job_id TEXT REFERENCES jobs(id),
    source_artifact_id TEXT REFERENCES artifacts(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_metrics_idempotency
ON metrics (
    run_id,
    metric_name,
    COALESCE(step, ''),
    COALESCE(split, ''),
    COALESCE(source_job_id, ''),
    COALESCE(source_artifact_id, '')
)
WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    note_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    body TEXT NOT NULL,
    author TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS reconcile_events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT REFERENCES experiments(id),
    source TEXT NOT NULL,
    inserts_json TEXT NOT NULL DEFAULT '{}',
    updates_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sync_events (
    id TEXT PRIMARY KEY,
    target_system TEXT NOT NULL,
    target_identifier TEXT,
    status TEXT NOT NULL,
    run_id TEXT REFERENCES runs(id),
    job_id TEXT REFERENCES jobs(id),
    error_message TEXT,
    created_at TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_experiments_status_updated
ON experiments(status, updated_at)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_experiment_tags_tag
ON experiment_tags(tag);

CREATE INDEX IF NOT EXISTS idx_experiment_runs_run
ON experiment_runs(run_id);

CREATE INDEX IF NOT EXISTS idx_jobs_experiment_status
ON jobs(experiment_id, status, updated_at)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_run_status
ON jobs(run_id, status, updated_at)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_artifacts_run
ON artifacts(run_id, type, updated_at)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_artifacts_job
ON artifacts(job_id, type, updated_at)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_metrics_run_name
ON metrics(run_id, metric_name)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_notes_entity
ON notes(entity_type, entity_id, status, updated_at)
WHERE deleted_at IS NULL;
