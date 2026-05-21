## MODIFIED Requirements

### Requirement: Run read-only ledger doctor
The system SHALL audit ledger health without mutating the ledger.

#### Scenario: Detect retry cycle
- **WHEN** doctor finds a cycle in job retry lineage
- **THEN** it reports `job_retry.cycle` as an error

#### Scenario: Detect missing retry target
- **WHEN** doctor finds a retry link whose target job is missing or archived unexpectedly
- **THEN** it reports `job_retry.missing_target` as an error

#### Scenario: Detect retry loop pattern
- **WHEN** doctor finds a retry chain above the configured retry-loop threshold without a successful descendant
- **THEN** it reports `job_retry.loop` as a warning

#### Scenario: Detect active failed validation
- **WHEN** doctor finds an active validation with status `fail`
- **THEN** it reports `validation.failed` as a warning with the validation identity and suggested next action

#### Scenario: Detect blocking unknown validation
- **WHEN** doctor finds an active validation with status `unknown` and blocking attrs
- **THEN** it reports `validation.unknown_blocking` as a warning

#### Scenario: Detect recovered failure with open debug note
- **WHEN** doctor finds a recovered failed job that still has an open debug note attached to the job or experiment
- **THEN** it reports `job_retry.recovered_debug_open` as a warning

#### Scenario: Detect stale recovery in progress
- **WHEN** doctor finds a failed job with a queued or running retry descendant whose `updated_at` is older than the stale threshold
- **THEN** it reports `job_retry.recovery_stale` as a warning with the failed job, retry job, and suggested next action

#### Scenario: Detect stale submitting job
- **WHEN** doctor finds a job with status `submitting` whose `updated_at` is older than the submitting stale threshold
- **THEN** it reports `job_submission.submitting_stale` as a warning with the job identity and suggested refresh or status-correction action

#### Scenario: Detect stale unknown submission
- **WHEN** doctor finds a job with status `unknown_submit` whose `updated_at` is older than the unknown-submit stale threshold
- **THEN** it reports `job_submission.unknown_stale` as a warning with the job identity and suggested refresh or status-correction action

#### Scenario: Detect suspected secrets in ledger text
- **WHEN** doctor finds suspected secret patterns in job commands, JSON attribute values, or note bodies
- **THEN** it reports `privacy.secret_pattern` as a warning with the affected entity, pattern family, redacted snippet, and remediation guidance
