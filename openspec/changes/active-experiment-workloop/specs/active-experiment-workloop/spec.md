## ADDED Requirements

### Requirement: Provide active-experiment workloop
The system SHALL provide a single active-experiment workloop surface for agents
returning to or leaving an experiment.

#### Scenario: Workloop returns bounded active-experiment report
- **WHEN** an agent runs `fieldbook experiment workloop <experiment> --json`
- **THEN** the response includes top-level `experiment`, `locality`,
  `session`, `runs`, `jobs`, `validations`, `freshness`, `notes`, `doctor`,
  and `suggested_next_actions` blocks

#### Scenario: Workloop text output is Markdown
- **WHEN** an agent runs `fieldbook experiment workloop <experiment>`
- **THEN** the response is bounded Markdown suitable for LLM handoff context

#### Scenario: Workloop is read-only by default
- **WHEN** an agent runs workloop without apply, cleanup, or checkpoint flags
- **THEN** the ledger is not mutated

#### Scenario: Workloop composes existing surfaces
- **WHEN** an agent runs workloop
- **THEN** Fieldbook composes existing status, context, freshness, refresh,
  validation, note, run-progress, and doctor helpers without changing the
  public behavior of `experiment status` or `experiment context`

#### Scenario: Workloop does not enforce ownership or execute jobs
- **WHEN** an agent runs workloop for an experiment with active jobs
- **THEN** Fieldbook reports observed state and suggested commands without
  launching, stopping, resubmitting, monitoring, or locking external jobs

#### Scenario: Workloop can checkpoint explicitly
- **WHEN** an agent runs workloop with `--checkpoint`
- **THEN** Fieldbook writes one checkpoint note for the experiment after the
  workloop report is generated

#### Scenario: Workloop accepts normal note body sources
- **WHEN** an agent runs workloop checkpoint with exactly one of `--body`,
  `--body-file`, or `--body-stdin`
- **THEN** Fieldbook uses that Markdown body and appends the generated
  workloop/freshness summary

#### Scenario: Workloop rejects body source without checkpoint
- **WHEN** an agent runs workloop with `--body`, `--body-file`, or
  `--body-stdin` without `--checkpoint`
- **THEN** Fieldbook rejects the command as a validation error

#### Scenario: Workloop reports global issue count
- **WHEN** scoped workloop output hides unrelated global doctor issues
- **THEN** it reports `doctor.global_omitted_count` and suggests running full
  `fieldbook doctor --json` for ledger-wide maintenance

### Requirement: Provide active-experiment cleanup
The system SHALL expose explicit dry-run cleanup for common recovered-state
bookkeeping issues.

#### Scenario: Plan recovered debug-note cleanup
- **WHEN** a recovered failed job has open debug notes in the requested
  experiment
- **THEN** `fieldbook experiment cleanup <experiment> --json` includes planned
  note resolutions without mutating the ledger

#### Scenario: Plan superseded validation cleanup
- **WHEN** an older warning or failing validation is superseded by a newer pass
  for the same validation key in the requested experiment
- **THEN** cleanup dry-run includes a planned validation archive

#### Scenario: Apply cleanup explicitly
- **WHEN** an agent runs cleanup with `--apply`
- **THEN** Fieldbook applies only the planned changes for the requested
  experiment and records a checkpoint note describing what changed

#### Scenario: Cleanup does not cross experiment boundaries
- **WHEN** another experiment has similar stale debug notes or validations
- **THEN** cleanup for the requested experiment does not mutate the other
  experiment
