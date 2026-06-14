## MODIFIED Requirements

### Requirement: Render active experiment state
The dashboard SHALL render active experiment state through an ergonomic,
schema-aware UI.

#### Scenario: Experiment index renders lifecycle groups
- **WHEN** a user opens the dashboard root page
- **THEN** it shows a category sidebar and experiments grouped by needing
  attention, running, review, open, and archived lifecycle state with
  compact counts and status badges

#### Scenario: Handoff freshness is not a group
- **WHEN** an experiment has missing or stale handoff freshness
- **THEN** the dashboard renders that freshness as metadata rather than using a
  `Stale` lifecycle group

#### Scenario: Archived experiments are collapsed by default
- **WHEN** a user opens the dashboard root page
- **THEN** the archived experiment group is rendered in a collapsed native
  disclosure by default

#### Scenario: Experiment detail avoids raw table dumps
- **WHEN** a user opens an experiment detail page
- **THEN** run progress, job recovery, leases, validations, freshness, notes,
  artifacts, and external links are rendered with entity-specific cards or
  compact rows instead of generic raw tables

#### Scenario: Experiment context columns are omitted
- **WHEN** a child entity section is rendered on an experiment detail page
- **THEN** page-context columns such as `experiment_id` are not displayed as
  repeated row data

#### Scenario: Dashboard preserves vertical space
- **WHEN** the experiment detail page is rendered
- **THEN** the detail page uses a horizontal tab bar and renders one entity
  family per tab instead of stacking every section on one page

#### Scenario: Experiment detail keeps experiment navigation available
- **WHEN** a user opens an experiment detail tab
- **THEN** the category sidebar remains available for switching to another
  experiment

#### Scenario: Experiment tabs load only scoped data
- **WHEN** a user opens an experiment detail tab such as `runs`
- **THEN** the dashboard queries and renders only the stable-view data needed
  for that tab, plus the experiment/sidebar context

### Requirement: Dashboard actions are non-mutating
The dashboard SHALL show agent instructions and links for actions without
executing mutations.

#### Scenario: Suggested action is an agent instruction
- **WHEN** the dashboard suggests work for a coding agent
- **THEN** it renders a copyable/previewable agent instruction rather than a
  raw human-facing CLI command card

#### Scenario: Raw command cards are removed
- **WHEN** an experiment detail page is rendered
- **THEN** the page does not render Phase 19 raw CLI command cards for refresh,
  recovery, checkpoints, leases, or validation fixes
