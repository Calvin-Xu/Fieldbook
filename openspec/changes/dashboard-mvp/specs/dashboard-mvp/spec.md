## ADDED Requirements

### Requirement: Serve a read-only local dashboard
The system SHALL provide an on-demand dashboard server for read-only
experiment inspection.

#### Scenario: Dashboard binds to localhost by default
- **WHEN** an agent runs `fieldbook dashboard serve`
- **THEN** the server binds to `127.0.0.1:8765` unless an explicit host or port
  override is provided

#### Scenario: Dashboard exposes only read routes
- **WHEN** the dashboard route table is inspected
- **THEN** all application routes are read-only GET routes

#### Scenario: Dashboard exits with process
- **WHEN** the foreground dashboard process is stopped
- **THEN** no Fieldbook daemon, background worker, or monitor remains running

#### Scenario: Dashboard does not watch or auto-reload
- **WHEN** the dashboard server is running
- **THEN** Fieldbook does not start a file watcher, auto-reload process, or
  background refresh loop

### Requirement: Render active experiment state
The dashboard SHALL render active experiment state from stable views.

#### Scenario: Experiment index renders ledger overview
- **WHEN** a user opens the dashboard root page
- **THEN** it shows experiments grouped by active, stale, archived, and needing
  attention state

#### Scenario: Experiment detail renders coordination state
- **WHEN** a user opens an experiment detail page
- **THEN** it shows run progress, job recovery, advisory leases, validation
  readiness, freshness, latest notes, artifacts, and external links

#### Scenario: Empty ledger renders safely
- **WHEN** the ledger has no experiments
- **THEN** the dashboard renders an empty state with the relevant CLI command
  to create or initialize experiment records

#### Scenario: Missing ledger exits
- **WHEN** an agent runs dashboard serve with a ledger path that does not exist
- **THEN** Fieldbook exits with the same non-init ledger-not-found error as
  other commands

### Requirement: Dashboard actions are non-mutating
The dashboard SHALL show commands and links for actions without executing
mutations.

#### Scenario: Suggested action is a command
- **WHEN** the dashboard suggests refreshing an experiment
- **THEN** it renders a copyable `fieldbook` command rather than running the
  refresh

#### Scenario: External systems are links
- **WHEN** a run, job, artifact, or metric has an external URL
- **THEN** the dashboard renders a link without syncing or mutating external
  state
