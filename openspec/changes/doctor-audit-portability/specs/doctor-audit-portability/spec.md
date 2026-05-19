## ADDED Requirements

### Requirement: Run read-only ledger doctor
The system SHALL audit ledger health without mutating the ledger.

#### Scenario: Run doctor successfully
- **WHEN** an agent runs `fieldbook doctor --json`
- **THEN** the system opens the ledger read-only and returns a versioned envelope with issue counts and issue rows

#### Scenario: Doctor does not write
- **WHEN** doctor runs on any ledger
- **THEN** it does not insert, update, archive, delete, or reconcile any row

#### Scenario: Doctor rejects older schema
- **WHEN** doctor opens a ledger with `PRAGMA user_version` lower than the installed Fieldbook schema
- **THEN** it exits with validation-error status and reports `schema.version_mismatch` without running migrations

#### Scenario: Doctor rejects newer schema
- **WHEN** doctor opens a ledger with `PRAGMA user_version` higher than the installed Fieldbook schema
- **THEN** it exits with validation-error status and reports `schema.version_mismatch`

#### Scenario: Doctor reports ledger busy
- **WHEN** doctor cannot obtain a read-only connection because the ledger is locked
- **THEN** it exits with ledger-busy status

#### Scenario: Doctor text output is compact
- **WHEN** an agent runs `fieldbook doctor`
- **THEN** the system prints a compact summary grouped by severity and issue code

#### Scenario: Doctor JSON output is structured
- **WHEN** an agent runs `fieldbook doctor --json`
- **THEN** each issue includes stable `code`, `severity`, optional entity identity, message, details, and suggested next action

#### Scenario: Doctor exits nonzero for errors
- **WHEN** doctor finds one or more error-severity issues
- **THEN** the command exits with validation-error status after emitting output

#### Scenario: Doctor strict mode escalates warnings
- **WHEN** doctor finds only warnings and the agent supplies `--strict`
- **THEN** the command exits with validation-error status after emitting output

#### Scenario: List doctor checks
- **WHEN** an agent runs `fieldbook doctor --list-checks --json`
- **THEN** the system returns available check IDs, descriptions, default inclusion state, and severity

#### Scenario: Run selected doctor checks
- **WHEN** an agent supplies one or more `--check <id>` values
- **THEN** doctor runs only those checks and rejects unknown check IDs

### Requirement: Detect ledger integrity anomalies
The system SHALL detect common ledger drift and provenance anomalies.

#### Scenario: Detect invalid attrs JSON
- **WHEN** an attrs JSON column cannot decode to an object
- **THEN** doctor reports an `attrs.invalid_json` issue

#### Scenario: Scan all attrs JSON columns
- **WHEN** doctor runs the attrs JSON check
- **THEN** it scans experiments, runs, jobs, artifacts, notes, reconcile events, and sync events

#### Scenario: Detect dangling note entity
- **WHEN** a note references a missing or deleted entity row
- **THEN** doctor reports a `dangling.note_entity` issue

#### Scenario: Detect missing local artifact
- **WHEN** an artifact URI is a `file://` URI or bare local path and the target path does not exist
- **THEN** doctor reports an `artifact.local_missing` issue

#### Scenario: Detect unreadable local artifact
- **WHEN** an artifact URI is local and the target path exists but cannot be read
- **THEN** doctor reports an `artifact.local_unreadable` issue

#### Scenario: Skip remote artifacts
- **WHEN** an artifact URI uses `gs://`, `s3://`, `http://`, or `https://`
- **THEN** doctor skips filesystem existence checks for that artifact

#### Scenario: Detect stale active jobs
- **WHEN** a job status is queued or running, `updated_at` is older than the stale threshold, and no sync event with the same `job_id` was created within the threshold window
- **THEN** doctor reports a `job.stale_active` warning

#### Scenario: Detect active duplicate external IDs
- **WHEN** active runs or jobs share the same non-null `(external_system, external_id)` pair within the same entity table
- **THEN** doctor reports an `external_id.duplicate_active` error

#### Scenario: Detect archived duplicate external IDs
- **WHEN** archived rows share an external identifier with an active row
- **THEN** doctor reports an `external_id.duplicate_archived` warning

#### Scenario: Detect sync event entity issues
- **WHEN** a sync event references a soft-deleted run or job
- **THEN** doctor reports a `sync_event.dangling_entity` issue

