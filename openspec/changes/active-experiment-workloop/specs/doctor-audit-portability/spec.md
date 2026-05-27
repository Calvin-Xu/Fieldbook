## MODIFIED Requirements

### Requirement: Diagnose ledger health issues
The system SHALL support experiment-scoped doctor output for active work.

#### Scenario: Doctor filters to one experiment
- **WHEN** an agent runs `fieldbook doctor --experiment <experiment> --json`
- **THEN** doctor reports issues scoped to the experiment and its linked runs,
  jobs, artifacts, metrics, notes, validations, sessions, refresh events,
  reconcile events, and sync events

#### Scenario: Scoped doctor suppresses unrelated archived history
- **WHEN** archived or unrelated experiments have doctor issues
- **THEN** scoped doctor does not include those issues in the requested
  experiment's issue list

#### Scenario: Scoped doctor reports omitted global issue count
- **WHEN** full-ledger doctor would report additional issues outside the
  requested experiment
- **THEN** scoped doctor includes a count of omitted global issues and a
  suggested full-doctor command
