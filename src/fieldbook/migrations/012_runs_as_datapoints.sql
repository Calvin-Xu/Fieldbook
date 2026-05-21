ALTER TABLE runs ADD COLUMN experiment_id TEXT REFERENCES experiments(id);
ALTER TABLE runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'datapoint';

UPDATE runs
SET experiment_id = (
    SELECT er.experiment_id
    FROM experiment_runs er
    JOIN experiments e ON e.id = er.experiment_id
    WHERE er.run_id = runs.id AND e.deleted_at IS NULL
    ORDER BY er.created_at, er.experiment_id
    LIMIT 1
)
WHERE experiment_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_experiment_idempotency
ON runs(experiment_id, idempotency_key)
WHERE experiment_id IS NOT NULL AND idempotency_key IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_runs_experiment_id
ON runs(experiment_id)
WHERE experiment_id IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT NOT NULL REFERENCES jobs(id),
    run_id TEXT NOT NULL REFERENCES runs(id),
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT,
    finished_at TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(job_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_job_runs_run_id
ON job_runs(run_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_job_runs_job_id
ON job_runs(job_id)
WHERE deleted_at IS NULL;

INSERT OR IGNORE INTO job_runs (
    job_id,
    run_id,
    role,
    status,
    started_at,
    finished_at,
    failure_reason,
    created_at,
    updated_at,
    attrs_json
)
SELECT
    id,
    run_id,
    'other',
    status,
    started_at,
    finished_at,
    failure_reason,
    created_at,
    updated_at,
    '{}'
FROM jobs
WHERE run_id IS NOT NULL AND deleted_at IS NULL;

DROP VIEW IF EXISTS v_runs_v1;

CREATE VIEW v_runs_v1 AS
SELECT
    r.id AS id,
    r.id AS run_id,
    r.experiment_id,
    r.name,
    r.description,
    r.status,
    r.kind,
    r.idempotency_key,
    r.external_system,
    r.external_id,
    r.parent_run_id,
    r.created_at,
    r.updated_at,
    r.attrs_json,
    COALESCE((
        SELECT GROUP_CONCAT(er.experiment_id, ',')
        FROM experiment_runs er
        JOIN experiments e ON e.id = er.experiment_id
        WHERE er.run_id = r.id AND e.deleted_at IS NULL
        ORDER BY er.experiment_id
    ), '') AS experiment_ids
FROM runs r
WHERE r.deleted_at IS NULL;

DROP VIEW IF EXISTS v_job_runs_v1;

CREATE VIEW v_job_runs_v1 AS
SELECT
    jr.job_id,
    jr.run_id,
    r.experiment_id,
    jr.role,
    jr.status,
    jr.started_at,
    jr.finished_at,
    jr.failure_reason,
    jr.created_at,
    jr.updated_at,
    jr.attrs_json
FROM job_runs jr
JOIN jobs j ON j.id = jr.job_id
JOIN runs r ON r.id = jr.run_id
WHERE jr.deleted_at IS NULL
  AND j.deleted_at IS NULL
  AND r.deleted_at IS NULL;

DROP VIEW IF EXISTS v_run_summary_v1;

CREATE VIEW v_run_summary_v1 AS
SELECT
    r.id AS run_id,
    r.experiment_id,
    r.name,
    r.status,
    r.kind,
    r.idempotency_key,
    r.parent_run_id,
    r.updated_at,
    COALESCE(GROUP_CONCAT(DISTINCT er.experiment_id), '') AS experiment_ids,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL THEN j.id END) AS job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status = 'failed' THEN j.id END) AS failed_job_count,
    COUNT(DISTINCT CASE WHEN a.deleted_at IS NULL THEN a.id END) AS artifact_count,
    COUNT(DISTINCT CASE WHEN m.deleted_at IS NULL THEN m.id END) AS metric_count
FROM runs r
LEFT JOIN experiment_runs er ON er.run_id = r.id
LEFT JOIN job_runs jr ON jr.run_id = r.id AND jr.deleted_at IS NULL
LEFT JOIN jobs j ON j.id = jr.job_id AND j.deleted_at IS NULL
LEFT JOIN artifacts a ON a.run_id = r.id
LEFT JOIN metrics m ON m.run_id = r.id
WHERE r.deleted_at IS NULL
GROUP BY r.id;

DROP VIEW IF EXISTS v_runs_progress_v1;

