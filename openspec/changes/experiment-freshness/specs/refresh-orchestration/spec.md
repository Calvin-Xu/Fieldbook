## MODIFIED Requirements

### Requirement: Keep refresh output agent-readable
The system SHALL surface local artifact drift observed during explicit refresh runs.

#### Scenario: Refresh output includes drifted artifacts
- **WHEN** refresh observes local artifact drift in scope
- **THEN** JSON output includes bounded `drifted_artifacts` entries and text output includes a compact drift count
