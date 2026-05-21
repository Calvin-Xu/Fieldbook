## ADDED Requirements

### Requirement: Model runs as experiment datapoints
The system SHALL treat runs as first-class experiment matrix datapoints rather than only completed external runs.

#### Scenario: Create planned run datapoint
- **WHEN** an agent creates a run linked to an experiment
- **THEN** the run can exist before any job, artifact, metric, or checkpoint is observed

#### Scenario: Store run kind
- **WHEN** an agent creates a run with kind `datapoint`, `aggregate`, `analysis`, or `external`
- **THEN** the system stores the kind and exposes it through run show/list and stable run views

#### Scenario: Reject invalid run kind
- **WHEN** an agent creates or reconciles a run with any other kind
- **THEN** the system rejects the write with a validation error

#### Scenario: Idempotent run creation in experiment scope
- **WHEN** an active run already exists for the same experiment and run idempotency key
- **THEN** creating or reconciling the same key returns or updates that run instead of inserting a duplicate

#### Scenario: Run idempotency is scoped by experiment
- **WHEN** two experiments use the same run idempotency key
- **THEN** the system permits one active run row per experiment/key pair

#### Scenario: Reject invalid run idempotency key
- **WHEN** an agent supplies a run idempotency key that is not a lowercase slug
- **THEN** the system rejects the write with a validation error

### Requirement: Link jobs to many runs
The system SHALL model execution attempts that touch multiple runs.

#### Scenario: Link one job to many runs
- **WHEN** an agent links one job to multiple runs
- **THEN** the system stores one active job-run edge for each run

#### Scenario: Link one run to many jobs
- **WHEN** a run is trained, exported, evaluated, and collected by separate jobs
- **THEN** the system stores all job-run edges without overwriting prior edges

#### Scenario: Store job-run role
- **WHEN** an agent links a job and run with role `train`, `eval`, `export`, `analyze`, `collect`, or `other`
- **THEN** the system stores and exposes the role

#### Scenario: Reject invalid job-run role
- **WHEN** an agent supplies any other job-run role
- **THEN** the system rejects the write with a validation error

#### Scenario: Store job-run status
- **WHEN** an agent links or updates a job-run edge with status `planned`, `submitting`, `unknown_submit`, `queued`, `running`, `succeeded`, `failed`, `killed`, `skipped`, or `unknown`
- **THEN** the system stores and exposes the per-edge status

#### Scenario: Reject invalid job-run status
- **WHEN** an agent supplies any other job-run status
- **THEN** the system rejects the write with a validation error

#### Scenario: Preserve job-level status separately
- **WHEN** a parent job succeeds but one child run edge fails
- **THEN** the system can store the job as succeeded while storing the child job-run edge as failed

#### Scenario: Backfill simple job-run edge
- **WHEN** an agent creates a job with `--run`
- **THEN** the system creates or updates a matching `job_runs` edge for compatibility

### Requirement: Derive run progress
The system SHALL derive matrix progress from runs, job-run edges, artifacts, metrics, and optional experiment attrs.

#### Scenario: Planned phase
- **WHEN** a run has no active job-run edges and no run-linked evidence
- **THEN** run progress reports phase `planned`

#### Scenario: Submitted phase
- **WHEN** a run has active job-run edges but no running, succeeded, failed, skipped, checkpoint, eval artifact, or required metric evidence
- **THEN** run progress reports phase `submitted`

#### Scenario: Unknown-submit phase
- **WHEN** a run has a job-run edge with status `unknown_submit` and no stronger phase evidence
- **THEN** run progress reports phase `submitted`

#### Scenario: Training phase
- **WHEN** a run has a train edge with status `submitting`, `queued`, or `running`
- **THEN** run progress reports phase `training`

#### Scenario: Trained phase
- **WHEN** a run has a successful train edge or checkpoint artifact and lacks eval completion evidence
- **THEN** run progress reports phase `trained`

#### Scenario: Evaluated phase
- **WHEN** a run has a successful eval edge or eval-result artifact and required metric completion is not satisfied
- **THEN** run progress reports phase `evaluated`

#### Scenario: Complete phase without required metrics
- **WHEN** a run is evaluated and the experiment has no required metrics declaration
- **THEN** run progress reports phase `complete`

#### Scenario: Complete phase with required metrics
- **WHEN** a run has every metric declared in the experiment's `progress.required_metrics` attr
- **THEN** run progress reports phase `complete`

#### Scenario: Failed phase
- **WHEN** a run has failed or killed job-run evidence and no later successful train or eval evidence
- **THEN** run progress reports phase `failed`

#### Scenario: Retry success supersedes failure
- **WHEN** a run has failed train evidence and later successful train evidence
- **THEN** run progress no longer reports phase `failed`

#### Scenario: Skipped phase
- **WHEN** a run has only skipped job-run evidence and no success evidence
- **THEN** run progress reports phase `skipped`

### Requirement: Expose run progress in experiment resume surfaces
The system SHALL expose bounded matrix progress in experiment status and context.

#### Scenario: Status run progress block
- **WHEN** an agent runs `fieldbook experiment status <experiment> --json`
- **THEN** the output includes `runs.total`, `runs.expected`, `runs.missing_expected_count`, `runs.by_kind`, `runs.by_phase`, `runs.coverage`, and bounded failure/missing examples

#### Scenario: Empty experiment progress block
- **WHEN** an experiment has no active runs
- **THEN** status reports `runs.total=0`, empty dictionaries for `by_kind` and `by_phase`, zero coverage counts, and empty examples

#### Scenario: Context matrix section
- **WHEN** an agent runs `fieldbook experiment context <experiment>`
- **THEN** text output includes a bounded Markdown matrix-progress section

#### Scenario: Expected run gap
- **WHEN** an experiment declares `progress.expected_runs` greater than observed active runs
- **THEN** status reports the missing expected count

#### Scenario: Required metrics complete
- **WHEN** an experiment declares `progress.required_metrics` and a run has every named metric
- **THEN** run progress reports that run as complete
