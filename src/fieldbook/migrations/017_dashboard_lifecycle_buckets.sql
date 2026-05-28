DROP VIEW IF EXISTS v_dashboard_experiments_v1;

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
        WHEN active_job_count > 0
          OR active_lease_count > 0
          OR recovery_in_progress_failed_job_count > 0 THEN 'in_progress'
        WHEN has_pending_review = 1 THEN 'review'
        ELSE 'open'
    END AS lifecycle_state
FROM handoff_state;
