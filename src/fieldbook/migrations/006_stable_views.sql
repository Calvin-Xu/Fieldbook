CREATE VIEW IF NOT EXISTS v_experiments_v1 AS
SELECT
    e.id AS experiment_id,
    e.name,
    e.description,
    e.status,
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

CREATE VIEW IF NOT EXISTS v_runs_v1 AS
SELECT
    r.id AS run_id,
    r.name,
    r.description,
    r.status,
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

CREATE VIEW IF NOT EXISTS v_jobs_v1 AS
SELECT
    j.id AS job_id,
    j.experiment_id,
    j.run_id,
    j.name,
    j.status,
    j.command,
    j.launcher,
    j.external_system,
    j.external_id,
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

CREATE VIEW IF NOT EXISTS v_artifacts_v1 AS
SELECT
    a.id AS artifact_id,
    a.experiment_id,
    a.run_id,
    a.job_id,
    a.type,
    a.uri,
    a.content_hash,
    a.created_at,
    a.updated_at,
    a.attrs_json
FROM artifacts a
WHERE a.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_metrics_long_v1 AS
SELECT
    er.experiment_id,
    r.id AS run_id,
    r.name AS run_name,
    m.id AS metric_id,
    m.metric_name,
    m.value,
    m.step,
    m.split,
    m.source_job_id,
    m.source_artifact_id,
    m.updated_at
FROM experiment_runs er
JOIN runs r ON r.id = er.run_id
JOIN metrics m ON m.run_id = r.id
WHERE r.deleted_at IS NULL AND m.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_experiment_summary_v1 AS
SELECT
    e.id AS experiment_id,
    e.name,
    e.status,
    e.updated_at,
    COUNT(DISTINCT CASE WHEN r.deleted_at IS NULL THEN r.id END) AS run_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL THEN j.id END) AS job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status = 'failed' THEN j.id END) AS failed_job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status = 'running' THEN j.id END) AS running_job_count,
    COUNT(DISTINCT CASE WHEN a.deleted_at IS NULL THEN a.id END) AS artifact_count,
    COUNT(DISTINCT CASE WHEN m.deleted_at IS NULL THEN m.id END) AS metric_count,
    COUNT(DISTINCT CASE WHEN n.deleted_at IS NULL AND n.status = 'open' THEN n.id END) AS open_note_count
FROM experiments e
LEFT JOIN experiment_runs er ON er.experiment_id = e.id
LEFT JOIN runs r ON r.id = er.run_id
LEFT JOIN jobs j ON j.experiment_id = e.id OR j.run_id = r.id
LEFT JOIN artifacts a ON a.experiment_id = e.id OR a.run_id = r.id OR a.job_id = j.id
LEFT JOIN metrics m ON m.run_id = r.id
LEFT JOIN notes n ON n.entity_type = 'experiment' AND n.entity_id = e.id
WHERE e.deleted_at IS NULL
GROUP BY e.id;

CREATE VIEW IF NOT EXISTS v_run_summary_v1 AS
SELECT
    r.id AS run_id,
    r.name,
    r.status,
    r.parent_run_id,
    r.updated_at,
    COALESCE(GROUP_CONCAT(DISTINCT er.experiment_id), '') AS experiment_ids,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL THEN j.id END) AS job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status = 'failed' THEN j.id END) AS failed_job_count,
    COUNT(DISTINCT CASE WHEN a.deleted_at IS NULL THEN a.id END) AS artifact_count,
    COUNT(DISTINCT CASE WHEN m.deleted_at IS NULL THEN m.id END) AS metric_count
FROM runs r
LEFT JOIN experiment_runs er ON er.run_id = r.id
LEFT JOIN jobs j ON j.run_id = r.id
LEFT JOIN artifacts a ON a.run_id = r.id
LEFT JOIN metrics m ON m.run_id = r.id
WHERE r.deleted_at IS NULL
GROUP BY r.id;

