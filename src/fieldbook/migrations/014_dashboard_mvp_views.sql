CREATE VIEW IF NOT EXISTS v_dashboard_experiments_v1 AS
SELECT
    e.id AS experiment_id,
    e.name,
    e.status,
    e.created_at,
    e.updated_at,
    e.deleted_at,
    COUNT(DISTINCT CASE WHEN r.deleted_at IS NULL THEN r.id END) AS run_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL THEN j.id END) AS job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status = 'failed' THEN j.id END) AS failed_job_count,
    COUNT(DISTINCT CASE WHEN j.deleted_at IS NULL AND j.status IN ('submitting', 'unknown_submit', 'queued', 'running') THEN j.id END) AS active_job_count,
    COUNT(DISTINCT CASE WHEN v.deleted_at IS NULL AND v.status = 'fail' THEN v.id END) AS failing_validation_count,
    COUNT(DISTINCT CASE WHEN l.released_at IS NULL THEN l.id END) AS active_lease_count,
    COUNT(DISTINCT CASE WHEN l.released_at IS NULL AND l.heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') THEN l.id END) AS stale_lease_count,
    MAX(CASE WHEN n.note_type = 'checkpoint' AND n.deleted_at IS NULL THEN n.updated_at END) AS last_checkpoint_at
FROM experiments e
LEFT JOIN experiment_runs er ON er.experiment_id = e.id
LEFT JOIN runs r ON r.id = er.run_id
LEFT JOIN jobs j ON j.experiment_id = e.id OR j.run_id = r.id
LEFT JOIN validations v ON v.entity_type = 'experiment' AND v.entity_id = e.id
LEFT JOIN leases l ON l.entity_type = 'experiment' AND l.entity_id = e.id
LEFT JOIN notes n ON n.entity_type = 'experiment' AND n.entity_id = e.id
GROUP BY e.id;

CREATE VIEW IF NOT EXISTS v_dashboard_runs_v1 AS
SELECT * FROM v_runs_progress_v1;

CREATE VIEW IF NOT EXISTS v_dashboard_jobs_v1 AS
SELECT * FROM v_jobs_with_recovery_v1;

CREATE VIEW IF NOT EXISTS v_dashboard_validations_v1 AS
SELECT
    entity_id AS experiment_id,
    validation_id,
    check_name,
    status,
    expected_value,
    measured_value,
    updated_at
FROM v_validations_v1
WHERE entity_type = 'experiment';

CREATE VIEW IF NOT EXISTS v_dashboard_notes_v1 AS
SELECT
    n.entity_id AS experiment_id,
    n.id AS note_id,
    n.note_type,
    n.status,
    n.title,
    SUBSTR(n.body, 1, 240) AS body_preview,
    n.updated_at
FROM notes n
WHERE n.entity_type = 'experiment' AND n.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_dashboard_artifacts_v1 AS
SELECT
    experiment_id,
    artifact_id,
    type AS artifact_type,
    uri,
    NULL AS external_system,
    NULL AS external_id,
    updated_at
FROM v_artifacts_v1
WHERE experiment_id IS NOT NULL;

CREATE VIEW IF NOT EXISTS v_dashboard_leases_v1 AS
SELECT
    l.id AS lease_id,
    l.entity_type,
    l.entity_id,
    l.entity_id AS experiment_id,
    l.owner_agent,
    l.session_id,
    l.claimed_at,
    l.heartbeat_at,
    l.expires_at,
    l.released_at,
    l.release_reason,
    l.attrs_json
FROM leases l
JOIN experiments e ON e.id = l.entity_id
WHERE l.entity_type = 'experiment'
UNION ALL
SELECT
    l.id AS lease_id,
    l.entity_type,
    l.entity_id,
    er.experiment_id,
    l.owner_agent,
    l.session_id,
    l.claimed_at,
    l.heartbeat_at,
    l.expires_at,
    l.released_at,
    l.release_reason,
    l.attrs_json
FROM leases l
JOIN experiment_runs er ON er.run_id = l.entity_id
WHERE l.entity_type = 'run'
UNION ALL
SELECT
    l.id AS lease_id,
    l.entity_type,
    l.entity_id,
    COALESCE(j.experiment_id, er.experiment_id) AS experiment_id,
    l.owner_agent,
    l.session_id,
    l.claimed_at,
    l.heartbeat_at,
    l.expires_at,
    l.released_at,
    l.release_reason,
    l.attrs_json
FROM leases l
JOIN jobs j ON j.id = l.entity_id
LEFT JOIN experiment_runs er ON er.run_id = j.run_id
WHERE l.entity_type = 'job';

CREATE VIEW IF NOT EXISTS v_dashboard_external_links_v1 AS
SELECT
    COALESCE(j.experiment_id, er.experiment_id) AS experiment_id,
    'job' AS entity_type,
    j.id AS entity_id,
    j.external_system,
    j.external_id AS url
FROM jobs j
LEFT JOIN experiment_runs er ON er.run_id = j.run_id
WHERE j.deleted_at IS NULL AND j.external_id LIKE 'http%'
UNION ALL
SELECT
    a.experiment_id,
    'artifact' AS entity_type,
    a.id AS entity_id,
    NULL AS external_system,
    a.uri AS url
FROM artifacts a
WHERE a.deleted_at IS NULL AND a.uri LIKE 'http%';
