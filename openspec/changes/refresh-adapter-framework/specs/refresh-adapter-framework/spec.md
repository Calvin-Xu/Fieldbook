## ADDED Requirements

### Requirement: Register refresh adapters
The system SHALL expose available refresh adapters and their input contracts.

#### Scenario: List adapters
- **WHEN** an agent runs `fieldbook adapter list`
- **THEN** the system returns available adapter names and short descriptions

#### Scenario: Describe adapter
- **WHEN** an agent runs `fieldbook adapter describe <name>`
- **THEN** the system returns the adapter's expected input format, required fields, optional fields, coercion rules, emitted manifest sections, and failure behavior

#### Scenario: Describe adapter as JSON
- **WHEN** an agent runs `fieldbook adapter describe <name> --json`
- **THEN** the system returns the same contract as a machine-readable object

#### Scenario: Reject unknown adapter
- **WHEN** an agent references an unknown adapter name
- **THEN** the system rejects the command with a validation error

### Requirement: Run adapters as pure manifest producers
The system SHALL run adapters without reading or writing the Fieldbook ledger.

#### Scenario: Produce reconcile manifest
- **WHEN** an agent runs `fieldbook adapter run <name> --input <path> --output <path>`
- **THEN** the adapter reads the local input, writes a reconcile manifest, and does not open the ledger database

#### Scenario: Require explicit input and output
- **WHEN** an agent runs `fieldbook adapter run <name>` without `--input` or without `--output`
- **THEN** the system rejects the invocation with a validation error

#### Scenario: Do not apply adapter output
- **WHEN** an adapter run succeeds
- **THEN** no ledger rows change until an agent explicitly runs `fieldbook reconcile file`

#### Scenario: Emit canonical manifest sections
- **WHEN** an adapter writes a manifest
- **THEN** the manifest contains `manifest_version=1` and all canonical reconcile sections, using empty arrays for sections with no rows

#### Scenario: Preserve adapter row order
- **WHEN** an adapter writes a manifest from multiple valid source rows
- **THEN** emitted rows preserve source order and manifest keys are written deterministically

#### Scenario: Preserve row attrs on entity rows
- **WHEN** an adapter source row contains supported `attrs`
- **THEN** the adapter writes those attrs to the emitted row's `attrs` field and does not flatten them into `custom_attributes`

#### Scenario: Require two-pass ID workflow
- **WHEN** a source format needs ledger IDs for metrics or artifacts and only provides external run identifiers
- **THEN** the adapter skips those rows and records debug entries instead of querying the ledger or resolving external keys

### Requirement: Support adapter stdin and stdout
The system SHALL support pipe-friendly adapter input and output.

#### Scenario: Read input from stdin
- **WHEN** an agent passes `--input -`
- **THEN** the adapter reads its input from standard input

#### Scenario: Write manifest to stdout
- **WHEN** an agent passes `--output -`
- **THEN** the adapter writes the manifest JSON to standard output

#### Scenario: Reject conflicting stdout outputs
- **WHEN** an agent passes both `--output -` and `--debug-output -`
- **THEN** the system rejects the command with a validation error

### Requirement: Report adapter outcomes
The system SHALL distinguish clean, partial, and hard-failure adapter outcomes.

#### Scenario: Clean adapter run
- **WHEN** all input rows are valid
- **THEN** the adapter exits successfully, writes a manifest, and reports zero skipped rows

#### Scenario: Partial adapter run
- **WHEN** some input rows are malformed but others are valid
- **THEN** the adapter exits successfully, writes a manifest for valid rows, and records skipped-row debug entries

#### Scenario: Strict partial adapter run
- **WHEN** some input rows are malformed and the agent supplies `--strict`
- **THEN** the adapter exits with a validation error, writes debug output if requested, and writes no manifest

#### Scenario: Hard parse failure
- **WHEN** the input file cannot be parsed as the adapter's declared source format
- **THEN** the adapter exits nonzero, writes no manifest, and writes debug output if requested

#### Scenario: Debug row shape
- **WHEN** an adapter writes debug output
- **THEN** each debug entry contains input row index when available, severity, message, and source row payload when available

#### Scenario: Debug output is unredacted
- **WHEN** an adapter writes debug output
- **THEN** source row payloads are stored without redaction and documentation warns agents to treat debug output as local diagnostic material

#### Scenario: Preserve skipped-row source order
- **WHEN** an adapter records skipped-row debug entries
- **THEN** debug entries preserve source order and include stable row indexes when the input format has row boundaries

### Requirement: Transform Iris job summary JSON
The system SHALL transform pre-exported Iris job summary JSON into reconcile manifests.

