## MODIFIED Requirements

### Requirement: Provide compact experiment status for context recovery
The system SHALL include advisory ownership summaries in active experiment
resume surfaces.

#### Scenario: Status includes active lease summary
- **WHEN** an agent runs `fieldbook experiment status <experiment> --json`
- **THEN** the response includes bounded active lease summaries for linked
  experiments, runs, and jobs

#### Scenario: Workloop includes monitor ownership warnings
- **WHEN** an agent runs `fieldbook experiment workloop <experiment> --json`
- **THEN** the response includes active owners, stale heartbeats, expired
  leases, force-takeover history, and suggested next commands

### Requirement: Make Fieldbook the default active-experiment entrypoint
The system SHALL guide agents to use advisory leases for long-running
monitoring and parallel-agent coordination.

#### Scenario: Agent skill describes babysit ownership
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it instructs long-running babysitters to claim a lease, heartbeat
  during monitoring, and release or hand off before stopping
