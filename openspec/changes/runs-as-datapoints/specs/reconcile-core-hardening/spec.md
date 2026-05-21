## MODIFIED Requirements

### Requirement: Support file-based reconcile
The system SHALL ingest run datapoint manifests and job-run fan-out edges through reconcile.

#### Scenario: Reconcile run idempotency key
- **WHEN** a reconcile manifest run row includes `experiment_id` and `idempotency_key`
- **THEN** reconcile resolves active existing rows by `(experiment_id, idempotency_key)` before inserting

#### Scenario: Reject invalid reconcile run idempotency key
- **WHEN** a reconcile manifest run row includes an invalid idempotency key
- **THEN** reconcile rejects the manifest before committing writes

#### Scenario: Reconcile run kind
- **WHEN** a reconcile manifest run row includes `kind`
- **THEN** reconcile validates and stores the run kind

#### Scenario: Reconcile job-run edge
- **WHEN** a reconcile manifest contains a top-level `job_runs` row
- **THEN** reconcile validates the job, run, role, and status, then inserts or updates the edge

#### Scenario: Reject job-run role mutation
- **WHEN** a reconcile manifest attempts to change the role of an existing active job-run edge
- **THEN** reconcile rejects the manifest before committing writes

#### Scenario: Reconcile job-run archive
- **WHEN** a reconcile manifest `job_runs` row has `_op=archive`
- **THEN** reconcile soft-archives the matching edge

#### Scenario: Same-manifest job-run references
- **WHEN** a reconcile manifest creates jobs, runs, and job-run edges in one file
- **THEN** reconcile resolves job-run references against the manifest snapshot and applies all rows atomically

#### Scenario: Reject missing job-run references
- **WHEN** a job-run row references a job or run absent from the active ledger and absent from the same manifest
- **THEN** reconcile rejects the manifest before committing writes

#### Scenario: Count job-run operations
- **WHEN** reconcile returns counts for a manifest with job-run rows
- **THEN** the count shape includes job-run inserts, updates, archives, and noops
