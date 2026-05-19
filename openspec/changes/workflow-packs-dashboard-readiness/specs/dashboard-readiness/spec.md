## ADDED Requirements

### Requirement: Classify artifact URI locality
The system SHALL expose artifact locality for dashboard and shared-output use.

#### Scenario: Classify local filesystem artifacts
- **WHEN** an artifact URI is an absolute path, relative path, or `file://` URI
- **THEN** the system classifies it as `local-fs`

#### Scenario: Classify remote artifacts
- **WHEN** an artifact URI starts with `gs://`, `s3://`, `wandb:`, `http://`,
  or `https://`
- **THEN** the system classifies it as `gcs`, `s3`, `wandb`, or `http`
  respectively

#### Scenario: Classify unknown artifacts
- **WHEN** an artifact URI has an unsupported scheme
- **THEN** the system classifies it as `other`

### Requirement: Provide redacted artifact view
The system SHALL provide a stable redacted artifact view for dashboards.

#### Scenario: Redacted artifact columns
- **WHEN** a ledger is migrated to this phase
- **THEN** `v_artifacts_redacted_v1` exposes exactly `artifact_id`,
  `experiment_id`, `run_id`, `job_id`, `type`, `uri_locality`, `display_uri`,
  `content_hash`, `created_at`, `updated_at`, and `attrs_json`, and does not
  expose raw `uri`

#### Scenario: Redact local filesystem path
- **WHEN** an artifact is local filesystem provenance
- **THEN** `v_artifacts_redacted_v1.display_uri` is
  `local:<artifact_id>/<basename>`

#### Scenario: Effective experiment association
- **WHEN** an artifact is linked through direct experiment ownership, run
  membership, job experiment ownership, or job run membership
- **THEN** `v_artifacts_redacted_v1.experiment_id` exposes the effective
  experiment identifier when it can be inferred

#### Scenario: Preserve remote display URI
- **WHEN** an artifact is remote or non-local
- **THEN** `display_uri` preserves the original URI unless the locality-specific
  rule says otherwise

#### Scenario: Keep raw artifact view available
- **WHEN** agents need local provenance
- **THEN** `v_artifacts_v1` remains available with the raw URI

### Requirement: Document dashboard readiness contract
The system SHALL document the minimum future-dashboard read contract.

#### Scenario: Contract defines target screens
- **WHEN** an agent reads the dashboard readiness contract
- **THEN** it defines exactly the initial experiment portfolio and
  single-experiment drilldown screens

#### Scenario: Contract maps UI entities to stable views
- **WHEN** an agent reads the contract
- **THEN** it maps Experiment, Run, Job, Artifact, Metric, Note, ReconcileEvent,
  and SyncEvent entities to stable views or explicit follow-up requirements

#### Scenario: Notes and sync-event views exist
- **WHEN** a ledger is migrated to this phase
- **THEN** it contains `v_notes_v1` and `v_sync_events_v1` stable views for
  dashboard read-only use

#### Scenario: Contract includes sample queries
- **WHEN** dashboard sample queries are committed
- **THEN** tests execute each query against a fixture ledger and assert the
  documented columns are present and each query contains an explicit `LIMIT`

#### Scenario: Contract states non-goals
- **WHEN** an agent reads the contract
- **THEN** it explicitly excludes dashboard UI implementation, write-side
  dashboard operations, realtime polling, auth, and broad analytics

#### Scenario: Contract pins acceptance criteria
- **WHEN** a later dashboard phase begins
- **THEN** the contract provides acceptance criteria including read-only stable
  views, redacted artifact display, queries with explicit limits, and no raw
  local paths in shared payloads
