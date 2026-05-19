## ADDED Requirements

### Requirement: Plan W&B summary writeback
The system SHALL plan W&B summary writes from Fieldbook metrics without external
side effects by default.

#### Scenario: Dry-run is default
- **WHEN** an agent runs `fieldbook writeback wandb --run <run> --metric <glob>`
- **THEN** the system returns a writeback plan, performs no network calls, and
  writes no sync-event rows

#### Scenario: Select metrics by glob
- **WHEN** an agent supplies one or more `--metric <glob>` patterns
- **THEN** the system selects non-deleted metrics on the source run whose names
  match at least one pattern

#### Scenario: Reject archived source run
- **WHEN** the source run is archived or deleted
- **THEN** the system exits with a validation error

#### Scenario: Reject empty metric selection
- **WHEN** no metrics match the supplied patterns
- **THEN** the system exits with a validation error

#### Scenario: Reject target-field collisions
- **WHEN** two selected source metrics would write to the same target W&B run and
  target summary field
- **THEN** the system rejects the plan with a validation error identifying the
  colliding source metric IDs

#### Scenario: Emit plan envelope
- **WHEN** the system emits JSON output
- **THEN** the envelope contains `envelope_version`, `dry_run`, `target_system`,
  `source_run_id`, `target_identifier`, `planned`, `skipped`, `errors`, and
  `summary`

### Requirement: Resolve target W&B run safely
The system SHALL resolve the target W&B run deterministically and guard against
mis-targeted writes.

#### Scenario: Use explicit target
- **WHEN** an agent supplies `--target-run <wandb-run-id>`
- **THEN** the system uses that W&B run identifier as the target

#### Scenario: Use source run W&B external ID
- **WHEN** no target is supplied and the source run has
  `external_system='wandb'` and `external_id`
- **THEN** the system uses the source run external ID as the target

#### Scenario: Use parent W&B external ID
- **WHEN** no target is supplied, the source run has a parent, and the parent run
  has `external_system='wandb'` and `external_id`
- **THEN** the system uses the parent external ID as the target

#### Scenario: Reject missing target
- **WHEN** no explicit, source, or parent W&B target can be resolved
- **THEN** the system exits with a validation error

#### Scenario: Guard explicit target mismatch
- **WHEN** the supplied target differs from the default target that would have
  been resolved from the source run or its parent
- **THEN** the system rejects apply unless `--force-target` is supplied

### Requirement: Apply W&B summary writeback explicitly
The system SHALL perform W&B network writes only when the agent explicitly
applies the plan.

#### Scenario: Apply writes
- **WHEN** an agent runs `fieldbook writeback wandb ... --apply`
- **THEN** the system writes the planned summary fields to the target W&B run
  and records one sync-event row per attempted write

#### Scenario: Apply requires explicit writer
- **WHEN** an agent runs `fieldbook writeback wandb ... --apply` without
  `--writer`
- **THEN** the system rejects the command with a validation error

#### Scenario: First write acknowledgement
- **WHEN** applying to a W&B target with no prior Fieldbook writeback sync-event
  rows
- **THEN** the system rejects apply unless `--first-write-ok` is supplied

#### Scenario: Dry-run reports first write guardrail
- **WHEN** a dry-run targets a W&B run with no prior Fieldbook writeback
  sync-event rows
- **THEN** the plan reports that `--first-write-ok` will be required for apply

#### Scenario: Summary-only write
- **WHEN** writeback applies
- **THEN** the system writes W&B summary fields only and does not write W&B
  history rows or upload W&B artifacts

#### Scenario: Write before audit insert
- **WHEN** writeback applies a metric
- **THEN** the system calls the writer before inserting the sync-event row for
  that metric

#### Scenario: Retry after crash before audit insert
- **WHEN** a previous process wrote the W&B summary value but crashed before
  inserting a sync-event row
- **THEN** a later apply with the same inputs plans the metric again and can
  record the sync event after rewriting the same summary value

#### Scenario: Fake writer
- **WHEN** an agent supplies `--writer fake`
- **THEN** the system uses the fake writer boundary and records deterministic
  success or requested failure behavior without requiring W&B credentials

#### Scenario: Real writer missing dependency
- **WHEN** an agent applies with the real writer and W&B support is unavailable
- **THEN** the system exits with a validation error explaining how to install
  the W&B extra

### Requirement: Namespace target fields by default
The system SHALL avoid clobbering existing W&B summary keys by default.

#### Scenario: Default field prefix
- **WHEN** a selected metric is named `eval/foo`
- **THEN** the default W&B summary field is `fieldbook/eval/foo`

#### Scenario: Custom field prefix
- **WHEN** an agent supplies `--key-prefix <prefix>`
- **THEN** the system writes target fields under that prefix

#### Scenario: Reject empty key prefix
- **WHEN** an agent supplies an empty `--key-prefix`
- **THEN** the system exits with a validation error and directs the agent to use
  `--raw-keys` if raw metric names are intended

#### Scenario: Normalize trailing prefix slash
- **WHEN** an agent supplies `--key-prefix fieldbook/`
- **THEN** the system writes target fields without a duplicated slash

