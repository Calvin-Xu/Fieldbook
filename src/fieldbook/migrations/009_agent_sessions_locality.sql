ALTER TABLE experiments ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_experiments_idempotency
ON experiments(idempotency_key)
WHERE deleted_at IS NULL AND idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL,
    experiment_id TEXT REFERENCES experiments(id),
    agent TEXT NOT NULL,
    cwd TEXT,
    git_root TEXT,
    git_worktree_dir TEXT,
    git_branch TEXT,
    git_commit TEXT,
    intent TEXT,
    started_at TEXT NOT NULL,
    last_touch_at TEXT NOT NULL,
    ended_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_cwd_open
ON sessions(agent, cwd, ended_at);

CREATE INDEX IF NOT EXISTS idx_sessions_experiment_time
ON sessions(experiment_id, started_at, id);

ALTER TABLE reconcile_events ADD COLUMN session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL;

INSERT INTO schema_metadata (key, value, updated_at)
SELECT
    'ledger_id',
    lower(
        hex(randomblob(4)) || '-' ||
        hex(randomblob(2)) || '-4' ||
        substr(hex(randomblob(2)), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) ||
        substr(hex(randomblob(2)), 2) || '-' ||
        hex(randomblob(6))
    ),
    datetime('now')
WHERE NOT EXISTS (SELECT 1 FROM schema_metadata WHERE key = 'ledger_id');

DROP VIEW IF EXISTS v_experiments_v1;

CREATE VIEW v_experiments_v1 AS
SELECT
    e.id AS experiment_id,
    e.name,
    e.description,
    e.status,
    e.idempotency_key,
    e.created_at,
    e.updated_at,
    e.attrs_json,
    COALESCE((
        SELECT GROUP_CONCAT(t.tag, ',')
        FROM experiment_tags t
        WHERE t.experiment_id = e.id
        ORDER BY t.tag
    ), '') AS tags
FROM experiments e
WHERE e.deleted_at IS NULL;

DROP VIEW IF EXISTS v_reconcile_log_v1;

CREATE VIEW v_reconcile_log_v1 AS
SELECT
    re.id AS reconcile_event_id,
    re.experiment_id,
    re.session_id,
    re.source,
    re.created_at,
    re.counts_json,
    re.inserts_json,
    re.updates_json,
    COUNT(ro.id) AS operation_count
FROM reconcile_events re
LEFT JOIN reconcile_operations ro ON ro.reconcile_event_id = re.id
GROUP BY re.id;

CREATE VIEW IF NOT EXISTS v_sessions_v1 AS
SELECT
    s.id AS session_id,
    s.ledger_id,
    s.experiment_id,
    s.agent,
    s.cwd,
    s.git_root,
    s.git_worktree_dir,
    s.git_branch,
    s.git_commit,
    s.intent,
    s.started_at,
    s.last_touch_at,
    s.ended_at,
    s.attrs_json
FROM sessions s;

CREATE VIEW IF NOT EXISTS v_experiment_session_history_v1 AS
SELECT
    s.experiment_id,
    s.id AS session_id,
    s.ledger_id,
    s.agent,
    s.cwd,
    s.git_branch,
    s.git_commit,
    s.intent,
    s.started_at,
    s.last_touch_at,
    s.ended_at,
    s.attrs_json
FROM sessions s
WHERE s.experiment_id IS NOT NULL
ORDER BY s.started_at DESC, s.id DESC;
