CREATE VIEW IF NOT EXISTS v_notes_v1 AS
SELECT
    n.id AS note_id,
    n.entity_type,
    n.entity_id,
    n.note_type,
    n.status,
    n.title,
    n.body_format,
    n.body,
    n.author,
    n.created_at,
    n.updated_at,
    n.attrs_json
FROM notes n
WHERE n.deleted_at IS NULL;

CREATE VIEW IF NOT EXISTS v_sync_events_v1 AS
SELECT
    s.id AS sync_event_id,
    s.target_system,
    s.target_identifier,
    s.status,
    s.origin,
    s.run_id,
    s.job_id,
    s.source_entity_type,
    s.source_entity_id,
    s.target_field,
    s.error_message,
    s.reconcile_event_id,
    s.idempotency_key,
    s.payload_summary_json,
    s.created_at,
    s.attrs_json
FROM sync_events s;

CREATE VIEW IF NOT EXISTS v_artifacts_redacted_v1 AS
WITH artifact_experiments AS (
    SELECT a.id AS artifact_id, a.experiment_id
    FROM artifacts a
    WHERE a.experiment_id IS NOT NULL
    UNION
    SELECT a.id AS artifact_id, er.experiment_id
    FROM artifacts a
    JOIN experiment_runs er ON er.run_id = a.run_id
    UNION
    SELECT a.id AS artifact_id, j.experiment_id
    FROM artifacts a
    JOIN jobs j ON j.id = a.job_id
    WHERE j.experiment_id IS NOT NULL
    UNION
    SELECT a.id AS artifact_id, er.experiment_id
    FROM artifacts a
    JOIN jobs j ON j.id = a.job_id
    JOIN experiment_runs er ON er.run_id = j.run_id
),
artifact_base AS (
    SELECT
        a.id AS artifact_id,
        MIN(ae.experiment_id) AS experiment_id,
        a.run_id,
        a.job_id,
        a.type,
        a.content_hash,
        a.created_at,
        a.updated_at,
        a.attrs_json,
        a.uri,
        CASE
            WHEN a.uri LIKE 'gs://%' THEN 'gcs'
            WHEN a.uri LIKE 's3://%' THEN 's3'
            WHEN a.uri LIKE 'wandb:%' THEN 'wandb'
            WHEN a.uri LIKE 'http://%' OR a.uri LIKE 'https://%' THEN 'http'
            WHEN a.uri LIKE 'file://%' THEN 'local-fs'
            WHEN a.uri LIKE '%://%' THEN 'other'
            ELSE 'local-fs'
        END AS uri_locality,
        REPLACE(CASE WHEN a.uri LIKE 'file://%' THEN SUBSTR(a.uri, 8) ELSE a.uri END, CHAR(92), '/') AS path_text
    FROM artifacts a
    LEFT JOIN artifact_experiments ae ON ae.artifact_id = a.id
    WHERE a.deleted_at IS NULL
    GROUP BY a.id
),
path_parts(artifact_id, rest, part) AS (
    SELECT artifact_id, path_text AS rest, '' AS part
    FROM artifact_base
    WHERE uri_locality = 'local-fs'
    UNION ALL
    SELECT
        artifact_id,
        CASE WHEN INSTR(rest, '/') = 0 THEN '' ELSE SUBSTR(rest, INSTR(rest, '/') + 1) END AS rest,
        CASE WHEN INSTR(rest, '/') = 0 THEN rest ELSE SUBSTR(rest, 1, INSTR(rest, '/') - 1) END AS part
    FROM path_parts
    WHERE rest <> ''
),
basenames AS (
    SELECT artifact_id, COALESCE(NULLIF(part, ''), 'artifact') AS basename
    FROM path_parts
    WHERE rest = ''
)
SELECT
    ab.artifact_id,
    ab.experiment_id,
    ab.run_id,
    ab.job_id,
    ab.type,
    ab.uri_locality,
    CASE
        WHEN ab.uri_locality = 'local-fs' THEN 'local:' || ab.artifact_id || '/' || COALESCE(b.basename, 'artifact')
        ELSE ab.uri
    END AS display_uri,
    ab.content_hash,
    ab.created_at,
    ab.updated_at,
    ab.attrs_json
FROM artifact_base ab
LEFT JOIN basenames b ON b.artifact_id = ab.artifact_id;