#### Scenario: Convert Iris job row
- **WHEN** an input job row has `external_id` and `status`
- **THEN** the adapter emits a `jobs` row with `external_system="iris"` and the mapped job fields

#### Scenario: Reject unknown Iris status
- **WHEN** an Iris job row has a status outside Fieldbook's job status enum
- **THEN** the adapter skips that row and records a debug entry

#### Scenario: Reject invalid Iris timestamp
- **WHEN** an Iris job row has a non-UTC-Z `started_at` or `finished_at`
- **THEN** the adapter skips that row and records a debug entry

#### Scenario: Record Iris sync event
- **WHEN** an Iris job row is converted
- **THEN** the adapter emits a `sync_events` row recording the Iris refresh attempt

#### Scenario: Emit Iris sync event shape
- **WHEN** an Iris sync event is emitted
- **THEN** it includes `target_system`, `target_identifier`, `status`, optional entity identifiers when present, an optional error message, a deterministic `idempotency_key`, and optional `attrs`

#### Scenario: Skip malformed Iris row
- **WHEN** an Iris job row lacks required fields
- **THEN** the adapter skips that row and records a debug entry

### Requirement: Transform W&B run JSON
The system SHALL transform pre-exported W&B run metadata JSON into reconcile manifests.

#### Scenario: Convert W&B run row
- **WHEN** an input run row has a run identifier and name
- **THEN** the adapter emits a `runs` row with `external_system="wandb"` and the mapped run fields

#### Scenario: Preserve W&B metadata
- **WHEN** W&B input contains project, entity, URL, state, summary, or attrs
- **THEN** the adapter stores those values as namespaced attrs on the emitted run row

#### Scenario: Record W&B sync event
- **WHEN** a W&B run row is converted
- **THEN** the adapter emits a `sync_events` row recording the W&B refresh attempt

#### Scenario: Preserve W&B state as attrs
- **WHEN** W&B input contains a source-specific state
- **THEN** the adapter stores that state under a namespaced attrs key instead of treating it as Fieldbook run status

#### Scenario: Reject unknown W&B run status
- **WHEN** a W&B run row supplies a Fieldbook `status` outside Fieldbook's run status enum
- **THEN** the adapter skips that row and records a debug entry

### Requirement: Transform metrics CSV
The system SHALL transform local metric CSV snapshots into reconcile manifests.

#### Scenario: Convert metric row
- **WHEN** a CSV row has `run_id`, `metric_name`, and `value`
- **THEN** the adapter emits a `metrics` row with optional step, split, source job, and source artifact fields

#### Scenario: Preserve metric step as string
- **WHEN** a metric CSV row supplies `step`
- **THEN** the adapter emits the step as a string without numeric coercion

#### Scenario: Reject non-finite metric value
- **WHEN** a metric CSV row supplies NaN, infinity, or a non-numeric value
- **THEN** the adapter skips that row and records a debug entry

#### Scenario: Skip malformed metric row
- **WHEN** a metric row lacks required fields or has an invalid value
- **THEN** the adapter skips that row and records a debug entry

#### Scenario: Require ledger run IDs for metrics
- **WHEN** a metric source row only contains external run identifiers
- **THEN** the adapter skips that row and records a debug entry because Phase 3 adapters do not resolve external keys

### Requirement: Transform artifact JSON
The system SHALL transform local artifact JSON snapshots into reconcile manifests.

#### Scenario: Convert artifact row
- **WHEN** an artifact row has `type`, `uri`, and at least one owner identifier
- **THEN** the adapter emits an `artifacts` row

#### Scenario: Skip malformed artifact row
- **WHEN** an artifact row lacks type, URI, or owner identifier
- **THEN** the adapter skips that row and records a debug entry

### Requirement: Keep adapter output deterministic
The system SHALL make adapter output deterministic for the same input bytes and options.

#### Scenario: Preserve duplicate valid source rows
- **WHEN** a source file contains duplicate valid rows
- **THEN** the adapter emits duplicate manifest rows in source order and leaves idempotency handling to reconcile

#### Scenario: Stable JSON output
- **WHEN** an adapter writes JSON output
- **THEN** top-level and nested object keys are written in a stable order

### Requirement: Document adapter refresh workflow
The system SHALL guide agents toward adapter-to-reconcile workflows.

#### Scenario: README includes adapter example
- **WHEN** an agent reads the README
- **THEN** it sees an example that runs an adapter, inspects the manifest, and applies it with reconcile

#### Scenario: Skill includes adapter guidance
- **WHEN** an agent uses the Fieldbook skill
- **THEN** it is told that adapters never mutate the ledger and reconcile remains the only writer
