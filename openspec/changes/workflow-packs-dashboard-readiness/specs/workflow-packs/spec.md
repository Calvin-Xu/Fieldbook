## ADDED Requirements

### Requirement: Summarize experiment triage
The system SHALL provide a read-only triage command for resuming experiments.

#### Scenario: Triage as JSON
- **WHEN** an agent runs `fieldbook experiment triage <experiment> --json`
- **THEN** the system returns experiment summary, failed jobs, stale jobs,
  unresolved debug notes, key artifacts, doctor issue counts, and suggested next
  actions without mutating the ledger

#### Scenario: Triage as Markdown
- **WHEN** an agent runs `fieldbook experiment triage <experiment>`
- **THEN** the system emits bounded Markdown suitable for an LLM handoff

#### Scenario: Triage is read-only
- **WHEN** triage runs
- **THEN** it does not add notes, run reconcile, run writeback, archive rows, or
  create artifacts

### Requirement: Produce closeout checklist
The system SHALL provide a read-only closeout checklist.

#### Scenario: Closeout checklist as JSON
- **WHEN** an agent runs `fieldbook experiment closeout-checklist <experiment> --json`
- **THEN** the system returns checklist items for doctor health, failed/stale
  jobs, unresolved handoff/next-action/debug notes, metric-table exports, and
  final decision notes

#### Scenario: Closeout checklist as Markdown
- **WHEN** an agent runs `fieldbook experiment closeout-checklist <experiment>`
- **THEN** the system emits Markdown that an agent can attach as a decision note

#### Scenario: No closeout state mutation
- **WHEN** closeout checklist runs
- **THEN** it does not change experiment status or create new ledger rows

### Requirement: Provide workflow recipes and templates
The system SHALL ship agent-oriented workflow recipes and templates.

#### Scenario: Recipe files exist
- **WHEN** an agent inspects the Fieldbook skill references
- **THEN** it finds recipes for launch planning, eval refresh, failure triage,
  collaborator export, handoff, and closeout

#### Scenario: Templates validate
- **WHEN** committed reconcile-manifest templates are tested
- **THEN** they parse as reconcile manifests and dry-run successfully against a
  fixture ledger after substituting `<EXPERIMENT_ID>`, `<RUN_ID>`, `<JOB_ID>`,
  `<ARTIFACT_URI>`, `<METRIC_NAME>`, and `<NOTE_BODY>`

#### Scenario: Note templates validate
- **WHEN** committed note templates are tested
- **THEN** their Markdown bodies pass Fieldbook note validation after placeholder
  substitution

#### Scenario: Recipes avoid private examples
- **WHEN** tests scan committed recipes and templates
- **THEN** they reject private local paths, real W&B URLs, real private cloud
  buckets, and credential-looking strings
