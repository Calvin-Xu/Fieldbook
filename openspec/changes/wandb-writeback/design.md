## Context

Fieldbook already has a `sync_events` table. Previous phases use it as an audit
surface for externally observed syncs, especially through reconcile manifests.
Phase 6 is different: Fieldbook will initiate an external side effect by writing
selected Fieldbook metrics into W&B run summaries.

The safe design is therefore not a general "W&B integration". It is a narrow,
explicit, auditable push path.

## Goals / Non-Goals

**Goals:**

- Support explicit writeback of Fieldbook scalar metrics to W&B summary fields.
- Keep Fieldbook as source of truth; W&B is a mirror target.
- Make dry-run planning the default and network side effects opt-in.
- Record idempotent sync events for every applied write attempt.
- Preserve source metric provenance and target-field provenance in queryable
  columns.
- Keep W&B optional; default installs and tests must not import live W&B.

**Non-Goals:**

- No W&B mirror/import direction in this phase.
- No automatic writeback when metrics are added.
- No W&B history writes via `run.log`.
- No W&B artifact upload.
- No project-level writeback config file.
- No live W&B calls in the default test suite.

## Decisions

### Decision: This phase implements writeback only, not mirror

W&B reads are already possible through a local export plus
`wandb-runs-json`/reconcile. Adding a live W&B mirror would expand the adapter
surface, credential handling, and partial-failure semantics. Phase 6 only pushes
Fieldbook metrics to W&B summaries.

### Decision: `sync_events` remains the audit table

The migration adds queryable provenance columns to `sync_events`:

- `origin`: `manifest` or `writeback`;
- `source_entity_type`: `metric`;
- `source_entity_id`;
- `target_field`;
- `payload_summary_json`.

Manifest-created sync events default to `origin='manifest'`. Fieldbook-created
writeback events use `origin='writeback'`. This avoids a second audit table
while letting stable views distinguish observed external syncs from Fieldbook
side effects.

Reconcile manifests may not create `origin='writeback'` rows. The writeback
origin means Fieldbook executed the side effect through the writeback command,
not that an agent reported a side effect in a manifest.

### Decision: Writeback is summary-only

`fieldbook writeback wandb` writes W&B summary keys. It does not call
`run.log`, because W&B history writes are not naturally idempotent: reruns
append duplicate points. Summary overwrite behavior is easier to reason about
and fits follow-up eval metrics.

### Decision: Dry-run plans do not mutate the ledger

Dry-run output contains planned writes, skipped existing writes, and validation
errors. It performs no network call and inserts no `sync_events` rows. `--apply`
performs the network writes and inserts one sync-event row per attempted write
with status `synced`, `failed`, or `skipped`.

`pending` remains reserved for future asynchronous writeback and is not emitted
by Phase 6 code.

### Decision: Idempotency is source-anchored

The logical idempotency key is stored in `sync_events.idempotency_key`:

`wandb-summary:<source_metric_id>:<target_identifier>:<target_field>`

If the same Fieldbook metric is recomputed and should be resent, the agent must
use `--allow-rewrite`. A changed metric value alone does not force a resend.
This makes repeated `--apply` safe by default.

Planner behavior:

- existing latest `synced` row with the same key: skip unless `--allow-rewrite`;
- existing latest `failed`, `skipped`, or `pending` row: retry by inserting a new
  row on apply;
- no existing row: plan a new write.

Failed rows remain in history. Retries insert new rows instead of mutating old
rows.

Existing manifest sync-event idempotency keeps its uniqueness guarantee, but
writeback retries require multiple rows with the same logical idempotency key.
The migration therefore replaces the current unique sync-event idempotency index
with a manifest-only unique partial index:

`UNIQUE(target_system, COALESCE(target_identifier, ''), idempotency_key) WHERE origin='manifest' AND idempotency_key IS NOT NULL`

Writeback idempotency is enforced by the planner. The planner determines the
latest row for a key by `created_at DESC, id DESC`. Doctor does not warn on
duplicate writeback idempotency keys; it still warns on duplicate manifest keys
if direct SQL or import drift violates the manifest uniqueness contract.

### Decision: Source run and target W&B run are distinct

For follow-up evals, the metric may belong to a child Fieldbook run while the
target W&B run is the original training run. `sync_events.run_id` is therefore
the source run that produced the metric. `target_identifier` is the W&B run ID
being updated. The optional `--target-run` flag can override the default target.

Default target resolution:

- if `--target-run` is supplied, use it;
- else if the source run has `external_system='wandb'`, use its `external_id`;
- else if the source run has `parent_run_id` and the parent run has
  `external_system='wandb'`, use the parent `external_id`;
- otherwise fail validation.

If the caller supplies a target that differs from the default resolved target,
the command requires `--force-target`. This applies whether the default came
from the source run or its parent.

### Decision: Summary keys are namespaced by default

The default target field is `fieldbook/<metric_name>`, preserving slash-delimited
metric names. `--key-prefix <prefix>` changes the prefix. `--raw-keys` disables
the prefix and requires `--force-target` because it may overwrite training-run
summary keys.

The planner rejects a plan where two selected source metrics would write to the
same `(target_identifier, target_field)`. Agents must narrow the metric
selection or use a disambiguating prefix before applying. This prevents
order-dependent W&B summary overwrites when a run has multiple rows with the
same metric name but different step, split, source job, or source artifact.

### Decision: First write to a W&B target requires acknowledgement

If the ledger has no prior `origin='writeback'` sync-event rows for a target W&B
run, `--apply` requires `--first-write-ok`. Dry-run reports the guardrail but
does not fail. This catches wrong-run accidents before the first external side
effect.

### Decision: W&B is optional and abstracted behind a writer protocol

Core Fieldbook imports no W&B library at startup. Applying writeback requires an
explicit writer selection; there is no destructive-path default. The CLI uses a
`WandbSummaryWriter` protocol:

- `FakeWandbSummaryWriter` for tests and local fake apply;
- `RealWandbSummaryWriter` loaded only when the user applies with
  `--writer real`.

If real W&B support is unavailable, the command exits with a validation error
that tells the user to install Fieldbook with the W&B extra. Credentials are
read by W&B from its normal environment; Fieldbook stores no W&B API keys.

### Decision: Error messages are sanitized before storage

Failures store concise redacted errors. Tokens, bearer headers, passwords,
secrets, and common cloud/API key patterns are stripped before insertion into
`sync_events.error_message`.

## Risks / Trade-offs

- **Risk: summary overwrites still mutate external state** -> Mitigate with
  dry-run default, namespacing, first-write acknowledgement, and idempotency.
- **Risk: optional dependency is annoying** -> Accepted to keep Fieldbook
  portable and lightweight.
- **Risk: source-anchored idempotency hides recomputed values** -> Mitigate with
  explicit `--allow-rewrite`; this is safer than accidental repeated writes.
- **Risk: target resolution is surprising** -> Document the child-to-parent
  convention and surface it in dry-run output.
- **Risk: W&B failures leak credentials** -> Sanitize errors before storing or
  printing.

### Decision: Write first, then record the sync event

Apply executes one selected metric at a time. For each metric, Fieldbook calls
the writer first and then records the resulting sync event. If the process
crashes after a successful W&B write but before the sync-event insert, a later
retry will write the same summary value again and then record the event. This is
preferable to recording `synced` before an external side effect occurs.
