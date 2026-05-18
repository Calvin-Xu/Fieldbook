## ADDED Requirements

### Requirement: Export run tables with provenance
The system SHALL export run-level tables that include metrics and provenance
columns suitable for collaborators and custom dashboards.

#### Scenario: Export wide run table
- **WHEN** a user exports runs in wide format
- **THEN** the system writes one row per run with selected metric columns and
  provenance columns for run identifier, requesting experiment, source jobs,
  artifacts, code revision, and external links when available

#### Scenario: Select metrics for wide export
- **WHEN** a user exports a wide run table
- **THEN** the system selects metric columns from an explicit metric list,
  metric-list file, or all metrics present when the user requests all metrics

#### Scenario: Export long metric table
- **WHEN** a user exports metrics in long format
- **THEN** the system writes one row per metric observation with metric name,
  value, run identifier, source job, source artifact, step, split, and
  timestamp

### Requirement: Record export provenance
The system SHALL record exports as artifacts in the ledger.

#### Scenario: Export creates artifact record
- **WHEN** a user exports a CSV or JSON file
- **THEN** the system records an artifact entry for that export with the output
  path, export command, creation time, and related experiment

### Requirement: Report metric coverage
The system SHALL report metric coverage across runs without requiring every run
to have every metric.

#### Scenario: Coverage table
- **WHEN** a user requests coverage for an experiment
- **THEN** the system reports which requested metrics are complete, missing, or
  partially present across the selected runs

### Requirement: Import metric CSV files
The system SHALL import summary metric CSV files with a documented minimal
schema.

#### Scenario: Import valid metric CSV
- **WHEN** a user imports a CSV with `run_id`, `metric_name`, `value`, and
  optional `step`, `split`, `source_job_id`, and `source_artifact_id` columns
- **THEN** the system validates all referenced entities and records the metric
  observations

#### Scenario: Reject ambiguous metric CSV
- **WHEN** a user imports a CSV that omits required columns or references an
  unknown run
- **THEN** the system rejects the import and leaves the ledger unchanged

### Requirement: Preserve artifact pointers in exports
The system SHALL include durable artifact pointers in exported tables when they
back the exported data.

#### Scenario: Export includes checkpoint and eval result
- **WHEN** a run has checkpoint and eval-result artifacts
- **THEN** the run export includes the artifact URIs or repo-relative paths so
  the exported metric values can be traced back to their sources
