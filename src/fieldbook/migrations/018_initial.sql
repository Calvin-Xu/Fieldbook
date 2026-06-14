-- Coalesced baseline schema for Fieldbook schema version 18.
-- Existing ledgers at PRAGMA user_version = 18 are left unchanged.
-- Fresh ledgers apply this migration directly and are then stamped as v18 by the migration runner.

CREATE TABLE artifacts (
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
, experiment_id TEXT REFERENCES experiments(id));
CREATE TABLE experiment_runs (
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    run_id TEXT NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, run_id)
);
CREATE TABLE experiment_tags (
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (experiment_id, tag)
);
CREATE TABLE experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
, idempotency_key TEXT);
CREATE TABLE job_runs (
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
CREATE TABLE jobs (
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
, retry_of TEXT REFERENCES jobs(id));
CREATE TABLE leases (
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
CREATE TABLE metrics (
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
CREATE TABLE notes (
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
, title TEXT
CHECK (title IS NULL OR (length(trim(title)) BETWEEN 1 AND 120)), body_format TEXT NOT NULL DEFAULT 'markdown'
CHECK (body_format IN ('markdown', 'plain')));
CREATE TABLE reconcile_events (
    id TEXT PRIMARY KEY,
    experiment_id TEXT REFERENCES experiments(id),
    source TEXT NOT NULL,
    inserts_json TEXT NOT NULL DEFAULT '{}',
    updates_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}'
, counts_json TEXT NOT NULL
DEFAULT '{"insert":{},"update":{},"archive":{},"sync_event":0,"noop":{},"total":0}', session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL);
CREATE TABLE reconcile_operations (
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
CREATE TABLE refresh_events (
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
CREATE TABLE runs (
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
, parent_run_id TEXT REFERENCES runs(id), experiment_id TEXT REFERENCES experiments(id), idempotency_key TEXT, kind TEXT NOT NULL DEFAULT 'datapoint');
CREATE TABLE schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE sessions (
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
CREATE TABLE sync_events (
    id TEXT PRIMARY KEY,
    target_system TEXT NOT NULL,
    target_identifier TEXT,
    status TEXT NOT NULL,
    run_id TEXT REFERENCES runs(id),
    job_id TEXT REFERENCES jobs(id),
    error_message TEXT,
    created_at TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}'
, reconcile_event_id TEXT REFERENCES reconcile_events(id), idempotency_key TEXT, origin TEXT NOT NULL DEFAULT 'manifest'
CHECK (origin IN ('manifest', 'writeback')), source_entity_type TEXT
CHECK (source_entity_type IS NULL OR source_entity_type = 'metric'), source_entity_id TEXT, target_field TEXT, payload_summary_json TEXT);
CREATE TABLE validations (
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
CREATE UNIQUE INDEX idx_metrics_idempotency
ON metrics (
    run_id,
    metric_name,
    COALESCE(step, ''),
    COALESCE(split, ''),
    COALESCE(source_job_id, ''),
    COALESCE(source_artifact_id, '')
)
WHERE deleted_at IS NULL;
CREATE INDEX idx_experiments_status_updated
ON experiments(status, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_experiment_tags_tag
ON experiment_tags(tag);
CREATE INDEX idx_experiment_runs_run
ON experiment_runs(run_id);
CREATE INDEX idx_jobs_experiment_status
ON jobs(experiment_id, status, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_jobs_run_status
ON jobs(run_id, status, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_artifacts_run
ON artifacts(run_id, type, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_artifacts_job
ON artifacts(job_id, type, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_metrics_run_name
ON metrics(run_id, metric_name)
WHERE deleted_at IS NULL;
CREATE INDEX idx_notes_entity
ON notes(entity_type, entity_id, status, updated_at)
WHERE deleted_at IS NULL;
CREATE INDEX idx_artifacts_experiment
ON artifacts(experiment_id, type, updated_at)
WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX idx_artifacts_uri_unique
ON artifacts(uri)
WHERE deleted_at IS NULL;
CREATE INDEX idx_runs_parent
ON runs(parent_run_id)
WHERE parent_run_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX idx_reconcile_ops_event
ON reconcile_operations(reconcile_event_id, op_index);
CREATE INDEX idx_reconcile_ops_entity
ON reconcile_operations(entity, entity_id);
CREATE UNIQUE INDEX idx_runs_external_unique
ON runs(external_system, external_id)
WHERE deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL;
CREATE UNIQUE INDEX idx_jobs_external_unique
ON jobs(external_system, external_id)
WHERE deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL;
CREATE VIEW v_artifacts_v1 AS
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
CREATE VIEW v_metrics_long_v1 AS
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
CREATE VIEW v_experiment_summary_v1 AS
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
CREATE VIEW v_artifact_latest_per_type_v1 AS
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
CREATE VIEW v_metric_coverage_v1 AS
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
CREATE UNIQUE INDEX idx_sync_events_idempotency
ON sync_events(target_system, COALESCE(target_identifier, ''), idempotency_key)
WHERE idempotency_key IS NOT NULL AND origin = 'manifest';
CREATE INDEX idx_sync_events_writeback_latest
ON sync_events(target_system, target_identifier, idempotency_key, created_at, id);
CREATE VIEW v_wandb_sync_coverage_v1 AS
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
        AND s.origin = 'manifest'
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
CREATE VIEW v_wandb_writeback_coverage_v1 AS
WITH ranked AS (
    SELECT
        s.run_id AS source_run_id,
        s.source_entity_id,
        s.target_identifier,
        s.target_field,
        s.status AS latest_status,
        s.error_message AS latest_error_message,
        s.created_at AS latest_event_at,
        COUNT(*) OVER (
            PARTITION BY s.source_entity_id, s.target_identifier, s.target_field
        ) AS attempt_count,
        ROW_NUMBER() OVER (
            PARTITION BY s.source_entity_id, s.target_identifier, s.target_field
            ORDER BY s.created_at DESC, s.id DESC
        ) AS rn
    FROM sync_events s
    WHERE s.target_system = 'wandb'
      AND s.origin = 'writeback'
      AND s.source_entity_type = 'metric'
      AND s.source_entity_id IS NOT NULL
      AND s.target_field IS NOT NULL
)
SELECT
    source_run_id,
    source_entity_id,
    target_identifier,
    target_field,
    latest_status,
    latest_error_message,
    latest_event_at,
    attempt_count
FROM ranked
WHERE rn = 1;
CREATE VIEW v_notes_v1 AS
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
CREATE VIEW v_sync_events_v1 AS
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
CREATE VIEW v_artifacts_redacted_v1 AS
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
CREATE UNIQUE INDEX idx_experiments_idempotency
ON experiments(idempotency_key)
WHERE deleted_at IS NULL AND idempotency_key IS NOT NULL;
CREATE INDEX idx_sessions_agent_cwd_open
ON sessions(agent, cwd, ended_at);
CREATE INDEX idx_sessions_experiment_time
ON sessions(experiment_id, started_at, id);
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
CREATE VIEW v_sessions_v1 AS
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
CREATE VIEW v_experiment_session_history_v1 AS
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
CREATE INDEX idx_jobs_retry_of
ON jobs(retry_of)
WHERE retry_of IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX idx_validations_key
ON validations(entity_type, entity_id, check_name)
WHERE deleted_at IS NULL;
CREATE INDEX idx_validations_status
ON validations(status, updated_at)
WHERE deleted_at IS NULL;
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
CREATE VIEW v_validations_v1 AS
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
CREATE VIEW v_jobs_with_recovery_v1 AS
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
CREATE VIEW v_experiment_blockers_v1 AS
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
CREATE INDEX idx_refresh_events_source_finished
ON refresh_events(source, finished_at);
CREATE INDEX idx_refresh_events_status_finished
ON refresh_events(status, finished_at);
CREATE VIEW v_refresh_log_v1 AS
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
CREATE UNIQUE INDEX idx_runs_experiment_idempotency
ON runs(experiment_id, idempotency_key)
WHERE experiment_id IS NOT NULL AND idempotency_key IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX idx_runs_experiment_id
ON runs(experiment_id)
WHERE experiment_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX idx_job_runs_run_id
ON job_runs(run_id)
WHERE deleted_at IS NULL;
CREATE INDEX idx_job_runs_job_id
ON job_runs(job_id)
WHERE deleted_at IS NULL;
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
CREATE UNIQUE INDEX idx_leases_active_entity
ON leases(entity_type, entity_id)
WHERE released_at IS NULL;
CREATE INDEX idx_leases_owner_active
ON leases(owner_agent, heartbeat_at)
WHERE released_at IS NULL;
CREATE INDEX idx_leases_session_active
ON leases(session_id)
WHERE session_id IS NOT NULL AND released_at IS NULL;
CREATE VIEW v_leases_active_v1 AS
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
CREATE VIEW v_leases_stale_v1 AS
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
CREATE VIEW v_lease_history_v1 AS
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
CREATE VIEW v_experiment_ownership_v1 AS
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
CREATE VIEW v_run_ownership_v1 AS
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
CREATE VIEW v_job_ownership_v1 AS
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
CREATE VIEW v_dashboard_runs_v1 AS
SELECT * FROM v_runs_progress_v1;
CREATE VIEW v_dashboard_jobs_v1 AS
SELECT * FROM v_jobs_with_recovery_v1;
CREATE VIEW v_dashboard_validations_v1 AS
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
CREATE VIEW v_dashboard_notes_v1 AS
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
CREATE VIEW v_dashboard_artifacts_v1 AS
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
CREATE VIEW v_dashboard_leases_v1 AS
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
CREATE VIEW v_dashboard_external_links_v1 AS
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
CREATE VIEW v_dashboard_experiments_v1 AS
WITH
run_counts AS (
    SELECT
        er.experiment_id,
        COUNT(DISTINCT r.id) AS run_count
    FROM experiment_runs er
    JOIN runs r ON r.id = er.run_id
    WHERE r.deleted_at IS NULL
    GROUP BY er.experiment_id
),
experiment_jobs AS (
    SELECT
        j.job_id,
        j.status,
        j.updated_at,
        j.finished_at,
        j.is_blocking_failed,
        j.is_recovery_in_progress,
        j.is_recovered_failed,
        j.experiment_id
    FROM v_jobs_with_recovery_v1 j
    WHERE j.deleted_at IS NULL AND j.experiment_id IS NOT NULL
    UNION
    SELECT
        j.job_id,
        j.status,
        j.updated_at,
        j.finished_at,
        j.is_blocking_failed,
        j.is_recovery_in_progress,
        j.is_recovered_failed,
        er.experiment_id
    FROM v_jobs_with_recovery_v1 j
    JOIN experiment_runs er ON er.run_id = j.run_id
    WHERE j.deleted_at IS NULL
),
job_counts AS (
    SELECT
        experiment_id,
        COUNT(DISTINCT job_id) AS job_count,
        COUNT(DISTINCT CASE WHEN status = 'failed' THEN job_id END) AS failed_job_count,
        COUNT(DISTINCT CASE WHEN is_blocking_failed = 1 THEN job_id END) AS blocking_failed_job_count,
        COUNT(DISTINCT CASE WHEN is_recovery_in_progress = 1 THEN job_id END) AS recovery_in_progress_failed_job_count,
        COUNT(DISTINCT CASE WHEN is_recovered_failed = 1 THEN job_id END) AS recovered_failed_job_count,
        COUNT(DISTINCT CASE WHEN status IN ('submitting', 'unknown_submit', 'queued', 'running') THEN job_id END) AS active_job_count,
        COUNT(DISTINCT CASE WHEN status IN ('submitting', 'unknown_submit') THEN job_id END) AS submission_uncertainty_count,
        COUNT(DISTINCT CASE
            WHEN status IN ('submitting', 'unknown_submit')
             AND updated_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour')
            THEN job_id END) AS stale_submission_count
    FROM experiment_jobs
    GROUP BY experiment_id
),
validation_counts AS (
    SELECT
        entity_id AS experiment_id,
        COUNT(DISTINCT id) AS validation_count,
        COUNT(DISTINCT CASE WHEN status = 'fail' THEN id END) AS failing_validation_count,
        MAX(updated_at) AS last_validation_at
    FROM validations
    WHERE entity_type = 'experiment' AND deleted_at IS NULL
    GROUP BY entity_id
),
artifact_counts AS (
    SELECT
        experiment_id,
        COUNT(DISTINCT id) AS artifact_count,
        MAX(updated_at) AS last_artifact_at
    FROM artifacts
    WHERE deleted_at IS NULL AND experiment_id IS NOT NULL
    GROUP BY experiment_id
),
non_handoff_note_counts AS (
    SELECT
        entity_id AS experiment_id,
        COUNT(DISTINCT id) AS non_handoff_note_count
    FROM notes
    WHERE entity_type = 'experiment'
      AND note_type NOT IN ('checkpoint', 'review')
      AND deleted_at IS NULL
    GROUP BY entity_id
),
lease_counts AS (
    SELECT
        entity_id AS experiment_id,
        COUNT(DISTINCT CASE WHEN released_at IS NULL THEN id END) AS active_lease_count,
        COUNT(DISTINCT CASE WHEN released_at IS NULL AND heartbeat_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') THEN id END) AS stale_lease_count
    FROM leases
    WHERE entity_type = 'experiment'
    GROUP BY entity_id
),
handoff_notes AS (
    SELECT
        entity_id AS experiment_id,
        MAX(created_at) AS last_handoff_at
    FROM notes
    WHERE entity_type = 'experiment' AND note_type = 'checkpoint' AND deleted_at IS NULL
    GROUP BY entity_id
),
review_note_keys AS (
    SELECT
        entity_id AS experiment_id,
        MAX(created_at || ' ' || id) AS last_reviewed_key
    FROM notes
    WHERE entity_type = 'experiment' AND note_type = 'review' AND deleted_at IS NULL
    GROUP BY entity_id
),
review_notes AS (
    SELECT
        n.entity_id AS experiment_id,
        n.created_at AS last_reviewed_at,
        k.last_reviewed_key,
        CAST(json_extract(n.attrs_json, '$."fieldbook.reviewed_activity_count"') AS INTEGER)
            AS reviewed_activity_count
    FROM notes n
    JOIN review_note_keys k
      ON k.experiment_id = n.entity_id
     AND k.last_reviewed_key = n.created_at || ' ' || n.id
    WHERE n.entity_type = 'experiment' AND n.note_type = 'review' AND n.deleted_at IS NULL
),
reviewable_activity_rows AS (
    SELECT
        experiment_id,
        activity_at,
        activity_id
    FROM (
        SELECT
            experiment_id,
            COALESCE(finished_at, updated_at) AS activity_at,
            job_id AS activity_id
        FROM experiment_jobs
        WHERE status IN ('succeeded', 'failed', 'killed', 'skipped')
        UNION ALL
        SELECT
            experiment_id,
            updated_at AS activity_at,
            job_id AS activity_id
        FROM experiment_jobs
        WHERE is_recovered_failed = 1
        UNION ALL
        SELECT
            experiment_id,
            updated_at AS activity_at,
            id AS activity_id
        FROM artifacts
        WHERE deleted_at IS NULL AND experiment_id IS NOT NULL
        UNION ALL
        SELECT
            entity_id AS experiment_id,
            updated_at AS activity_at,
            id AS activity_id
        FROM validations
        WHERE entity_type = 'experiment' AND deleted_at IS NULL
        UNION ALL
        SELECT
            entity_id AS experiment_id,
            updated_at AS activity_at,
            id AS activity_id
        FROM notes
        WHERE entity_type = 'experiment'
          AND note_type IN ('next-action', 'debug', 'research', 'decision')
          AND status != 'superseded'
          AND deleted_at IS NULL
    )
    WHERE activity_at IS NOT NULL AND activity_id IS NOT NULL
),
reviewable_activity AS (
    SELECT
        experiment_id,
        COUNT(*) AS reviewable_activity_count,
        MAX(activity_at) AS last_reviewable_activity_at,
        MAX(activity_at || ' ' || activity_id) AS last_reviewable_activity_key
    FROM reviewable_activity_rows
    GROUP BY experiment_id
),
summary AS (
    SELECT
        e.id AS experiment_id,
        e.name,
        e.status,
        e.created_at,
        e.updated_at,
        e.deleted_at,
        COALESCE(r.run_count, 0) AS run_count,
        COALESCE(j.job_count, 0) AS job_count,
        COALESCE(j.failed_job_count, 0) AS failed_job_count,
        COALESCE(j.blocking_failed_job_count, 0) AS blocking_failed_job_count,
        COALESCE(j.recovery_in_progress_failed_job_count, 0) AS recovery_in_progress_failed_job_count,
        COALESCE(j.recovered_failed_job_count, 0) AS recovered_failed_job_count,
        COALESCE(j.active_job_count, 0) AS active_job_count,
        COALESCE(j.submission_uncertainty_count, 0) AS submission_uncertainty_count,
        COALESCE(j.stale_submission_count, 0) AS stale_submission_count,
        COALESCE(v.validation_count, 0) AS validation_count,
        COALESCE(v.failing_validation_count, 0) AS failing_validation_count,
        COALESCE(l.active_lease_count, 0) AS active_lease_count,
        COALESCE(l.stale_lease_count, 0) AS stale_lease_count,
        COALESCE(a.artifact_count, 0) AS artifact_count,
        COALESCE(n.non_handoff_note_count, 0) AS non_handoff_note_count,
        h.last_handoff_at,
        rv.last_reviewed_at,
        rv.last_reviewed_key,
        rv.reviewed_activity_count,
        COALESCE(ra.reviewable_activity_count, 0) AS reviewable_activity_count,
        ra.last_reviewable_activity_at,
        ra.last_reviewable_activity_key
    FROM experiments e
    LEFT JOIN run_counts r ON r.experiment_id = e.id
    LEFT JOIN job_counts j ON j.experiment_id = e.id
    LEFT JOIN validation_counts v ON v.experiment_id = e.id
    LEFT JOIN lease_counts l ON l.experiment_id = e.id
    LEFT JOIN artifact_counts a ON a.experiment_id = e.id
    LEFT JOIN non_handoff_note_counts n ON n.experiment_id = e.id
    LEFT JOIN handoff_notes h ON h.experiment_id = e.id
    LEFT JOIN review_notes rv ON rv.experiment_id = e.id
    LEFT JOIN reviewable_activity ra ON ra.experiment_id = e.id
),
review_state AS (
    SELECT
        *,
        CASE
            WHEN last_reviewable_activity_key IS NOT NULL
             AND (
                 last_reviewed_key IS NULL
                 OR last_reviewable_activity_key > last_reviewed_key
                 OR reviewable_activity_count > COALESCE(reviewed_activity_count, -1)
             )
            THEN 1
            ELSE 0
        END AS has_pending_review
    FROM summary
),
handoff_state AS (
    SELECT
        *,
        last_handoff_at AS last_checkpoint_at,
        CASE
            WHEN last_handoff_at IS NULL
             AND run_count + job_count + validation_count + artifact_count + non_handoff_note_count = 0 THEN 'idle'
            WHEN last_handoff_at IS NULL THEN 'missing'
            WHEN last_handoff_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours') THEN 'stale'
            ELSE 'current'
        END AS handoff_status
    FROM review_state
)
SELECT
    *,
    CASE
        WHEN deleted_at IS NOT NULL OR status = 'archived' THEN 'archived'
        WHEN blocking_failed_job_count > 0
          OR failing_validation_count > 0
          OR stale_lease_count > 0
          OR stale_submission_count > 0 THEN 'needs_attention'
        WHEN active_job_count > 0 THEN 'running'
        WHEN has_pending_review = 1 THEN 'review'
        ELSE 'open'
    END AS lifecycle_state
FROM handoff_state;

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
