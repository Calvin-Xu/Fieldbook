SELECT artifact_id, type, uri_locality, display_uri, updated_at
FROM v_artifacts_redacted_v1
WHERE experiment_id = '<EXPERIMENT_ID>'
ORDER BY updated_at DESC
LIMIT 100;
