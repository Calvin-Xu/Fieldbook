## ADDED Requirements

### Requirement: Initialize a local ledger
The system SHALL initialize a repo-local Fieldbook ledger at
`.experiments/ledger.sqlite` by default.

#### Scenario: Fresh initialization
- **WHEN** a user runs `fieldbook init` in a repository without a ledger
- **THEN** the system creates `.experiments/ledger.sqlite`, creates the schema,
  records the schema version, enables SQLite WAL mode, and enforces SQLite
  foreign keys on every connection

#### Scenario: Initialize from subdirectory
- **WHEN** a user runs `fieldbook init` from a subdirectory inside a Git
  repository
- **THEN** the system creates `.experiments/ledger.sqlite` at the repository
  root unless `--ledger` or `FIELDBOOK_LEDGER` overrides the path

#### Scenario: Initialize outside Git repository
- **WHEN** a user runs `fieldbook init` outside a Git repository
- **THEN** the system creates `.experiments/ledger.sqlite` under the current
  working directory unless `--ledger` or `FIELDBOOK_LEDGER` overrides the path

#### Scenario: Repeated initialization
- **WHEN** a user runs `fieldbook init` in a repository that already has a
  ledger
- **THEN** the system reports the existing ledger path and does not destroy
  existing data

#### Scenario: Discover ledger from subdirectory
- **WHEN** a user runs a Fieldbook command from a repository subdirectory
- **THEN** the system walks upward from the current directory until it finds
  `.experiments/ledger.sqlite`

#### Scenario: Override ledger path
- **WHEN** a user supplies `--ledger` or `FIELDBOOK_LEDGER`
- **THEN** the system uses that ledger path instead of walking upward from the
  current directory

### Requirement: Manage schema versions
The system SHALL track schema version and refuse unsafe access to incompatible
ledgers.

#### Scenario: Current schema
- **WHEN** the CLI opens a ledger with the current supported schema version
- **THEN** the system proceeds normally

#### Scenario: Old schema
- **WHEN** the CLI opens a ledger with an older supported schema version
- **THEN** the system applies pending SQL migrations in order inside a
  transaction before executing the requested command

#### Scenario: Newer schema
- **WHEN** the CLI opens a ledger with a schema version newer than the CLI
  supports
- **THEN** the system permits read-only show/status commands when possible,
  refuses mutating commands, and reports the version mismatch

### Requirement: Generate stable sortable identifiers
The system SHALL generate type-prefixed ULID-compatible identifiers for core
entities.

#### Scenario: Create entity identifier
- **WHEN** the system creates an experiment, run, job, artifact, metric, note,
  reconcile event, or sync event
- **THEN** the identifier includes a type prefix and a sortable
  ULID-compatible suffix

### Requirement: Track experiments
The system SHALL record experiments with stable identifiers, names, status,
timestamps, descriptions, tags, and namespaced custom attributes.

#### Scenario: Create experiment
- **WHEN** a user creates an experiment with a name and description
- **THEN** the system records the experiment and returns a stable experiment
  identifier

#### Scenario: List experiments
- **WHEN** a user lists experiments
- **THEN** the system displays each experiment's identifier, name, status,
  updated time, and tags in a compact table

#### Scenario: Filter experiments by tag
- **WHEN** a user lists experiments with a tag filter
- **THEN** the system returns only non-deleted experiments that have that tag

#### Scenario: Store experiment tags
- **WHEN** a user creates or updates experiment tags
- **THEN** the system stores tags in a normalized tag table rather than a
  comma-delimited string

### Requirement: Track runs
The system SHALL record runs as scientific datapoints or model/config outcomes
that may belong to one or more experiments.

#### Scenario: Create run under experiment
- **WHEN** a user creates a run for an experiment
- **THEN** the system records the run, links it to the experiment, and stores
  any supplied namespaced custom attributes

#### Scenario: Link run to additional experiment
- **WHEN** a run is relevant to another experiment
- **THEN** the system can link the existing run to the additional experiment
  without duplicating the run record

#### Scenario: External run identifier collision
- **WHEN** a user records a run with the same external system and external
  identifier as an existing non-deleted run
