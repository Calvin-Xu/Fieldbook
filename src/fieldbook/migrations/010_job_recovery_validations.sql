ALTER TABLE jobs ADD COLUMN retry_of TEXT REFERENCES jobs(id);

CREATE INDEX IF NOT EXISTS idx_jobs_retry_of
ON jobs(retry_of)
WHERE retry_of IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS validations (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    expected_value TEXT,
    measured_value TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    source_artifact_id TEXT REFERENCES artifacts(id),
    source_job_id TEXT REFERENCES jobs(id),
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_validations_key
ON validations(entity_type, entity_id, check_name)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_validations_status
ON validations(status, updated_at)
WHERE deleted_at IS NULL;

DROP VIEW IF EXISTS v_jobs_v1;

CREATE VIEW v_jobs_v1 AS
SELECT
    j.id AS id,
    j.id AS job_id,
    j.experiment_id,
    j.run_id,
    j.name,
    j.status,
    j.command,
    j.launcher,
    j.external_system,
    j.external_id,
    j.retry_of,
    j.failure_reason,
    j.code_commit,
    j.code_dirty,
    j.created_at,
    j.updated_at,
    j.started_at,
    j.finished_at,
    j.attrs_json
FROM jobs j
WHERE j.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_validations_v1 AS
SELECT
    v.id AS validation_id,
    v.entity_type,
    v.entity_id,
    v.check_name,
    v.status,
    v.expected_value,
    v.measured_value,
    v.details_json,
    v.source_artifact_id,
    v.source_job_id,
    v.session_id,
    v.created_at,
    v.updated_at,
    v.attrs_json
FROM validations v
WHERE v.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_jobs_with_recovery_v1 AS
WITH RECURSIVE retry_edges(root_id, descendant_id, descendant_status, path, depth) AS (
    SELECT
        parent.id AS root_id,
        child.id AS descendant_id,
        child.status AS descendant_status,
        parent.id || ',' || child.id AS path,
        1 AS depth
    FROM jobs parent
    JOIN jobs child ON child.retry_of = parent.id
    WHERE parent.deleted_at IS NULL AND child.deleted_at IS NULL
    UNION ALL
    SELECT
        retry_edges.root_id,
        child.id AS descendant_id,
        child.status AS descendant_status,
        retry_edges.path || ',' || child.id AS path,
        retry_edges.depth + 1 AS depth
    FROM retry_edges
    JOIN jobs child ON child.retry_of = retry_edges.descendant_id
    WHERE child.deleted_at IS NULL
      AND retry_edges.depth < 32
      AND INSTR(',' || retry_edges.path || ',', ',' || child.id || ',') = 0
),
retry_summary AS (
    SELECT
        root_id,
        MAX(CASE WHEN descendant_status = 'succeeded' THEN 1 ELSE 0 END) AS has_success_descendant,
        MAX(CASE WHEN descendant_status IN ('submitting', 'unknown_submit', 'queued', 'running') THEN 1 ELSE 0 END)
            AS has_active_descendant,
        MIN(CASE WHEN descendant_status = 'succeeded' THEN descendant_id END) AS success_descendant_id,
        MIN(CASE WHEN descendant_status IN ('submitting', 'unknown_submit', 'queued', 'running') THEN descendant_id END)
            AS active_descendant_id
    FROM retry_edges
    GROUP BY root_id
)
SELECT
    j.id AS job_id,
    j.experiment_id,
    j.run_id,
    j.name,
    j.status,
    j.command,
    j.launcher,
    j.retry_of,
    j.external_system,
    j.external_id,
    j.failure_reason,
    j.code_commit,
    j.code_dirty,
    j.created_at,
    j.updated_at,
    j.started_at,
    j.finished_at,
    j.deleted_at,
    j.attrs_json,
    COALESCE(rs.has_success_descendant, 0) AS has_success_descendant,
    COALESCE(rs.has_active_descendant, 0) AS has_active_descendant,
    rs.success_descendant_id,
    rs.active_descendant_id,
    CASE
        WHEN j.status = 'failed' AND COALESCE(rs.has_success_descendant, 0) = 1 THEN 'recovered_failed'
        WHEN j.status = 'failed' AND COALESCE(rs.has_active_descendant, 0) = 1 THEN 'recovery_in_progress'
        WHEN j.status = 'failed' THEN 'blocking_failed'
        ELSE NULL
    END AS retry_state,
    CASE
        WHEN j.status = 'failed' AND COALESCE(rs.has_success_descendant, 0) = 0
             AND COALESCE(rs.has_active_descendant, 0) = 0 THEN 1
        ELSE 0
    END AS is_blocking_failed,
    CASE
        WHEN j.status = 'failed' AND COALESCE(rs.has_success_descendant, 0) = 0
             AND COALESCE(rs.has_active_descendant, 0) = 1 THEN 1
        ELSE 0
    END AS is_recovery_in_progress,
    CASE
        WHEN j.status = 'failed' AND COALESCE(rs.has_success_descendant, 0) = 1 THEN 1
        ELSE 0
    END AS is_recovered_failed,
    CASE WHEN j.status IN ('submitting', 'unknown_submit') THEN 1 ELSE 0 END AS is_submission_uncertain
FROM jobs j
LEFT JOIN retry_summary rs ON rs.root_id = j.id
WHERE j.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_experiment_blockers_v1 AS
SELECT
    job_id AS entity_id,
    experiment_id,
    'job' AS entity_type,
    'blocking_failed_job' AS blocker_type,
    status,
    updated_at,
    failure_reason AS message
FROM v_jobs_with_recovery_v1
WHERE is_blocking_failed = 1
UNION ALL
SELECT
    job_id AS entity_id,
    experiment_id,
    'job' AS entity_type,
    CASE WHEN status = 'submitting' THEN 'submission_in_progress' ELSE 'submission_unknown' END AS blocker_type,
    status,
    updated_at,
    failure_reason AS message
FROM v_jobs_with_recovery_v1
WHERE status IN ('submitting', 'unknown_submit')
UNION ALL
SELECT
    validation_id AS entity_id,
    entity_id AS experiment_id,
    'validation' AS entity_type,
    CASE WHEN status = 'fail' THEN 'validation_failed' ELSE 'validation_unknown_blocking' END AS blocker_type,
    status,
    updated_at,
    check_name AS message
FROM v_validations_v1
WHERE entity_type = 'experiment'
  AND (status = 'fail' OR (status = 'unknown' AND INSTR(attrs_json, '"validation.blocking":true') > 0));

DROP VIEW IF EXISTS v_jobs_needing_attention_v1;

CREATE VIEW v_jobs_needing_attention_v1 AS
SELECT
    j.id AS job_id,
    j.experiment_id,
    j.run_id,
    j.name,
    j.status,
    j.launcher,
    j.external_system,
    j.external_id,
    j.retry_of,
    j.failure_reason,
    j.updated_at,
    j.started_at,
    j.finished_at
FROM jobs j
WHERE j.deleted_at IS NULL AND j.status IN ('submitting', 'unknown_submit', 'queued', 'running', 'failed');
