## MODIFIED Requirements

### Requirement: Refresh external state explicitly
The system SHALL allow the active-experiment workloop to invoke configured
refresh sources only when explicitly requested.

#### Scenario: Workloop does not refresh by default
- **WHEN** an agent runs `fieldbook experiment workloop <experiment>` without
  refresh flags
- **THEN** no refresh source is executed

#### Scenario: Workloop dry-runs selected refresh source
- **WHEN** an agent runs workloop with `--refresh <source>`
- **THEN** Fieldbook runs that source in dry-run mode, records the refresh event,
  and includes the snapshot, manifest, reconcile counts, and next action in the
  workloop output

#### Scenario: Workloop applies selected refresh source
- **WHEN** an agent runs workloop with `--refresh <source> --apply`
- **THEN** Fieldbook applies the generated reconcile manifest and shows
  post-refresh status in the output

#### Scenario: Workloop all-source refresh is explicit
- **WHEN** an agent runs workloop with `--refresh-all`
- **THEN** the output reports that all configured runnable sources were
  explicitly requested

#### Scenario: Workloop refresh surfaces drift
- **WHEN** a requested refresh observes local artifact drift
- **THEN** workloop output includes bounded drifted artifact entries and a
  suggested refresh-local or validation rerun action
