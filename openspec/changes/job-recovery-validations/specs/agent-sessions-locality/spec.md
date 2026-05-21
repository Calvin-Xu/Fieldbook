## MODIFIED Requirements

### Requirement: Track advisory agent sessions
The system SHALL track agent sessions for context switching without enforcing exclusive ownership.

#### Scenario: Experiment status shows active blockers
- **WHEN** an agent runs `fieldbook experiment status <experiment> --json`
- **THEN** the output includes `ready`, `blocking_failed_jobs`, `submission_in_progress_jobs`, `submission_unknown_jobs`, `recovery_in_progress_failed_jobs`, `recovered_failed_jobs`, and validation summaries derived from current jobs and validations

#### Scenario: Experiment context prioritizes blockers
- **WHEN** an agent runs `fieldbook experiment context <experiment>`
- **THEN** the Markdown output prioritizes active blockers, failed validations, submission uncertainty, in-progress recoveries, and next actions before historical recovered failures

#### Scenario: Preserve historical failed jobs
- **WHEN** an experiment has recovered failures
- **THEN** status and context preserve them as historical information without treating them as active blockers

#### Scenario: Preserve in-progress recovery state
- **WHEN** an experiment has failed jobs with queued or running retry descendants
- **THEN** status and context preserve them as in-progress recoveries without treating them as blocking failed jobs

#### Scenario: Preserve submission uncertainty
- **WHEN** an experiment has jobs in `submitting` or `unknown_submit`
- **THEN** status and context preserve them as active uncertainty with suggested refresh or correction actions without treating them as blocking failed jobs

#### Scenario: Bound recovered failure output
- **WHEN** an experiment has many recovered failures
- **THEN** status and context summarize them compactly and direct agents to drilldown commands or SQL views for full details
