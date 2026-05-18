## ADDED Requirements

### Requirement: Provide compact experiment status
The system SHALL provide a concise status summary for an experiment suitable
for coding-agent context recovery. The primary caller SHALL be a coding agent
acting from natural-language human instructions.

#### Scenario: Show experiment status
- **WHEN** a user runs a status command for an experiment
- **THEN** the system reports experiment summary, run counts, job counts by
  status, stale running jobs, failed jobs, key artifacts, and next-action notes

#### Scenario: Select key artifacts
- **WHEN** the system builds compact experiment status
- **THEN** key artifacts include latest checkpoint artifacts, latest
  eval-result artifacts, latest metric-table artifacts, and artifacts mentioned
  by unresolved next-action notes

### Requirement: Identify stale running jobs
The system SHALL identify jobs that have been running longer than a user
provided or default staleness threshold. The default threshold SHALL be 24
hours.

#### Scenario: Stale job detected
- **WHEN** a job has status `running` and has not been updated within the
  staleness threshold
- **THEN** the experiment status marks the job as stale and includes its
  external identifier when available

#### Scenario: Override staleness threshold
- **WHEN** a user supplies a staleness threshold
- **THEN** the system uses that threshold for the current status query

### Requirement: Preserve next actions
The system SHALL allow agents to record explicit next actions for an
experiment, run, or job.

#### Scenario: Add next action
- **WHEN** an agent records a next action after launching or debugging jobs
- **THEN** the next action appears in the compact experiment status until it is
  resolved or superseded

### Requirement: Drill down without loading all context
The system SHALL support targeted show commands for experiments, runs, jobs,
artifacts, and notes.

#### Scenario: Show one job
- **WHEN** a user asks for details on one job
- **THEN** the system displays that job's status, command, external links,
  artifacts, failure reason, notes, and related runs without dumping unrelated
  experiment history

#### Scenario: Show one experiment for agent handoff
- **WHEN** an agent asks for one experiment's handoff context
- **THEN** the system displays only the experiment summary, active jobs,
  unresolved next actions, recent notes, and key artifacts needed to resume work

### Requirement: Support machine-readable output
The system SHALL support JSON output for commands that agents need to compose:
`list`, `show`, `status`, and commands that create or add entities.

#### Scenario: Agent requests JSON
- **WHEN** an agent passes a JSON output flag to a supported command
- **THEN** the system emits stable machine-readable JSON for the requested
  entity or status summary

#### Scenario: JSON output for ID-minting command
- **WHEN** an agent creates or adds an entity with JSON output enabled
- **THEN** the system emits the minted identifier and enough summary fields for
  the agent to reference the entity in subsequent commands

#### Scenario: JSON output for list command
- **WHEN** an agent lists entities with JSON output enabled
- **THEN** the system emits a list of matching entities with stable field names

#### Scenario: JSON output excludes unrelated history
- **WHEN** an agent requests JSON for one experiment, run, job, artifact, or note
- **THEN** the system emits only the requested entity and directly related
  records needed for that response
