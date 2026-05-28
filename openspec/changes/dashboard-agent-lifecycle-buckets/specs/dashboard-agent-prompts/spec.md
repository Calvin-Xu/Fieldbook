## MODIFIED Requirements

### Requirement: Provide closed-catalog agent prompt builders
The system SHALL provide a closed catalog of dashboard-oriented agent
instructions.

#### Scenario: Prompt catalog lists known actions
- **WHEN** an agent runs `fieldbook prompt list --json`
- **THEN** Fieldbook returns the registered action ids, titles, descriptions,
  catalog version `prompts_v1`, and read-only entry commands

#### Scenario: Prompt catalog contains complete action metadata
- **WHEN** the prompt catalog is loaded
- **THEN** every action has an action id, title, description, applicability
  logic, issue summary, prompt template, one read-only entry command, and a
  concise constraint

#### Scenario: Prompt actions are filtered by experiment state
- **WHEN** an agent runs `fieldbook prompt actions <experiment> --json`
- **THEN** Fieldbook returns only prompt actions currently applicable to the
  requested experiment

#### Scenario: Prompt build returns Markdown text
- **WHEN** an agent runs `fieldbook prompt build <action> <experiment>`
- **THEN** Fieldbook prints a bounded Markdown instruction for a coding agent

#### Scenario: Prompt build returns structured JSON
- **WHEN** an agent runs `fieldbook prompt build <action> <experiment> --json`
- **THEN** Fieldbook returns `envelope_version`, `catalog_version`, the action
  id, title, experiment id/name, applicability state, issue summary, entry
  command, constraints, and prompt body

#### Scenario: Prompt build rejects inapplicable actions
- **WHEN** an agent runs `fieldbook prompt build <action> <experiment>` for an
  action that is not applicable to the experiment state
- **THEN** Fieldbook exits with a validation error and does not render a prompt

#### Scenario: Prompt identifies experiment
- **WHEN** a prompt is built
- **THEN** the prompt body includes both the experiment id and experiment name

#### Scenario: Refresh prompt action is applicable
- **WHEN** `v_dashboard_experiments_v1.active_job_count` is greater than zero
- **THEN** `refresh-external-state` is applicable and uses entry command
  `fieldbook experiment workloop <id> --json`

#### Scenario: Failed-job prompt action follows actionable recovery state
- **WHEN** `v_dashboard_experiments_v1.blocking_failed_job_count` or
  `v_dashboard_experiments_v1.recovery_in_progress_failed_job_count` is greater
  than zero
- **THEN** `resolve-failed-jobs` is applicable and raw historical recovered
  failures do not make it applicable

#### Scenario: Failing-validation prompt action is applicable
- **WHEN** `v_dashboard_experiments_v1.failing_validation_count` is greater
  than zero
- **THEN** `fix-failing-validations` is applicable and uses entry command
  `fieldbook validation list --entity-type experiment --entity-id <id> --json`

#### Scenario: Handoff prompt action is applicable
- **WHEN** `v_dashboard_experiments_v1.handoff_status` is `missing` or `stale`
- **THEN** `write-handoff` is applicable and uses entry command
  `fieldbook experiment workloop <id> --json`

#### Scenario: Stale-lease prompt action is applicable
- **WHEN** `v_dashboard_experiments_v1.stale_lease_count` is greater than zero
- **THEN** `resolve-stale-leases` is applicable and uses entry command
  `fieldbook lease list --entity-type experiment --entity-id <id> --json`

#### Scenario: Open-note prompt action is applicable
- **WHEN** `v_dashboard_notes_v1` contains an open `handoff`, `next-action`, or
  `debug` note for the experiment
- **THEN** `review-open-notes` is applicable and uses entry command
  `fieldbook experiment context <id>`

#### Scenario: Review outputs prompt action is applicable
- **WHEN** `v_dashboard_experiments_v1.lifecycle_state` is `review`
- **THEN** `review-outputs` is applicable and uses entry command
  `fieldbook experiment workloop <id> --json`

#### Scenario: Review outputs prompt coexists with open-note review
- **WHEN** an experiment has both pending reviewable outputs and open action
  notes
- **THEN** `review-outputs` and `review-open-notes` may both be applicable

### Requirement: Keep prompts short, safe, and skill-oriented
The system SHALL render prompts as short pointers to an experiment issue rather
than standalone workflow manuals.

#### Scenario: Prompt references Fieldbook skill
- **WHEN** a prompt is built
- **THEN** it tells the coding agent to use the Fieldbook skill rather than
  embedding the skill body

#### Scenario: Prompt contains one read-only entry command
- **WHEN** a prompt is built
- **THEN** it contains exactly one `fieldbook ...` command line and that command
  is one of the prompt-builder read-only allow-list forms

#### Scenario: Prompt excludes mutation flags
- **WHEN** a prompt is built
- **THEN** it does not contain `--apply`, `--force`, `--archive`, `--errata`,
  `--errata-force`, `--checkpoint`, `--update-existing`, or `--retry-of`

#### Scenario: Prompt length is capped
- **WHEN** a prompt is built
- **THEN** its body is at most 1500 characters

#### Scenario: Prompt rejects suspected secrets
- **WHEN** the rendered prompt text matches known suspected secret patterns
- **THEN** Fieldbook rejects the prompt build as a validation error

#### Scenario: Prompt rejects skill-body embedding
- **WHEN** the rendered prompt text contains more than 200 contiguous characters
  copied from `.codex/skills/fieldbook/SKILL.md`
- **THEN** Fieldbook rejects the prompt build as a validation error

### Requirement: Render prompt actions in dashboard without sending them
The dashboard SHALL render applicable agent-instruction cards without sending
or executing the generated prompts.

#### Scenario: Dashboard renders applicable prompt cards
- **WHEN** a user opens an experiment detail page
- **THEN** the page shows agent-instruction cards for applicable prompt actions

#### Scenario: Dashboard hides prompt bodies by default
- **WHEN** a prompt card is rendered
- **THEN** the prompt body is inside a native
  `<details><summary>Preview agent instruction</summary>` disclosure

#### Scenario: Dashboard does not send prompts
- **WHEN** the dashboard route table is inspected
- **THEN** there is no POST, PATCH, DELETE, IPC, or external send route for
  prompt delivery
