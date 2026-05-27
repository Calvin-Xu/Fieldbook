## MODIFIED Requirements

### Requirement: Make Fieldbook the default active-experiment entrypoint
The system SHALL guide agents to start active experiment work through Fieldbook.

#### Scenario: Agent skill points to workloop
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it instructs active experiment checks to begin with
  `fieldbook experiment workloop <experiment> --json`

#### Scenario: README points to workloop
- **WHEN** an agent reads the README context-switch section
- **THEN** it presents `experiment workloop` as the preferred one-command resume
  surface before lower-level status, context, doctor, refresh, or checkpoint
  commands
