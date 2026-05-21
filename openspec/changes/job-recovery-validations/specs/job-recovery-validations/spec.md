## ADDED Requirements

### Requirement: Track job submission lifecycle
The system SHALL distinguish submission-attempt states from externally acknowledged execution states.

#### Scenario: Record in-flight submission
- **WHEN** an agent creates or updates a job with status `submitting`
- **THEN** the system stores the status and treats the job as active uncertainty

#### Scenario: Record ambiguous submission outcome
- **WHEN** an agent updates a job from `submitting` to `unknown_submit` with a failure reason
- **THEN** the system stores the transition and treats `unknown_submit` as active uncertainty, not as a blocking failure

#### Scenario: Confirm successful submission
- **WHEN** an agent updates a job from `submitting` or `unknown_submit` to `queued` or `running` with an external identifier
- **THEN** the system clears the submission-uncertainty classification

#### Scenario: Explicit submission rejection
- **WHEN** an external system explicitly rejects a submission
- **THEN** the agent can record the job as `failed` with a failure reason describing the rejection

#### Scenario: Refresh resolves submission ambiguity
- **WHEN** refresh discovers an external job matching an `unknown_submit` row
- **THEN** the reconcile manifest can update the job status to the confirmed execution state

#### Scenario: Refresh confirms missing acknowledgment
- **WHEN** refresh confirms no external job matches an `unknown_submit` row whose original submission window has elapsed
- **THEN** the reconcile manifest can update the job status to `failed` with a failure reason indicating the submission was never acknowledged

### Requirement: Track job retry lineage
The system SHALL allow a job to reference the failed job it retries.

#### Scenario: Create retry job
- **WHEN** an agent creates a job with a valid `retry_of` job ID
- **THEN** the system stores the retry lineage

#### Scenario: Link existing retry job
- **WHEN** an agent links an existing job to a valid `retry_of` job ID
- **THEN** the system stores the retry lineage without changing unrelated job fields

#### Scenario: Reject missing retry target
- **WHEN** an agent supplies a `retry_of` job ID that does not reference an active job
- **THEN** the system rejects the write with a validation error

#### Scenario: Reject self retry link
- **WHEN** an agent supplies a `retry_of` value equal to the job's own ID
- **THEN** the system rejects the write with a validation error

#### Scenario: Reject retry cycle
- **WHEN** a retry link would create a cycle
- **THEN** the system rejects the write with a validation error

#### Scenario: Resolve retry target created in same reconcile manifest
- **WHEN** a reconcile manifest creates one job and another job in the same manifest references it with `retry_of`
- **THEN** the system resolves the retry target within the same transaction and stores the retry lineage

#### Scenario: Reject missing retry target absent from manifest and ledger
- **WHEN** a reconcile manifest references a `retry_of` job ID that is absent from the active ledger and absent from the same manifest
- **THEN** the system rejects the manifest with a stable validation error before committing writes

#### Scenario: Preserve multi-hop retry chain
- **WHEN** job C retries job B and job B retries job A
- **THEN** the system preserves both links and exposes the transitive chain

### Requirement: Classify failed jobs by recovery state
The system SHALL distinguish blocking failures, in-progress recoveries, and historical failures recovered by retries.

#### Scenario: Blocking failed job
- **WHEN** a failed job has no transitive retry descendant with status `submitting`, `unknown_submit`, `queued`, `running`, or `succeeded`
- **THEN** the system classifies it as a blocking failed job

#### Scenario: Recovery in progress
- **WHEN** a failed job has at least one transitive retry descendant with status `submitting`, `unknown_submit`, `queued`, or `running` and no transitive retry descendant with status `succeeded`
- **THEN** the system classifies it as a recovery-in-progress failed job

#### Scenario: Recovered failed job
- **WHEN** a failed job has any transitive retry descendant with status `succeeded`
- **THEN** the system classifies it as a recovered failed job

#### Scenario: Completed unsuccessful retry remains blocking
- **WHEN** a failed job has retry descendants but none are in `submitting`, `unknown_submit`, `queued`, `running`, or `succeeded`
- **THEN** the system classifies the original failed job as blocking

