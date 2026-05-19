## ADDED Requirements

### Requirement: Record durable ledger identity
The system SHALL assign every ledger an immutable ledger identifier.

#### Scenario: Initialize ledger identity
- **WHEN** an agent initializes a fresh ledger
- **THEN** the system records a non-empty `ledger_id` in schema metadata

#### Scenario: Preserve existing ledger identity
- **WHEN** a ledger already has a `ledger_id`
- **THEN** future opens, migrations, and init calls do not change it

#### Scenario: Backfill legacy ledger identity
- **WHEN** an existing ledger without `ledger_id` is opened by the new version
- **THEN** the system records one `ledger_id` and preserves it afterward

#### Scenario: Preserve ledger identity on snapshot import
- **WHEN** an agent imports a snapshot of a ledger that has a `ledger_id`
- **THEN** the imported file retains the source ledger's `ledger_id`, the
  snapshot metadata includes that `ledger_id`, and the system does not generate
  a new one

### Requirement: Explain ledger locality
The system SHALL expose how the current ledger path is resolved.

#### Scenario: Report resolved ledger
- **WHEN** an agent runs `fieldbook db where --json` from a directory with a
  resolvable ledger
- **THEN** the system returns the ledger path, ledger ID, cwd, git context, and
  resolution source

#### Scenario: Report missing ledger without failing
- **WHEN** an agent runs `fieldbook db where --json` from a directory with no
  ledger
- **THEN** the system exits successfully and returns `ledger_path=null`,
  `ledger_id=null`, and `would_init_at`

#### Scenario: Resolve shared ledger config
- **WHEN** a `.fieldbook` file contains `ledger: <path>`
- **THEN** ledger discovery resolves that path relative to the `.fieldbook`
  file after `--ledger` and `FIELDBOOK_LEDGER`, but before cwd-walk

#### Scenario: Discover shared ledger config by walking upward
- **WHEN** `.fieldbook` is not in cwd but exists in a parent directory
- **THEN** ledger discovery walks upward from cwd and uses the nearest
  `.fieldbook`

#### Scenario: Reject malformed shared ledger config
- **WHEN** `.fieldbook` is unreadable, malformed, or lacks a `ledger` key
- **THEN** the system reports a stable validation error and does not fall back
  to cwd-walk

#### Scenario: Report missing shared ledger target
- **WHEN** `.fieldbook` points at a ledger path that does not exist
- **THEN** non-init commands raise not-found, while `db where` reports the
  resolved path, `ledger_id=null`, and the `.fieldbook` resolution source

### Requirement: Create experiments idempotently
The system SHALL support stable experiment creation keys.

#### Scenario: Create with idempotency key
- **WHEN** an agent creates an experiment with a valid idempotency key
- **THEN** the system stores that key on the experiment

#### Scenario: Reuse existing idempotent experiment
- **WHEN** an active experiment already has the requested idempotency key
- **THEN** the create command returns the existing experiment with
  `existed=true` and does not update existing fields

#### Scenario: Reject invalid idempotency key
- **WHEN** an agent supplies an invalid idempotency key
- **THEN** the system rejects the command with a validation error

### Requirement: Track advisory agent sessions
The system SHALL track agent sessions for context switching without enforcing
exclusive ownership.

#### Scenario: Start session
- **WHEN** an agent starts a session for an experiment
- **THEN** the system creates a session row, writes a local session marker, and
  returns the session ID

#### Scenario: Session marker location and format
- **WHEN** session start writes a marker
- **THEN** it writes `.fieldbook.session` adjacent to the resolved ledger root,
  containing exactly `id: <session_id>`, and the marker is git-ignored by default

#### Scenario: Report current session
- **WHEN** an agent requests the current session
- **THEN** the system resolves `FIELDBOOK_SESSION_ID` before the marker file and
  returns the resolved session or `null`

#### Scenario: Switch sessions
- **WHEN** an agent switches from one open experiment session to another
- **THEN** the system closes the old session, writes a handoff note on the old
  experiment, opens a new session, updates the marker, and returns the target
  experiment context

#### Scenario: Handoff note records context snapshot
- **WHEN** session switch writes a handoff note on the old experiment
- **THEN** the note body summarizes open next-action, handoff, and debug notes,
  stale jobs, failed jobs, and recent key artifacts, and the note attrs include
  the closing session ID

#### Scenario: Switch is atomic
- **WHEN** session switch closes the old session, writes the handoff note, and
  opens the new session
- **THEN** those ledger writes happen inside one transaction

#### Scenario: Switch without current session
- **WHEN** an agent switches to an experiment without a current open session
- **THEN** the system opens the new session and does not write a handoff note

#### Scenario: End session
- **WHEN** an agent ends a session
- **THEN** the system records `ended_at` and removes the marker when it points
  at that session

#### Scenario: End without current session
- **WHEN** an agent ends the current session and no current session exists
- **THEN** the system exits successfully and reports that no session was closed

#### Scenario: Reject ending already closed session by ID
- **WHEN** an agent requests to end a session that already has `ended_at`
- **THEN** the system rejects the command with a stable validation error unless
  the session is being force-closed by a doctor remediation path

#### Scenario: Allow parallel sessions
- **WHEN** multiple agents start sessions in the same ledger
- **THEN** the system allows the sessions and does not enforce a uniqueness lock

#### Scenario: Reject archived experiment without override
- **WHEN** an agent starts or switches to an archived experiment without
  `--force-archived`
- **THEN** the system rejects the command with a stable validation error

### Requirement: Stamp session provenance best-effort
The system SHALL attach session lineage when a valid current session is
available.

#### Scenario: Stamp reconcile event
- **WHEN** reconcile runs with a valid current session
- **THEN** the reconcile event stores that session ID

#### Scenario: Stamp note attrs
- **WHEN** a note is added with a valid current session
- **THEN** the note attrs include `session_id`

#### Scenario: Stamp sync event attrs
- **WHEN** a sync event is recorded during reconcile with a valid current
  session
- **THEN** the sync event attrs include `session_id`

#### Scenario: Ignore unknown session stamps
- **WHEN** the resolved session ID is unknown or stale
- **THEN** writes still succeed without a session stamp

### Requirement: Diagnose session and locality risks
The system SHALL warn about stale sessions and likely worktree ledger mistakes.

#### Scenario: Warn on stale sessions
- **WHEN** doctor finds open sessions older than the stale-session threshold
- **THEN** it reports a stable warning with a suggested `session end --force`
  action

#### Scenario: Use default stale-session threshold
- **WHEN** doctor checks stale sessions without an override
- **THEN** it uses a 24-hour stale-session threshold

#### Scenario: Warn on likely linked-worktree ledger split
- **WHEN** doctor runs from a linked worktree using implicit ledger discovery
  while a recent adjacent ledger likely exists in the main worktree
- **THEN** it reports a stable ledger-locality warning

#### Scenario: Use default ledger-locality recency threshold
- **WHEN** doctor checks ledger locality without an override
- **THEN** it treats adjacent ledgers modified in the last 7 days as recent

#### Scenario: Respect explicit ledger choice
- **WHEN** a command uses `--ledger`, `FIELDBOOK_LEDGER`, or `.fieldbook`
- **THEN** doctor does not second-guess the ledger locality choice
