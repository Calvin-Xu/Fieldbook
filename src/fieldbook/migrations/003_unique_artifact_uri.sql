CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_uri_unique
ON artifacts(uri)
WHERE deleted_at IS NULL;