CREATE VIEW v_runs_progress_v1 AS
WITH job_edge_summary AS (
    SELECT
        jr.run_id,
        COUNT(*) AS job_edge_count,
        SUM(CASE WHEN jr.role = 'train' AND jr.status IN ('submitting', 'queued', 'running') THEN 1 ELSE 0 END)
            AS train_active_count,
        SUM(CASE WHEN jr.role = 'train' AND jr.status = 'succeeded' THEN 1 ELSE 0 END)
            AS train_succeeded_count,
        SUM(CASE WHEN jr.role = 'eval' AND jr.status = 'succeeded' THEN 1 ELSE 0 END)
            AS eval_succeeded_count,
        SUM(CASE WHEN jr.status IN ('failed', 'killed') THEN 1 ELSE 0 END)
            AS failed_count,
        SUM(CASE WHEN jr.role = 'train' AND jr.status IN ('failed', 'killed') THEN 1 ELSE 0 END)
            AS train_failed_count,
        SUM(CASE WHEN jr.role = 'eval' AND jr.status IN ('failed', 'killed') THEN 1 ELSE 0 END)
            AS eval_failed_count,
        SUM(CASE WHEN jr.role NOT IN ('train', 'eval') AND jr.status IN ('failed', 'killed') THEN 1 ELSE 0 END)
            AS other_failed_count,
        SUM(CASE WHEN jr.status = 'skipped' THEN 1 ELSE 0 END)
            AS skipped_count
    FROM job_runs jr
    JOIN jobs j ON j.id = jr.job_id
    WHERE jr.deleted_at IS NULL AND j.deleted_at IS NULL
    GROUP BY jr.run_id
),
artifact_summary AS (
    SELECT
        run_id,
        MAX(CASE WHEN type = 'checkpoint' THEN 1 ELSE 0 END) AS has_checkpoint,
        MAX(CASE WHEN type = 'eval-result' THEN 1 ELSE 0 END) AS has_eval_result
    FROM artifacts
    WHERE deleted_at IS NULL AND run_id IS NOT NULL
    GROUP BY run_id
),
metric_summary AS (
    SELECT
        run_id,
        COUNT(DISTINCT metric_name) AS metric_count
    FROM metrics
    WHERE deleted_at IS NULL
    GROUP BY run_id
),
required_summary AS (
    SELECT
        r.id AS run_id,
        CASE
            WHEN json_type(e.attrs_json, '$."progress.required_metrics"') = 'array'
            THEN json_array_length(json_extract(e.attrs_json, '$."progress.required_metrics"'))
            ELSE 0
        END AS required_metric_count
    FROM runs r
    LEFT JOIN experiments e ON e.id = r.experiment_id
)
SELECT
    r.experiment_id,
    r.id AS run_id,
    r.name,
    r.kind,
    r.status,
    COALESCE(a.has_checkpoint, 0) AS has_checkpoint,
    COALESCE(a.has_eval_result, 0) AS has_eval_result,
    COALESCE(m.metric_count, 0) AS metric_count,
    COALESCE(j.train_active_count, 0) AS train_active_count,
    COALESCE(j.train_succeeded_count, 0) AS train_succeeded_count,
    COALESCE(j.eval_succeeded_count, 0) AS eval_succeeded_count,
    COALESCE(j.failed_count, 0) AS failed_count,
    COALESCE(j.skipped_count, 0) AS skipped_count,
    COALESCE(j.job_edge_count, 0) AS job_edge_count,
    CASE
        WHEN COALESCE(rs.required_metric_count, 0) > 0
             AND COALESCE(m.metric_count, 0) >= COALESCE(rs.required_metric_count, 0) THEN 'complete'
        WHEN COALESCE(rs.required_metric_count, 0) = 0
             AND (COALESCE(j.eval_succeeded_count, 0) > 0 OR COALESCE(a.has_eval_result, 0) = 1) THEN 'complete'
        WHEN COALESCE(j.train_active_count, 0) > 0 THEN 'training'
        WHEN (COALESCE(j.train_failed_count, 0) > 0 AND COALESCE(j.train_succeeded_count, 0) = 0)
             OR (COALESCE(j.eval_failed_count, 0) > 0 AND COALESCE(j.eval_succeeded_count, 0) = 0)
             OR COALESCE(j.other_failed_count, 0) > 0 THEN 'failed'
        WHEN COALESCE(j.skipped_count, 0) > 0 THEN 'skipped'
        WHEN COALESCE(j.train_succeeded_count, 0) > 0 OR COALESCE(a.has_checkpoint, 0) = 1 THEN 'trained'
        WHEN COALESCE(j.eval_succeeded_count, 0) > 0 OR COALESCE(a.has_eval_result, 0) = 1 THEN 'evaluated'
        WHEN COALESCE(j.job_edge_count, 0) > 0 THEN 'submitted'
        ELSE 'planned'
    END AS phase
FROM runs r
LEFT JOIN job_edge_summary j ON j.run_id = r.id
LEFT JOIN artifact_summary a ON a.run_id = r.id
LEFT JOIN metric_summary m ON m.run_id = r.id
LEFT JOIN required_summary rs ON rs.run_id = r.id
WHERE r.deleted_at IS NULL;
