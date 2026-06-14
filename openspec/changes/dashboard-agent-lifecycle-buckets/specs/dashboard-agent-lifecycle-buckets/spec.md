## ADDED Requirements

### Requirement: Group experiments by agent lifecycle
The dashboard SHALL group experiments by deterministic agent lifecycle buckets.

#### Scenario: Lifecycle groups are ordered
- **WHEN** the dashboard index is rendered
- **THEN** experiments are grouped as `Needs attention`, `Running`,
  `Review`, `Open`, and `Archived`

#### Scenario: Lifecycle tokens are canonical
- **WHEN** stable dashboard views expose `lifecycle_state`
- **THEN** values use `needs_attention`, `running`, `review`, `open`, or
  `archived`

#### Scenario: Archived has highest precedence
- **WHEN** an experiment is archived or deleted
- **THEN** it is grouped under `Archived` regardless of jobs, notes, artifacts,
  or handoff freshness

#### Scenario: Actionable blockers need attention
- **WHEN** an active experiment has blocking failed jobs, failing validations,
  stale submissions, or stale advisory leases
- **THEN** it is grouped under `Needs attention`

#### Scenario: Live work is running
- **WHEN** an active experiment has active jobs and no higher-precedence
  actionable issue
- **THEN** it is grouped under `Running`

#### Scenario: Active lease alone is not running
- **WHEN** an active experiment has active advisory leases but no active jobs
  and no higher-precedence actionable issue
- **THEN** it is not grouped under `Running`

#### Scenario: Active work has precedence over review
- **WHEN** an active experiment has active work and pending reviewable outputs
- **THEN** it is grouped under `Running` and exposes pending-review
  metadata separately

#### Scenario: Reviewable outputs enter review
- **WHEN** an active experiment has reviewable activity newer than the latest
  review marker and no higher-precedence actionable issue or active work
- **THEN** it is grouped under `Review`

#### Scenario: Dormant experiments remain open
- **WHEN** an active experiment has no actionable issue, active work, or pending
  review
- **THEN** it is grouped under `Open`

### Requirement: Track review markers as ledger records
The system SHALL represent review completion as auditable ledger records.

#### Scenario: Mark reviewed creates a review note
- **WHEN** an agent runs `fieldbook experiment mark-reviewed <experiment>`
- **THEN** Fieldbook writes a `review` note on the experiment with
  `fieldbook.review=true` and `fieldbook.reviewed_at=<UTC Z>`

#### Scenario: Review note type is valid
- **WHEN** an agent writes a note with `note_type=review`
- **THEN** Fieldbook accepts it as a valid experiment note type

#### Scenario: Review marker consumes current activity
- **WHEN** the latest review marker is newer than all reviewable activity
- **THEN** the experiment is no longer grouped under `Review`

#### Scenario: New activity reopens review
- **WHEN** new reviewable activity is recorded after the latest review marker
- **THEN** the experiment becomes eligible for `Review` again

#### Scenario: Review marker is not an action mutator
- **WHEN** review is marked
- **THEN** Fieldbook does not mutate job, run, artifact, validation, lease, or
  handoff state

### Requirement: Keep handoff freshness separate from lifecycle
The dashboard SHALL render handoff freshness without using it as a lifecycle
bucket.

#### Scenario: Missing handoff does not make stale bucket
- **WHEN** an experiment has missing or stale handoff freshness but no
  actionable issue, active work, or pending review
- **THEN** it is grouped under `Open`

#### Scenario: Handoff status remains visible
- **WHEN** an experiment card or detail freshness panel is rendered
- **THEN** it shows the handoff status and latest handoff timestamp when
  available
