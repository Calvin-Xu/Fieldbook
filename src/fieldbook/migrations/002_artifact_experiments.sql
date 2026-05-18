ALTER TABLE artifacts ADD COLUMN experiment_id TEXT REFERENCES experiments(id);

CREATE INDEX IF NOT EXISTS idx_artifacts_experiment
ON artifacts(experiment_id, type, updated_at)
WHERE deleted_at IS NULL;
