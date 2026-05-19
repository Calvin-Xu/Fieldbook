ALTER TABLE sync_events ADD COLUMN origin TEXT NOT NULL DEFAULT 'manifest'
CHECK (origin IN ('manifest', 'writeback'));

ALTER TABLE sync_events ADD COLUMN source_entity_type TEXT
CHECK (source_entity_type IS NULL OR source_entity_type = 'metric');

ALTER TABLE sync_events ADD COLUMN source_entity_id TEXT;

ALTER TABLE sync_events ADD COLUMN target_field TEXT;

ALTER TABLE sync_events ADD COLUMN payload_summary_json TEXT;

DROP INDEX IF EXISTS idx_sync_events_idempotency;

CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_events_idempotency
ON sync_events(target_system, COALESCE(target_identifier, ''), idempotency_key)
WHERE idempotency_key IS NOT NULL AND origin = 'manifest';

CREATE INDEX IF NOT EXISTS idx_sync_events_writeback_latest
ON sync_events(target_system, target_identifier, idempotency_key, created_at, id);

DROP VIEW IF EXISTS v_wandb_sync_coverage_v1;

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

CREATE VIEW IF NOT EXISTS v_wandb_writeback_coverage_v1 AS
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
