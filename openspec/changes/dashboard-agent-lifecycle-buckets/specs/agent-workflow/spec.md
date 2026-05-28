## MODIFIED Requirements

### Requirement: Make Fieldbook the default active-experiment entrypoint
The system SHALL document dashboard lifecycle state as an input to agent
workflow, not as dashboard-owned state.

#### Scenario: Skill describes lifecycle buckets
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it explains that dashboard lifecycle buckets are rule-derived from
  ledger records and that agents should update the ledger through CLI/reconcile
  paths

#### Scenario: Agents record review completion
- **WHEN** an agent finishes reviewing experiment outputs
- **THEN** guidance directs it to run `fieldbook experiment mark-reviewed` with
  a concise Markdown summary
