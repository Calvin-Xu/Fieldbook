## MODIFIED Requirements

### Requirement: Provide compact experiment status for context recovery
The system SHALL include matrix run progress in agent resume surfaces.

#### Scenario: Status includes matrix summary
- **WHEN** an agent asks for experiment status
- **THEN** the response includes a compact run-progress block before detailed job drilldowns

#### Scenario: Context includes matrix handoff
- **WHEN** an agent asks for experiment context
- **THEN** Markdown output includes the run-progress summary and bounded incomplete-run examples

#### Scenario: Launch protocol records runs before jobs complete
- **WHEN** the Fieldbook agent skill describes launch workflow
- **THEN** it instructs agents to reconcile planned runs and job-run edges before or during external job submission

#### Scenario: Job add run compatibility uses other role
- **WHEN** an agent uses legacy `job add --run <run>`
- **THEN** the system creates a job-run edge with role `other` unless the agent explicitly links a more specific role