- **THEN** the system treats it as the same run only when the user explicitly
  updates that run, otherwise it reports an ambiguity error

#### Scenario: Export run under linked experiment
- **WHEN** a run is linked to multiple experiments and exported for one
  experiment
- **THEN** the run appears in that export with the requesting experiment as the
  exported `experiment_id`

### Requirement: Track jobs
The system SHALL record jobs as execution attempts with status, command,
launcher, timestamps, external identifiers, and optional links to experiments
and runs.

#### Scenario: Record experiment-level job
- **WHEN** a user records a job before knowing which run it will produce
- **THEN** the system records the job under the experiment without requiring a
  run link

#### Scenario: Record run-level job
- **WHEN** a user records a job for an existing run
- **THEN** the system links the job to that run and its experiment

#### Scenario: Update job status
- **WHEN** a user updates a job to `running`, `succeeded`, `failed`, `killed`,
  or `unknown`
- **THEN** the system records the status, update timestamp, and optional
  failure reason

#### Scenario: Correct job status
- **WHEN** a user updates a job from any valid status to any other valid status
- **THEN** the system accepts the correction and records the new status without
  enforcing a transition graph

#### Scenario: Capture code revision
- **WHEN** a user records a job in a Git repository
- **THEN** the system captures the current commit, dirty-worktree flag, and
  optional diff artifact when available

#### Scenario: External identifier collision
- **WHEN** a user records a job with the same external system and external
  identifier as an existing non-deleted job
- **THEN** the system treats it as the same job only when the user explicitly
  updates that job, otherwise it reports an ambiguity error

### Requirement: Validate core enums
The system SHALL validate status and artifact enums at the CLI boundary.

#### Scenario: Invalid job status
- **WHEN** a user supplies a job status outside `planned`, `queued`,
  `running`, `succeeded`, `failed`, `killed`, `skipped`, or `unknown`
- **THEN** the system rejects the command with a validation error

#### Scenario: Invalid artifact type
- **WHEN** a user supplies an artifact type outside `checkpoint`,
  `eval-result`, `metric-table`, `plot`, `report`, `log`, `wandb-run`,
  `manifest`, or `other`
- **THEN** the system rejects the command with a validation error

#### Scenario: Invalid note status
- **WHEN** a user supplies a note status outside `open`, `resolved`, or
  `superseded`
- **THEN** the system rejects the command with a validation error

### Requirement: Track artifacts
The system SHALL record durable artifact pointers for checkpoints, result
files, W&B runs, logs, plots, reports, CSVs, and other provenance outputs.

#### Scenario: Add artifact to job
- **WHEN** a user records an artifact produced by a job
- **THEN** the system stores the artifact type, URI or repo-relative path,
  optional content hash, producing job, and namespaced custom attributes

#### Scenario: Add artifact to run
- **WHEN** a user records an artifact that backs a run
- **THEN** the system links the artifact to the run and preserves the artifact
  provenance

#### Scenario: External artifact pointer collision
- **WHEN** a user records an artifact with the same URI or repo-relative path as
  an existing non-deleted artifact
- **THEN** the system treats it as the same artifact only when the user
  explicitly updates that artifact, otherwise it reports an ambiguity error

#### Scenario: Store artifact content hash
- **WHEN** a user supplies an artifact content hash
- **THEN** the system accepts `sha256:<hex>` hashes and rejects hashes without
  an explicit supported algorithm prefix

### Requirement: Track summary metrics
The system SHALL store summary metric observations linked to runs and their
source jobs or artifacts.

#### Scenario: Add metric
- **WHEN** a user records a metric value for a run
- **THEN** the system stores the metric name, value, optional step, split,
  source job, source artifact, and timestamp

#### Scenario: Preserve incomplete metric coverage
- **WHEN** one run has metrics that another run is missing
- **THEN** the system preserves both records without forcing a fixed table
  schema

#### Scenario: Idempotent metric update
- **WHEN** a metric is recorded with the same run, metric name, step, split,
  source job, and source artifact as an existing metric
- **THEN** the system updates that metric value and timestamp instead of
  creating a duplicate observation, treating missing optional key fields as
  equal to other missing values for idempotency

