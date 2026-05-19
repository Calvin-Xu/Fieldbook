## ADDED Requirements

### Requirement: Locate the active ledger path
The system SHALL expose the resolved ledger path through the CLI.

#### Scenario: Show discovered database path
- **WHEN** an agent runs `fieldbook db path`
- **THEN** the system resolves the ledger using the same discovery rules as other commands and returns the absolute path

#### Scenario: Respect explicit ledger overrides
- **WHEN** an agent runs `fieldbook db path --ledger <path>` or with `FIELDBOOK_LEDGER`
- **THEN** the returned path reflects that override and the ledger must already exist

### Requirement: Execute read-only SQL safely
The system SHALL provide a bounded SQL read command that cannot mutate the ledger or attached databases.

#### Scenario: Run a read-only query
- **WHEN** an agent runs `fieldbook sql --query "SELECT ..."`
- **THEN** the system opens the ledger read-only, executes exactly one read-only statement, and returns query results

#### Scenario: Resolve SQL ledger path
- **WHEN** an agent runs `fieldbook sql` with `--ledger`, `FIELDBOOK_LEDGER`, or normal upward discovery
- **THEN** the system uses the same ledger-discovery rules as other non-init commands and requires the ledger to already exist

#### Scenario: Reject write statements
- **WHEN** SQL attempts `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `REINDEX`, `VACUUM`, `ANALYZE`, or another write/DDL operation
- **THEN** the system rejects the query with a validation error before mutating any database

#### Scenario: Reject attach and detach
- **WHEN** SQL attempts `ATTACH` or `DETACH`
- **THEN** the system rejects the query with a validation error

#### Scenario: Reject pragma
- **WHEN** SQL attempts any PRAGMA statement
- **THEN** the system rejects the query with a validation error

#### Scenario: Reject extension loading
- **WHEN** SQL calls `load_extension` or otherwise attempts extension loading
- **THEN** the system rejects the query with a validation error

#### Scenario: Reject multiple statements
- **WHEN** SQL contains more than one statement
- **THEN** the system rejects the query with a validation error

### Requirement: Bound SQL execution
The system SHALL prevent runaway SQL reads and oversized outputs.

#### Scenario: Default limit
- **WHEN** an agent runs `fieldbook sql` without limit flags
- **THEN** the system returns at most 1,000 rows and sets `truncated=true` if more rows were available

#### Scenario: Default timeout
- **WHEN** an agent runs `fieldbook sql` without timeout flags
- **THEN** the system applies a 15-second timeout

#### Scenario: Custom timeout
- **WHEN** an agent supplies `--timeout <seconds>`
- **THEN** the system applies that timeout for query execution

#### Scenario: Default output cap
- **WHEN** an agent runs `fieldbook sql` without output-size flags
- **THEN** the system rejects serialized output larger than 10 MiB

#### Scenario: Custom output cap
- **WHEN** an agent supplies `--max-output-bytes <n>`
- **THEN** the system rejects serialized output larger than `n` bytes

#### Scenario: Custom limit
- **WHEN** an agent supplies `--limit <n>`
- **THEN** the system returns at most `n` rows and uses `limit + 1` probing to set `truncated`

#### Scenario: No row limit
- **WHEN** an agent supplies `--no-limit`
- **THEN** the system does not apply a row-count cap but still enforces timeout and output-size caps

#### Scenario: Timeout runaway query
- **WHEN** a read-only query exceeds the configured timeout
- **THEN** the system interrupts the query and exits with a structured validation error

#### Scenario: Reject oversized output
- **WHEN** serialized output would exceed the configured maximum output bytes
- **THEN** the system rejects the query with a structured validation error

#### Scenario: Materialize before emitting
- **WHEN** SQL output is JSON, NDJSON, or CSV
- **THEN** the system materializes the selected rows, serializes the requested output, verifies the output-size cap, and only then writes output

### Requirement: Accept explicit SQL input sources
The system SHALL accept exactly one SQL text source.

#### Scenario: Query from argument
- **WHEN** an agent supplies `--query`
- **THEN** the system uses that SQL text

#### Scenario: Query from file
- **WHEN** an agent supplies `--file`
- **THEN** the system reads SQL text from that file

#### Scenario: Query from stdin
- **WHEN** an agent supplies `--stdin`
- **THEN** the system reads SQL text from standard input

#### Scenario: Reject ambiguous SQL source
- **WHEN** an agent supplies zero SQL sources or multiple SQL sources
- **THEN** the system rejects the command with a validation error

### Requirement: Emit stable SQL output formats
The system SHALL emit deterministic JSON, NDJSON, and CSV query outputs.

#### Scenario: JSON envelope output
- **WHEN** SQL output format is `json`
- **THEN** the system emits an envelope with `envelope_version`, `rows`, `row_count`, `columns`, and `truncated`

#### Scenario: NDJSON output
- **WHEN** SQL output format is `ndjson`
- **THEN** the system emits a meta record, row records, and an end record with row count and truncation status

#### Scenario: CSV output
- **WHEN** SQL output format is `csv`
- **THEN** the system emits a header row and CSV data rows on stdout and emits metadata JSON including column metadata on stderr

#### Scenario: Column metadata
- **WHEN** the system emits JSON or NDJSON metadata
- **THEN** each column includes name, declared type when available, and first-row value type when available

#### Scenario: Empty-result column metadata
- **WHEN** a query returns zero rows
- **THEN** the system still emits column names and declared types where available, with `first_row_type=null`

### Requirement: Map SQLite values deterministically
The system SHALL convert SQLite result values to JSON/NDJSON/CSV values consistently.

#### Scenario: Preserve nulls and text
- **WHEN** a row contains NULL or TEXT
- **THEN** NULL is emitted as JSON null and TEXT is emitted as a string without auto-parsing JSON-looking text

#### Scenario: Preserve safe integers
- **WHEN** an INTEGER value is within JavaScript safe integer bounds
- **THEN** it is emitted as a JSON number

#### Scenario: Stringify large integers
- **WHEN** an INTEGER value is outside JavaScript safe integer bounds
- **THEN** it is emitted as a JSON string

#### Scenario: Reject non-finite real values
- **WHEN** a REAL value is NaN or positive/negative infinity
- **THEN** the system rejects the output with a validation error

#### Scenario: Reject blobs by default
- **WHEN** a result includes BLOB data and `--allow-blobs` is not supplied
- **THEN** the system rejects the output with a validation error

#### Scenario: Encode blobs explicitly
- **WHEN** a result includes BLOB data and `--allow-blobs` is supplied
- **THEN** the BLOB is base64 encoded and marked as blob-derived in column metadata

### Requirement: Provide versioned stable views
The system SHALL expose public query views with `_v1` suffixes and explicit column contracts.

#### Scenario: Create required views
- **WHEN** a ledger is migrated to this phase
- **THEN** it contains `v_experiments_v1`, `v_runs_v1`, `v_jobs_v1`, `v_artifacts_v1`, `v_metrics_long_v1`, `v_experiment_summary_v1`, `v_run_summary_v1`, `v_jobs_needing_attention_v1`, `v_artifact_latest_per_type_v1`, `v_metric_coverage_v1`, `v_wandb_sync_coverage_v1`, and `v_reconcile_log_v1`

#### Scenario: Filter soft-deleted rows
- **WHEN** an agent queries a stable view
- **THEN** soft-deleted rows are excluded unless the view explicitly documents otherwise

#### Scenario: Keep view columns stable
- **WHEN** an internal table gains an unrelated column
- **THEN** the `_v1` view column names and order do not change

#### Scenario: Create new version for breaking change
- **WHEN** a future change would remove or rename a public view column
- **THEN** the system creates a new `_v2` view instead of mutating the `_v1` contract

### Requirement: Document SQL and view contracts for agents
The system SHALL guide agents toward safe and portable SQL usage.

#### Scenario: README describes stable views
- **WHEN** an agent reads the README
- **THEN** it learns that views are the public SQL contract and tables are internal

#### Scenario: Skill describes SQL workflow
- **WHEN** an agent uses the Fieldbook skill
- **THEN** it is instructed to prefer stable views, keep limits explicit, and avoid direct SQL writes
