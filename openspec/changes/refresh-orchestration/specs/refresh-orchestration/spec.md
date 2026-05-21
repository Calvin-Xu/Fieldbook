## ADDED Requirements

### Requirement: Configure refresh sources
The system SHALL load explicit refresh source definitions from local configuration.

#### Scenario: Discover refresh config
- **WHEN** an agent runs a refresh command without `--config`
- **THEN** the system looks for `.fieldbook/refresh.toml` under the resolved ledger root

#### Scenario: Use explicit refresh config
- **WHEN** an agent supplies `--config <path>`
- **THEN** the system loads refresh source definitions from that path

#### Scenario: Reject malformed refresh config
- **WHEN** the refresh config cannot be parsed as TOML or lacks required source fields
- **THEN** the system rejects the command with a validation error

#### Scenario: List refresh sources
- **WHEN** an agent runs `fieldbook refresh list-sources --json`
- **THEN** the system returns configured source names, descriptions, kinds, adapters, and whether each source is runnable

#### Scenario: Reject unknown refresh source
- **WHEN** an agent references a source name absent from config
- **THEN** the system rejects the command with a validation error

### Requirement: Require explicit refresh selection
The system SHALL not refresh external state unless the agent explicitly selects sources.

#### Scenario: Reject missing source
- **WHEN** an agent runs `fieldbook refresh run` without `--source` or `--all`
- **THEN** the system rejects the invocation with a validation error

#### Scenario: Run one source
- **WHEN** an agent runs `fieldbook refresh run --source <name>`
- **THEN** the system refreshes only that source

#### Scenario: Run all sources explicitly
- **WHEN** an agent runs `fieldbook refresh run --all`
- **THEN** the system refreshes configured runnable sources and reports that all-source mode was explicitly requested

#### Scenario: Session switch does not refresh
- **WHEN** an agent switches Fieldbook sessions
- **THEN** the system does not run any refresh source implicitly

### Requirement: Capture refresh snapshots
The system SHALL persist raw refresh snapshots before adapter translation.

#### Scenario: Capture command snapshot
- **WHEN** a command source exits successfully
- **THEN** the system writes command stdout to `.experiments/refresh-snapshots/<source>/<timestamp>.json`

#### Scenario: Capture file snapshot
- **WHEN** a file source references an existing file
- **THEN** the system copies that file to `.experiments/refresh-snapshots/<source>/<timestamp>.json`

#### Scenario: Reject missing file source
- **WHEN** a file source path does not exist
- **THEN** the system records a failed refresh event and does not run an adapter

#### Scenario: Preserve snapshot path in output
- **WHEN** a refresh command completes or fails after snapshot creation
- **THEN** text and JSON output include the snapshot path

#### Scenario: Write derived manifest and debug paths
- **WHEN** adapter translation runs
- **THEN** the system writes sibling manifest and debug files next to the snapshot

### Requirement: Run refresh as dry-run by default
The system SHALL default refresh to no entity mutation.

#### Scenario: Dry-run refresh
- **WHEN** an agent runs `fieldbook refresh run --source <name>` without `--apply`
- **THEN** the system captures the snapshot, runs the adapter, runs reconcile dry-run, records a refresh event with status `dry_run`, and does not mutate entity rows

#### Scenario: Apply refresh
- **WHEN** an agent supplies `--apply`
- **THEN** the system captures the snapshot, runs the adapter, applies reconcile, records a refresh event with status `applied`, and returns the reconcile event ID

#### Scenario: Apply uses reconcile
- **WHEN** refresh applies changes
- **THEN** all entity mutations occur through reconcile and its operation audit

#### Scenario: Applied single-source refresh updates readiness
- **WHEN** an agent runs `fieldbook refresh run --source <name> --apply` and the generated manifest updates jobs or validations for an experiment
- **THEN** a subsequent `fieldbook experiment status <experiment>` reflects the updated job recovery and validation readiness state from that source

### Requirement: Resolve submission uncertainty through refresh
The system SHALL surface how refresh affects jobs whose submission state is uncertain.

#### Scenario: Refresh updates submission-state jobs
- **WHEN** refresh apply discovers external acknowledgment for a job in `submitting` or `unknown_submit`
- **THEN** the resulting reconcile updates the job status and external identifier through normal reconcile semantics

#### Scenario: Refresh reports unresolved submission uncertainty
- **WHEN** refresh apply finds no external record for a job in `unknown_submit` whose submission window has elapsed
- **THEN** text and JSON output surface the job in a `submission_resolutions` section with a suggested next action to resubmit or mark failed

#### Scenario: Refresh marks never-acknowledged submission failed
- **WHEN** a refresh manifest determines that an `unknown_submit` job was never acknowledged
- **THEN** applying the manifest can update the job to `failed` with a failure reason describing the missing acknowledgment

### Requirement: Record refresh events
The system SHALL record every refresh attempt as an auditable event.

#### Scenario: Record dry-run event
- **WHEN** refresh dry-run succeeds
- **THEN** the system records source name, experiment ID when supplied, session ID when current, status, stage, timestamps, snapshot path, manifest path, debug path, counts, and command metadata

#### Scenario: Record applied event
- **WHEN** refresh apply succeeds
- **THEN** the system records the reconcile event ID on the refresh event

#### Scenario: Record helper failure
- **WHEN** a command source exits nonzero
- **THEN** the system records a failed refresh event with stage `helper` and does not run adapter or reconcile

#### Scenario: Record adapter failure
- **WHEN** adapter translation fails
- **THEN** the system records a failed refresh event with stage `adapter` and does not run reconcile

#### Scenario: Record reconcile failure
- **WHEN** reconcile dry-run or apply fails
- **THEN** the system records a failed refresh event with stage `reconcile`

#### Scenario: Stamp refresh session
- **WHEN** refresh runs with a valid current session
- **THEN** the refresh event stores that session ID

### Requirement: Expose refresh log
The system SHALL expose recent refresh attempts through CLI and SQL.

#### Scenario: List refresh log
- **WHEN** an agent runs `fieldbook refresh log --json`
- **THEN** the system returns refresh events newest-first with stable fields

#### Scenario: Default refresh log limit
- **WHEN** an agent runs `fieldbook refresh log` without `--limit`
- **THEN** the system returns at most 20 events

#### Scenario: Filter refresh log
- **WHEN** an agent supplies `--source`, `--status`, `--since`, `--before`, or `--limit`
- **THEN** the system returns only matching refresh events

#### Scenario: Query refresh view
- **WHEN** an agent queries `v_refresh_log_v1`
- **THEN** the view returns active refresh event rows with source, status, stage, path, count, session, and reconcile identifiers

### Requirement: Keep refresh output agent-readable
The system SHALL emit bounded text and structured JSON for refresh operations.

#### Scenario: Text refresh output
- **WHEN** an agent runs refresh without `--json`
- **THEN** the system prints a compact summary with status, stage, paths, counts, and next action

#### Scenario: JSON refresh output
- **WHEN** an agent runs refresh with `--json`
- **THEN** the system returns a structured envelope with source, status, stage, paths, counts, event ID, reconcile event ID, and truncation flags

#### Scenario: JSON refresh output includes submission resolutions
- **WHEN** refresh inspects or updates jobs in `submitting` or `unknown_submit`
- **THEN** the JSON envelope includes bounded `submission_resolutions` entries with `job_id`, `previous_status`, `resolved_status`, `external_system`, `external_id`, and `suggested_action`

#### Scenario: Failure output includes next action
- **WHEN** refresh fails at any stage
- **THEN** text and JSON output include a suggested next action for inspecting snapshot, debug, manifest, or reconcile error details
