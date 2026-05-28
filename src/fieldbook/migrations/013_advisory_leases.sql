CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('experiment', 'run', 'job')),
    entity_id TEXT NOT NULL,
    owner_agent TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    claimed_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT,
    released_at TEXT,
    released_by TEXT,
    released_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    release_reason TEXT,
    previous_lease_id TEXT REFERENCES leases(id),
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_leases_active_entity
ON leases(entity_type, entity_id)
WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_leases_owner_active
ON leases(owner_agent, heartbeat_at)
WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_leases_session_active
ON leases(session_id)
WHERE session_id IS NOT NULL AND released_at IS NULL;

CREATE VIEW IF NOT EXISTS v_leases_active_v1 AS
SELECT
    id AS lease_id,
    entity_type,
    entity_id,
    owner_agent,
    session_id,
    claimed_at,
    heartbeat_at,
    expires_at,
    attrs_json
FROM leases
WHERE released_at IS NULL
  AND (expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

CREATE VIEW IF NOT EXISTS v_leases_stale_v1 AS
SELECT
    id AS lease_id,
    entity_type,
    entity_id,
    owner_agent,
    session_id,
    claimed_at,
    heartbeat_at,
    expires_at,
    1.0 AS stale_threshold_hours,
    (julianday('now') - julianday(replace(replace(heartbeat_at, 'Z', '+00:00'), 'T', ' '))) * 24.0 AS stale_hours,
    attrs_json
FROM leases
WHERE released_at IS NULL
  AND (expires_at IS NULL OR expires_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
  AND heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour');

CREATE VIEW IF NOT EXISTS v_lease_history_v1 AS
SELECT
    id AS lease_id,
    entity_type,
    entity_id,
    owner_agent,
    session_id,
    claimed_at,
    heartbeat_at,
    expires_at,
    released_at,
    released_by,
    released_session_id,
    release_reason,
    previous_lease_id,
    attrs_json
FROM leases;

CREATE VIEW IF NOT EXISTS v_experiment_ownership_v1 AS
SELECT
    e.id AS experiment_id,
    l.id AS lease_id,
    l.owner_agent,
    l.session_id,
    l.heartbeat_at,
    l.expires_at,
    CASE WHEN l.id IS NOT NULL AND l.heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') THEN 1 ELSE 0 END AS is_stale,
    CASE WHEN l.id IS NOT NULL AND l.expires_at IS NOT NULL AND l.expires_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now') THEN 1 ELSE 0 END AS is_expired
FROM experiments e
LEFT JOIN leases l ON l.entity_type = 'experiment' AND l.entity_id = e.id AND l.released_at IS NULL
WHERE e.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_run_ownership_v1 AS
SELECT
    r.id AS run_id,
    l.id AS lease_id,
    l.owner_agent,
    l.session_id,
    l.heartbeat_at,
    l.expires_at,
    CASE WHEN l.id IS NOT NULL AND l.heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') THEN 1 ELSE 0 END AS is_stale,
    CASE WHEN l.id IS NOT NULL AND l.expires_at IS NOT NULL AND l.expires_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now') THEN 1 ELSE 0 END AS is_expired
FROM runs r
LEFT JOIN leases l ON l.entity_type = 'run' AND l.entity_id = r.id AND l.released_at IS NULL
WHERE r.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_job_ownership_v1 AS
WITH RECURSIVE retry_depth(job_id, depth) AS (
    SELECT id, 0 FROM jobs WHERE retry_of IS NULL
    UNION ALL
    SELECT j.id, retry_depth.depth + 1
    FROM jobs j
    JOIN retry_depth ON j.retry_of = retry_depth.job_id
    WHERE retry_depth.depth < 32
)
SELECT
    j.id AS job_id,
    l.id AS lease_id,
    l.owner_agent,
    l.session_id,
    l.heartbeat_at,
    l.expires_at,
    COALESCE(rd.depth, 0) AS retry_depth,
    CASE WHEN l.id IS NOT NULL AND l.heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') THEN 1 ELSE 0 END AS is_stale,
    CASE WHEN l.id IS NOT NULL AND l.expires_at IS NOT NULL AND l.expires_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now') THEN 1 ELSE 0 END AS is_expired
FROM jobs j
LEFT JOIN retry_depth rd ON rd.job_id = j.id
LEFT JOIN leases l ON l.entity_type = 'job' AND l.entity_id = j.id AND l.released_at IS NULL
WHERE j.deleted_at IS NULL;
