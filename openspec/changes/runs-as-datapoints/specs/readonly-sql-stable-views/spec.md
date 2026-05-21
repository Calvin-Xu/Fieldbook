## MODIFIED Requirements

### Requirement: Provide versioned stable views
The system SHALL expose run datapoint and job-run progress through stable SQL views.

#### Scenario: Query run view with datapoint fields
- **WHEN** an agent queries `v_runs_v1`
- **THEN** each row includes `experiment_id`, `kind`, and `idempotency_key`

#### Scenario: Query job-run view
- **WHEN** an agent queries `v_job_runs_v1`
- **THEN** it returns active job-run edges with job ID, run ID, experiment IDs, role, status, timestamps, failure reason, and attrs

#### Scenario: Query run progress view
- **WHEN** an agent queries `v_runs_progress_v1`
- **THEN** it returns one active row per experiment-run link with derived phase, kind, checkpoint coverage, eval-result coverage, metric count, train/eval/other edge counts, and job-run status counts

#### Scenario: Legacy jobs run column remains visible
- **WHEN** an agent queries `v_jobs_v1`
- **THEN** the legacy `run_id` column remains available for compatibility during this phase
