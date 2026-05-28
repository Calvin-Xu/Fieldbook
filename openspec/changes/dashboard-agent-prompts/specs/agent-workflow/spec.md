## MODIFIED Requirements

### Requirement: Make Fieldbook the default active-experiment entrypoint
The system SHALL document dashboard prompt cards as human-to-agent handoff
helpers.

#### Scenario: Skill describes dashboard prompts
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it explains that dashboard prompts are short user-facing
  instructions and that the agent should rely on the Fieldbook skill for
  detailed workflow practice

#### Scenario: README describes prompt copy boundary
- **WHEN** a user reads the dashboard documentation
- **THEN** it states that the dashboard does not send prompts to agents and
  that the human copies instructions into an ongoing coding-agent session

#### Scenario: Prompt commands are read-only commands
- **WHEN** `fieldbook prompt list`, `fieldbook prompt actions`, or
  `fieldbook prompt build` runs
- **THEN** Fieldbook treats the command as read-only for ledger version checks
  and does not mutate the ledger
