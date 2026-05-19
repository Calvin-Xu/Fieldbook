## ADDED Requirements

### Requirement: Support external-repo invocation without downstream dependencies
The system SHALL document and validate a way to run Fieldbook from an ML repo without adding Fieldbook to that repo's dependency files.

#### Scenario: Invoke Fieldbook through a sidecar checkout
- **WHEN** an agent is inside a downstream repo such as Marin
- **THEN** it can run `uv run --project <FIELDBOOK_CHECKOUT> fieldbook <args>` from inside the downstream repo working tree without changing the downstream repo's `pyproject.toml`

#### Scenario: Record invocation provenance
- **WHEN** a dogfood report is produced
- **THEN** it records the invocation method, Fieldbook checkout path, Fieldbook git SHA, downstream repo path, downstream git SHA, command working directory, and resolved command form

#### Scenario: Provide fallback tool installation
- **WHEN** an agent wants a shorter repeated command
- **THEN** the documentation describes `uv tool install --editable <FIELDBOOK_CHECKOUT>` as a fallback that still does not modify the downstream repo
