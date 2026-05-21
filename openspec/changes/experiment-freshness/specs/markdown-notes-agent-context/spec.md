## MODIFIED Requirements

### Requirement: Store Markdown note metadata
The system SHALL treat checkpoint notes as Markdown-first experiment ledger records.

#### Scenario: Accept checkpoint note type
- **WHEN** an agent creates a note with note type `checkpoint`
- **THEN** the system accepts it as a valid note type

#### Scenario: Checkpoint notes appear in context
- **WHEN** experiment context is rendered
- **THEN** recent checkpoint notes are eligible for bounded display like recent research and decision notes
