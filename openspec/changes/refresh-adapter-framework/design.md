## Context

Research agents often return to an experiment after jobs or follow-up evals have finished elsewhere. They need a repeatable refresh path that captures external state without directly mutating the ledger. Fieldbook already has the correct write boundary: reconcile manifests. Adapters should produce those manifests from local snapshots and leave mutation to reconcile.

## Goals / Non-Goals

**Goals:**

- Keep adapters pure: input files plus adapter options produce manifest/debug outputs.
- Keep adapters stdlib-first and repo-agnostic.
- Support source-format adapters useful for Marin-style workflows without naming Marin in code.
- Make malformed rows debuggable without discarding the whole refresh when partial coverage is possible.
- Preserve the safety story: inspect manifest first, then reconcile explicitly.

**Non-Goals:**

- No live W&B, Iris, GCS, Slurm, or scheduler API calls.
- No direct database reads or writes from adapters.
- No one-shot `--apply`.
- No new reconcile manifest version in this phase.
- No dashboard UI.

## Decisions

### Decision: Adapters are pure translators

Adapters never open the Fieldbook ledger. They do not resolve IDs against the database. They emit fields that are already accepted by the existing reconcile manifest schema. If a source row lacks the identifiers required by reconcile, the adapter skips that row and records a row-level debug error.

This keeps adapters deterministic, easy to test, and safe to run before deciding whether to apply their output.

This also means some refreshes are intentionally two-pass. For example, an agent may run `wandb-runs-json`, apply the run manifest through reconcile, query `v_runs_v1` for ledger run IDs, and then run `metrics-csv` with those run IDs. Phase 3 does not add external-key resolution to reconcile.

### Decision: Adapter names describe source formats, not downstream projects

Code uses names such as `iris-jobs-json`, `wandb-runs-json`, `metrics-csv`, and `artifacts-json`. Marin is represented only through fixtures and README examples, not module names or core schema.

### Decision: Run and describe adapters through a small CLI

The CLI adds:

- `fieldbook adapter list`
- `fieldbook adapter describe <name>`
- `fieldbook adapter run <name> --input <path|-> --output <path|-> --debug-output <path|->`

`adapter describe` returns expected input shape, emitted manifest sections, required columns/fields, optional fields, coercion rules, and failure behavior. Text output is concise; `--json` returns machine-readable dictionaries for list/describe/run metadata.

`--input` and `--output` are required. `--debug-output` is optional. `-` means stdin for input and stdout for output. If both manifest output and debug output target stdout, the command rejects the invocation.

### Decision: Adapter outcomes distinguish hard failure from partial coverage

Adapters have three outcomes:

- hard parse failure: nonzero exit, no manifest, debug output if requested;
- partial coverage: exit zero, manifest contains valid rows, debug output records skipped rows;
- clean: exit zero, manifest contains valid rows, debug output records zero skipped rows.

The run result includes counts for input rows, emitted manifest rows by section, skipped rows, and debug output path when applicable.

`--strict` turns partial coverage into a validation error after writing debug output and before writing a manifest. This lets CI enforce clean refreshes while preserving the default agent-friendly partial mode.

### Decision: Supported MVP adapters

`iris-jobs-json` consumes pre-exported local JSON with a top-level list or `{ "jobs": [...] }`. Required fields per row: `external_id` and `status`. Optional fields include `id`, `run_id`, `experiment_id`, `name`, `command`, `launcher`, `failure_reason`, `started_at`, `finished_at`, and `attrs`. `status` must already be a Fieldbook job status. Timestamps must be UTC `Z` strings. It emits `jobs` rows with `external_system="iris"` plus `sync_events` rows for the Iris refresh.

`wandb-runs-json` consumes pre-exported local JSON with a top-level list or `{ "runs": [...] }`. Required fields per row: `external_id` or `id`, and `name`. Optional fields include `description`, `status`, `url`, `project`, `entity`, `state`, `summary`, and `attrs`. `status`, if supplied, must be a Fieldbook run status; W&B-specific state is stored in attrs. It emits `runs` rows with `external_system="wandb"` plus W&B sync events.

`metrics-csv` consumes UTF-8 comma-delimited CSV with a header row using Python `csv` module quoting rules. Required columns: `run_id`, `metric_name`, and `value`. Optional columns: `step`, `split`, `source_job_id`, and `source_artifact_id`. `value` must parse as a finite float. `step` remains a string because Fieldbook metric steps are strings. It emits `metrics` rows. It deliberately does not resolve run external identifiers; inputs must already include ledger run IDs.

`artifacts-json` consumes pre-exported local JSON with a top-level list or `{ "artifacts": [...] }`. Required fields per row: `type`, `uri`, and at least one of `experiment_id`, `run_id`, or `job_id`. Optional fields include `id`, `content_hash`, and `attrs`. It emits `artifacts` rows.

### Decision: Output is a normal reconcile manifest

Adapter output uses the existing manifest shape:

```json
{
  "manifest_version": 1,
  "runs": [],
  "jobs": [],
  "artifacts": [],
  "metrics": [],
  "notes": [],
  "custom_attributes": [],
  "sync_events": []
}
```

`manifest_version` is emitted for provenance but is compatible with current reconcile behavior, which ignores unknown top-level keys and reads the canonical sections. Entity `attrs` remain attached directly to the emitted row's `attrs` field; adapters do not flatten attrs into `custom_attributes`.

Sync events use the existing reconcile sync-event shape: `target_system`, `target_identifier`, `status`, optional `run_id`, optional `job_id`, optional `error_message`, optional `idempotency_key`, and optional `attrs`. Adapter-generated sync events use status `synced` for converted rows and deterministic idempotency keys derived from adapter name, target system, and target identifier.

Duplicate source rows are preserved in source order unless an adapter skips a malformed row. Reconcile remains responsible for idempotency, dedupe, and update/noop behavior. Manifest JSON is emitted with stable key ordering and stable source-row order.

Debug output is local diagnostic material. It includes source row payloads without redaction and should not be attached to public bug reports without review.

## Risks / Trade-offs

- **Risk: adapters feel less convenient without DB lookup** -> Accepted. Reconcile owns ID resolution and writes; adapters remain deterministic.
- **Risk: source schemas are too narrow** -> Mitigated by `adapter describe`, row-level debug, and fixtures that can evolve with real dogfood.
- **Risk: stdout/stderr confusion** -> `--output -` and `--debug-output -` cannot be used together.
- **Risk: W&B/Iris live integrations get requested later** -> Defer to a later optional phase with explicit dependencies and dry-run semantics.