CREATE VIEW IF NOT EXISTS v_jobs_needing_attention_v1 AS
SELECT
    j.id AS job_id,
    j.experiment_id,
    j.run_id,
    j.name,
    j.status,
    j.launcher,
    j.external_system,
    j.external_id,
    j.failure_reason,
    j.updated_at,
    j.started_at,
    j.finished_at
FROM jobs j
WHERE j.deleted_at IS NULL AND j.status IN ('queued', 'running', 'failed');

CREATE VIEW IF NOT EXISTS v_artifact_latest_per_type_v1 AS
SELECT
    artifact_id,
    experiment_id,
    run_id,
    job_id,
    type,
    uri,
    content_hash,
    updated_at
FROM (
    SELECT
        a.id AS artifact_id,
        a.experiment_id,
        a.run_id,
        a.job_id,
        a.type,
        a.uri,
        a.content_hash,
        a.updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(a.experiment_id, ''), COALESCE(a.run_id, ''), COALESCE(a.job_id, ''), a.type
            ORDER BY a.updated_at DESC, a.id DESC
        ) AS rn
    FROM artifacts a
    WHERE a.deleted_at IS NULL
)
WHERE rn = 1;

CREATE VIEW IF NOT EXISTS v_metric_coverage_v1 AS
WITH experiment_run_counts AS (
    SELECT er.experiment_id, COUNT(DISTINCT r.id) AS total_runs
    FROM experiment_runs er
    JOIN runs r ON r.id = er.run_id
    WHERE r.deleted_at IS NULL
    GROUP BY er.experiment_id
),
metric_run_counts AS (
    SELECT er.experiment_id, m.metric_name, COUNT(DISTINCT r.id) AS run_count
    FROM experiment_runs er
    JOIN runs r ON r.id = er.run_id
    JOIN metrics m ON m.run_id = r.id
    WHERE r.deleted_at IS NULL AND m.deleted_at IS NULL
    GROUP BY er.experiment_id, m.metric_name
)
SELECT
    mrc.experiment_id,
    mrc.metric_name,
    mrc.run_count,
    erc.total_runs,
    CASE WHEN erc.total_runs = 0 THEN 0.0 ELSE CAST(mrc.run_count AS REAL) / erc.total_runs END AS coverage
FROM metric_run_counts mrc
JOIN experiment_run_counts erc ON erc.experiment_id = mrc.experiment_id;

CREATE VIEW IF NOT EXISTS v_wandb_sync_coverage_v1 AS
WITH wandb_sync AS (
    SELECT
        r.id AS run_id,
        s.status,
        s.created_at,
        ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY s.created_at DESC, s.id DESC) AS rn,
        COUNT(*) OVER (PARTITION BY r.id) AS sync_count
    FROM runs r
    JOIN sync_events s
        ON s.target_system = 'wandb'
        AND (s.run_id = r.id OR (r.external_id IS NOT NULL AND s.target_identifier = r.external_id))
    WHERE r.deleted_at IS NULL
)
SELECT
    r.id AS run_id,
    r.name AS run_name,
    r.external_system,
    r.external_id,
    CASE WHEN r.external_system = 'wandb' AND r.external_id IS NOT NULL THEN 1 ELSE 0 END AS has_wandb_external_id,
    ws.status AS latest_wandb_sync_status,
    ws.created_at AS latest_wandb_sync_at,
    COALESCE(ws.sync_count, 0) AS wandb_sync_count
FROM runs r
LEFT JOIN wandb_sync ws ON ws.run_id = r.id AND ws.rn = 1
WHERE r.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_reconcile_log_v1 AS
SELECT
    re.id AS reconcile_event_id,
    re.experiment_id,
    re.source,
    re.created_at,
    re.counts_json,
    re.inserts_json,
    re.updates_json,
    COUNT(ro.id) AS operation_count
FROM reconcile_events re
LEFT JOIN reconcile_operations ro ON ro.reconcile_event_id = re.id
GROUP BY re.id;