#### Scenario: Reject raw keys with key prefix
- **WHEN** an agent supplies both `--raw-keys` and `--key-prefix`
- **THEN** the system exits with a validation error

#### Scenario: Raw keys require force
- **WHEN** an agent supplies `--raw-keys`
- **THEN** the system uses metric names as target fields and rejects apply
  unless `--force-target` is supplied

### Requirement: Enforce writeback idempotency
The system SHALL make repeated writeback applies safe by default.

#### Scenario: Skip already-synced metric
- **WHEN** an existing latest sync-event row with the same target and
  idempotency key has status `synced`
- **THEN** the planner skips that metric unless `--allow-rewrite` is supplied

#### Scenario: Retry failed metric
- **WHEN** an existing latest sync-event row with the same target and
  idempotency key has status `failed`, `skipped`, or `pending`
- **THEN** the planner treats the metric as retryable and plans a new write

#### Scenario: Allow rewrite
- **WHEN** an agent supplies `--allow-rewrite`
- **THEN** the planner plans a new write even if a prior `synced` row exists

#### Scenario: Source-anchored idempotency
- **WHEN** the planner creates an idempotency key
- **THEN** the key includes the source metric ID, target W&B run identifier, and
  target summary field

#### Scenario: Latest event ordering
- **WHEN** multiple sync-event rows have the same target and idempotency key
- **THEN** the planner chooses the latest row by `created_at DESC, id DESC`

#### Scenario: Preserve manifest idempotency uniqueness
- **WHEN** manifest-origin sync events have the same target and idempotency key
- **THEN** the database preserves the manifest uniqueness contract and rejects
  duplicates

#### Scenario: Allow writeback retry history
- **WHEN** writeback-origin sync events have the same target and idempotency key
- **THEN** the database permits multiple rows so failed attempts and retries
  remain auditable

### Requirement: Record writeback provenance
The system SHALL record queryable provenance for every applied write attempt.

#### Scenario: Record successful write
- **WHEN** a W&B summary write succeeds
- **THEN** the system inserts a sync-event row with `target_system='wandb'`,
  `origin='writeback'`, `status='synced'`, source run ID, source metric ID,
  target identifier, target field, idempotency key, and payload summary

#### Scenario: Record failed write
- **WHEN** a W&B summary write fails
- **THEN** the system inserts a sync-event row with `status='failed'`, the same
  provenance fields, and a sanitized error message

#### Scenario: Preserve failed history
- **WHEN** a failed write is retried
- **THEN** the old failed row remains in the ledger and the retry creates a new
  sync-event row

#### Scenario: Distinguish manifest and writeback origins
- **WHEN** sync events are inserted through reconcile manifests
- **THEN** they default to `origin='manifest'`

#### Scenario: Reject manifest writeback origin
- **WHEN** a reconcile manifest attempts to insert a sync event with
  `origin='writeback'`
- **THEN** reconcile rejects that row with a validation error

### Requirement: Inspect W&B writeback history
The system SHALL expose W&B writeback history through CLI and stable SQL views.

#### Scenario: Writeback log
- **WHEN** an agent runs `fieldbook writeback log --target-system wandb`
- **THEN** the system returns sync-event rows with writeback provenance and
  supports filters for target system, status, run, target identifier, origin,
  and source entity ID

#### Scenario: Stable writeback coverage view
- **WHEN** a ledger is migrated to this phase
- **THEN** it contains `v_wandb_writeback_coverage_v1` with one latest row per
  source metric and target field

#### Scenario: Existing sync coverage remains available
- **WHEN** the ledger is migrated to this phase
- **THEN** the existing `v_wandb_sync_coverage_v1` view remains available

### Requirement: Sanitize stored and displayed errors
The system SHALL redact credentials and common secrets from writeback errors.

#### Scenario: Redact bearer token
- **WHEN** a writer failure includes an authorization bearer value
- **THEN** the stored and displayed error replaces the sensitive value with a
  redacted marker

### Requirement: Check writeback audit health
The system SHALL report writeback audit anomalies through doctor.

#### Scenario: Report failed writeback events
- **WHEN** doctor sees failed writeback sync-event rows older than the configured
  stale threshold
- **THEN** it reports them as writeback items needing attention

#### Scenario: Do not warn on writeback retry keys
- **WHEN** doctor sees multiple writeback sync-event rows with the same
  idempotency key
- **THEN** it does not warn merely because retries preserved attempt history

#### Scenario: Redact API key patterns
- **WHEN** a writer failure includes common API-key or secret patterns
- **THEN** the stored and displayed error replaces those values with redacted
  markers

### Requirement: Document writeback safety
The system SHALL document W&B writeback as an explicit opt-in mirror target.

#### Scenario: README documents dry-run and apply
- **WHEN** an agent reads the README
- **THEN** it explains dry-run default, explicit `--apply`, namespaced keys, and
  first-write acknowledgement

#### Scenario: Agent skill documents safe workflow
- **WHEN** an agent reads the Fieldbook skill
- **THEN** it directs agents to dry-run first, inspect the plan, apply only on
  explicit user intent, and treat Fieldbook as source of truth
