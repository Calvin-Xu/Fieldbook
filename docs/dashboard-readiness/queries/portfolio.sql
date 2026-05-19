SELECT experiment_id, name, status, run_count, failed_job_count, open_note_count, updated_at
FROM v_experiment_summary_v1
ORDER BY updated_at DESC
LIMIT 100;