#### Scenario: Distinct metric provenance
- **WHEN** a metric is recorded with the same run, metric name, step, and split
  but a different source job or source artifact
- **THEN** the system records a distinct metric observation

### Requirement: Track notes
The system SHALL record structured notes for experiments, runs, jobs, and
artifacts.

#### Scenario: Add note
- **WHEN** a user adds a note to an experiment, run, job, or artifact
- **THEN** the system records the note type, body, author, timestamp, optional
  resolution state, and related entity

#### Scenario: Invalid note type
- **WHEN** a user supplies a note type outside `research`, `debug`,
  `next-action`, `handoff`, or `decision`
- **THEN** the system rejects the command with a validation error

#### Scenario: Resolve next action
- **WHEN** a user resolves a next-action note
- **THEN** the system marks the note resolved without deleting its text

### Requirement: Support namespaced custom attributes
The system SHALL allow experiments, runs, jobs, and artifacts to store
project-specific metadata in a JSON attributes column.

#### Scenario: Store Marin metadata
- **WHEN** a user records `marin.iris_job_path` or
  `marin.gcs_checkpoint_root` on a job or run
- **THEN** the system stores the value without requiring a Marin-specific core
  column

#### Scenario: Query custom attributes
- **WHEN** a user filters by a namespaced custom attribute
- **THEN** the system returns matching records using SQLite JSON extraction

#### Scenario: Reject invalid attribute namespace
- **WHEN** a user writes an attribute key that is not lowercase dotted form or
  that uses the reserved `fieldbook.` namespace
- **THEN** the system rejects the write with a validation error

### Requirement: Preserve deleted records
The system SHALL soft-delete experiments, runs, jobs, artifacts, metrics, and
notes by marking `deleted_at` rather than hard-deleting records.

#### Scenario: Delete experiment
- **WHEN** a user deletes an experiment
- **THEN** the system marks the experiment deleted and preserves linked runs,
  jobs, artifacts, metrics, and notes for auditability

#### Scenario: Delete job
- **WHEN** a user deletes a job
- **THEN** the system marks the job deleted and preserves artifacts, metrics,
  and notes linked to that job for auditability

#### Scenario: Write to deleted experiment
- **WHEN** a user attempts to create a run or job under a deleted experiment
- **THEN** the system rejects the write unless the experiment is restored first

#### Scenario: List deleted records
- **WHEN** a user lists experiments, runs, jobs, artifacts, metrics, or notes
- **THEN** the system excludes deleted records by default and includes them only
  when explicitly requested

### Requirement: Use UTC timestamps
The system SHALL store timestamps as UTC ISO-8601 strings with a `Z` suffix.

#### Scenario: Store timestamp
- **WHEN** the system records creation, update, deletion, status, metric, note,
  reconcile, or sync time
- **THEN** the stored value is a UTC ISO-8601 timestamp ending in `Z`

### Requirement: Record external sync attempts
The system SHALL record attempts to mirror or synchronize Fieldbook state to
external systems such as W&B.

#### Scenario: Record sync event
- **WHEN** the system attempts to sync metrics or artifacts to an external
  system
- **THEN** it records the target system, target identifier, status, timestamp,
  related run or job, and error message when the sync fails

### Requirement: Use stable exit codes
The system SHALL use stable process exit codes so coding agents can distinguish
expected error classes.

#### Scenario: Successful command
- **WHEN** a command succeeds
- **THEN** the process exits with code `0`

#### Scenario: Validation error
- **WHEN** a command rejects invalid user input
- **THEN** the process exits with code `2`

#### Scenario: Not found error
- **WHEN** a command references a missing entity
- **THEN** the process exits with code `3`

#### Scenario: Ambiguity error
- **WHEN** a command cannot safely choose between multiple matching entities
- **THEN** the process exits with code `4`

#### Scenario: Ledger busy error
- **WHEN** SQLite reports the ledger is busy or locked
- **THEN** the process exits with code `5`

#### Scenario: Internal error
- **WHEN** an unexpected internal failure occurs
- **THEN** the process exits with code `1`