#### Scenario: Detect sync idempotency collisions
- **WHEN** multiple sync events share target system, target identifier, and non-null idempotency key
- **THEN** doctor reports a `sync_event.duplicate_idempotency_key` warning

#### Scenario: Detect reconcile log anomalies
- **WHEN** a reconcile operation references a missing parent event or reconcile audit JSON cannot decode
- **THEN** doctor reports a `reconcile_log.anomaly` issue

#### Scenario: Do not flag zero-operation reconcile events
- **WHEN** a reconcile event has no operation rows but otherwise valid counts
- **THEN** doctor does not report a reconcile log anomaly for that event

### Requirement: Export full-ledger snapshots
The system SHALL create portable full-ledger snapshots.

#### Scenario: Export snapshot
- **WHEN** an agent runs `fieldbook snapshot export --output <path> --json`
- **THEN** the system writes a clean SQLite snapshot file and reports output path, metadata path, schema version, and table counts

#### Scenario: Export snapshot without WAL sidecars
- **WHEN** snapshot export succeeds
- **THEN** the exported SQLite file is complete without requiring `-wal` or `-shm` sidecars

#### Scenario: Export snapshot metadata
- **WHEN** snapshot export succeeds
- **THEN** the system writes metadata JSON with metadata version, exported timestamp, source ledger path, schema version, Fieldbook version, and table counts unless disabled

#### Scenario: Snapshot export refuses existing output
- **WHEN** the snapshot output already exists and `--replace` is not supplied
- **THEN** the command fails with a validation error

#### Scenario: Snapshot export can replace output
- **WHEN** the output exists and the agent supplies `--replace`
- **THEN** the command writes temporary sibling files, replaces the requested outputs, and reports success only after requested snapshot and metadata outputs are written

### Requirement: Inspect and import full-ledger snapshots
The system SHALL inspect and restore full-ledger snapshots safely.

#### Scenario: Inspect snapshot
- **WHEN** an agent runs `fieldbook snapshot inspect --input <path> --json`
- **THEN** the system opens the snapshot read-only and returns schema version, table counts, and metadata if sidecar metadata exists

#### Scenario: Inspect snapshot without metadata
- **WHEN** the snapshot metadata sidecar is absent
- **THEN** inspect returns snapshot metadata as null and does not fail solely because the sidecar is missing

#### Scenario: Reject non-SQLite snapshot input
- **WHEN** snapshot inspect or import receives a corrupt, empty, or non-SQLite input file
- **THEN** the command fails with a validation error

#### Scenario: Reject non-Fieldbook snapshot input
- **WHEN** snapshot inspect or import receives a SQLite database without a recognizable Fieldbook schema
- **THEN** the command fails with a validation error

#### Scenario: Import snapshot to new ledger
- **WHEN** an agent runs `fieldbook snapshot import --input <path> --output <path> --json`
- **THEN** the system creates a new ledger file from the snapshot and reports schema version and table counts

#### Scenario: Import refuses existing output
- **WHEN** the import output already exists and `--replace` is not supplied
- **THEN** the command fails with a validation error

#### Scenario: Import rejects newer schema
- **WHEN** the snapshot schema version is newer than the installed Fieldbook schema
- **THEN** the command fails with a validation error

#### Scenario: Import migrates older schema
- **WHEN** the snapshot schema version is older than the installed Fieldbook schema
- **THEN** the command applies local migrations after copying the snapshot

#### Scenario: Import migration failure leaves output untouched
- **WHEN** snapshot import fails while migrating a temporary destination
- **THEN** the requested output path remains untouched and the command exits with a validation error

#### Scenario: Import enables WAL
- **WHEN** snapshot import succeeds
- **THEN** the imported ledger has WAL mode enabled like a freshly initialized Fieldbook ledger

### Requirement: Document doctor and snapshot workflows
The system SHALL document agent-first audit and portability workflows.

#### Scenario: README includes doctor workflow
- **WHEN** an agent reads the README
- **THEN** it sees how to run doctor, inspect issue codes, and use stable views or reconcile logs for follow-up debugging

#### Scenario: README includes snapshot workflow
- **WHEN** an agent reads the README
- **THEN** it sees how to export, inspect, and import a full-ledger snapshot and the privacy warning

#### Scenario: Skill includes audit and portability guidance
- **WHEN** an agent uses the Fieldbook skill
- **THEN** it is told how to use doctor, snapshot, stable views, and reconcile logs during context recovery