#### Scenario: Archived failed job is historical
- **WHEN** a failed job is archived
- **THEN** the system does not classify it as an active blocking failure

#### Scenario: Recovery view includes retry metadata
- **WHEN** an agent queries `v_jobs_with_recovery_v1`
- **THEN** each job row includes retry target, retry state, retry descendant active state, retry descendant success state, blocking failure flag, recovery-in-progress flag, recovered failure flag, and terminal descendant identifiers when available

### Requirement: Store structured validation checks
The system SHALL store validation assertions as queryable ledger records.

#### Scenario: Add validation
- **WHEN** an agent records a validation with entity type, entity ID, check name, and status
- **THEN** the system stores the validation row with timestamps

#### Scenario: Validate status enum
- **WHEN** a validation status is not `pass`, `fail`, `warning`, or `unknown`
- **THEN** the system rejects the write with a validation error

#### Scenario: Update validation idempotently
- **WHEN** an active validation already exists for the same entity type, entity ID, and check name
- **THEN** adding the same validation key updates the existing validation instead of inserting a duplicate

#### Scenario: Archive validation
- **WHEN** an agent archives a validation
- **THEN** the system soft-archives the row and excludes it from active validation views

#### Scenario: Link validation evidence
- **WHEN** a validation references a source artifact or source job
- **THEN** the system stores the link after validating that the referenced row exists and is active

#### Scenario: Store validation details
- **WHEN** a validation includes JSON details or attrs
- **THEN** the system stores them as JSON objects and rejects non-object JSON

#### Scenario: Stamp validation session
- **WHEN** a validation is created while a valid session is current
- **THEN** the system records the session ID on the validation

### Requirement: Derive experiment readiness
The system SHALL derive experiment readiness from jobs and validations.

#### Scenario: No active blockers
- **WHEN** an experiment has no active running jobs, no blocking failed jobs, and no active failed validations
- **THEN** readiness reports no active blockers

#### Scenario: Blocking failed job prevents readiness
- **WHEN** an experiment has at least one blocking failed job
- **THEN** readiness reports active blockers and includes the failed job

#### Scenario: Recovery in progress is active work, not a blocking failure
- **WHEN** an experiment has a failed job classified as recovery-in-progress
- **THEN** readiness reports the in-flight recovery count and excludes that failed job from blocking failed jobs

#### Scenario: Submission uncertainty is active work, not a blocking failure
- **WHEN** an experiment has jobs in `submitting` or `unknown_submit` but no blocking failed jobs and no active failed validations
- **THEN** readiness reports submission uncertainty separately from blockers and does not classify those jobs as blocking failures

#### Scenario: Failed validation prevents readiness
- **WHEN** an experiment has an active validation with status `fail`
- **THEN** readiness reports active blockers and includes the validation

#### Scenario: Blocking unknown validation prevents readiness
- **WHEN** an experiment has an active validation with status `unknown` and attrs mark it blocking
- **THEN** readiness reports active blockers and includes the validation

#### Scenario: Warning validation does not block readiness
- **WHEN** an experiment only has active validations with status `warning` and no other blockers
- **THEN** readiness reports warnings but does not mark them as active blockers

### Requirement: Expose recovery and validation views
The system SHALL expose stable SQL views for recovery and validation analysis.

#### Scenario: Query recovery view
- **WHEN** an agent queries `v_jobs_with_recovery_v1`
- **THEN** the view returns active job rows with retry and recovery columns

#### Scenario: Query blocker view
- **WHEN** an agent queries `v_experiment_blockers_v1`
- **THEN** the view returns active blockers for jobs and validations with stable blocker type labels and excludes recovery-in-progress failed jobs from blocking-failure rows

#### Scenario: Query validation view
- **WHEN** an agent queries `v_validations_v1`
- **THEN** the view returns active validation rows with source artifact, source job, and session identifiers

### Requirement: Support validation report artifacts
The system SHALL support validation report artifacts as linked evidence.

#### Scenario: Add validation report artifact
- **WHEN** an agent adds an artifact with type `validation-report`
- **THEN** the system accepts it as a valid artifact type

#### Scenario: Use validation report as evidence
- **WHEN** a validation references a `validation-report` artifact
- **THEN** the system stores the source artifact link like any other artifact link
