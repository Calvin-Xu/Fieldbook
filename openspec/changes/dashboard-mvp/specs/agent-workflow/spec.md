## MODIFIED Requirements

### Requirement: Make Fieldbook the default active-experiment entrypoint
The system SHALL document the dashboard as a read-only companion to the CLI
agent workflow.

#### Scenario: Agent skill preserves CLI mutation path
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it describes dashboard inspection as read-only and directs mutations
  through CLI/reconcile workflows

#### Scenario: Dashboard provides copyable CLI commands
- **WHEN** the dashboard displays a suggested next action
- **THEN** the command is suitable for a coding agent to inspect and run
  explicitly outside the dashboard
