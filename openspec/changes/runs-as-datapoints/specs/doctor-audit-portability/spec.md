## MODIFIED Requirements

### Requirement: Diagnose ledger health issues
The system SHALL warn when experiment matrices or job-run edges are incomplete or unlinked.

#### Scenario: Expected runs missing
- **WHEN** an experiment declares `progress.expected_runs` larger than active linked run count
- **THEN** doctor reports a `runs.expected_missing` warning

#### Scenario: Run artifact missing run link
- **WHEN** an active checkpoint or eval-result artifact is linked only to an experiment or job but not to a run
- **THEN** doctor reports an `artifact.unlinked_to_run` warning

#### Scenario: Job-run edge points to archived entity
- **WHEN** an active job-run edge references an archived job or archived run
- **THEN** doctor reports a `job_runs.orphan` warning

#### Scenario: Job-run edge stale active state
- **WHEN** a job-run edge is active/running but its parent job is terminal
- **THEN** doctor reports a `job_runs.stale_state` warning
