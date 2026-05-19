## Context

Fieldbook currently exposes structured CLI commands for common workflows, but agents often need ad hoc joins, coverage checks, and dashboard queries. Letting agents read SQLite directly is valuable, but only if reads are safe, bounded, and pointed at a compatibility layer rather than internal tables.

## Goals / Non-Goals

**Goals:**

- Give agents a safe read-only SQL command for local ledger inspection.
- Make SQL output deterministic and scriptable.
- Provide versioned views as the stable public query contract.
- Keep Fieldbook portable and stdlib-first.
- Prevent accidental writes, runaway queries, and oversized outputs.

**Non-Goals:**

- No SQL write escape hatch.
- No dashboard UI.
- No general migration tooling for view deprecation beyond `_v1` naming.
- No automatic SQL query builder.
- No live W&B/Iris/GCS access in this phase.

## Decisions

### Decision: Read-only SQL uses layered SQLite safety controls

`fieldbook sql` opens the ledger through a URI using `mode=ro` and `uri=True`. It also enables `PRAGMA query_only=ON`, sets a read-only authorizer, rejects multiple statements, and rejects non-readonly statements before execution where Python's sqlite3 APIs make that practical.

The authorizer denies writes and side-effecting operations including `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `REINDEX`, `VACUUM`, `ANALYZE`, `ATTACH`, `DETACH`, and transaction control. User SQL cannot run PRAGMA statements at all in this phase; agents should inspect schema through stable views and `sqlite_schema` reads. `load_extension` is rejected even inside `SELECT`.

This is intentionally stricter than raw SQLite `mode=ro`; the contract is "safe ledger reads", not arbitrary SQLite execution.

### Decision: SQL execution is bounded

Default row limit is 1,000. The executor fetches `limit + 1` rows, returns at most `limit`, and sets `truncated=true` if the extra row exists. It does not promise total row counts.

`--limit <n>` changes the row limit. `--no-limit` disables the row-count cap but does not disable the output-size cap or timeout. The command also enforces:

- default timeout: 15 seconds;
- default maximum output bytes: 10 MiB;
- a progress handler so runaway recursive CTEs are interrupted;
- a structured validation error if the query is interrupted or output would exceed the cap.

`--no-limit` remains because it is in the approved phase plan, but docs warn agents to prefer explicit limits.

Phase 2 materializes query results before emitting JSON, NDJSON, or CSV. The output cap is checked against the serialized bytes before printing. This cap prevents oversized command output, but it is not a general memory-safety guarantee for arbitrary unlimited queries; agents should keep limits explicit unless they are exporting deliberately.

### Decision: SQL can come from an argument, file, or stdin

`fieldbook sql` accepts exactly one of:

- `--query <sql>`;
- `--file <path>`;
- `--stdin`.

This avoids shell-quoting failures for multiline queries while keeping command behavior explicit.

### Decision: JSON is the primary machine contract

Default SQL output format is JSON. The JSON envelope is:

```json
{
  "envelope_version": 1,
  "columns": [{"name": "run_id", "decltype": null, "first_row_type": "text"}],
  "rows": [{"run_id": "run_..."}],
  "row_count": 1,
  "truncated": false
}
```

`columns` is ordered exactly as returned by SQLite. Named fields are the contract; callers should not depend on implicit table column order outside view definitions.

NDJSON uses three record types:

- first line: `{"type":"meta","envelope_version":1,"columns":[...],"truncated":false}`;
- row lines: `{"type":"row","values":[...]}`;
- final line: `{"type":"end","row_count":N,"truncated":bool}`.

CSV writes a normal UTF-8 header row and row data to stdout using Python `csv` module quoting rules. CSV metadata is written to stderr as one JSON line containing `envelope_version`, `columns`, `row_count`, and `truncated`.

### Decision: Type mapping is explicit

SQLite values map as follows:

- `NULL` -> JSON `null` and empty CSV cell;
- `INTEGER` within JavaScript safe integer range -> JSON number;
- `INTEGER` outside `[-2^53, 2^53]` -> JSON string;
- finite `REAL` -> JSON number;
- non-finite `REAL` -> validation error;
- `TEXT` -> JSON string; JSON-looking text is not auto-parsed;
- `BLOB` -> validation error unless `--allow-blobs` is supplied, in which case it is base64 text with column type `blob_base64`.

### Decision: Views are the compatibility contract

Tables are internal. Versioned views are public. Phase 2 creates these views:

- `v_experiments_v1`
- `v_runs_v1`
- `v_jobs_v1`
- `v_artifacts_v1`
- `v_metrics_long_v1`
- `v_experiment_summary_v1`
- `v_run_summary_v1`
- `v_jobs_needing_attention_v1`
- `v_artifact_latest_per_type_v1`
- `v_metric_coverage_v1`
- `v_wandb_sync_coverage_v1`
- `v_reconcile_log_v1`

View column names are contractual. `SELECT *` order is stable for each `_v1` view and tested, but consumers should prefer named columns. Breaking changes require a new `_v2` view to live alongside `_v1`.

Views filter soft-deleted rows by default. Opinionated views freeze their selection criteria:

- `v_jobs_needing_attention_v1`: non-deleted jobs with status `queued`, `running`, or `failed`;
- `v_artifact_latest_per_type_v1`: one latest non-deleted artifact per `(experiment_id, run_id, job_id, type)` partition, based on `updated_at DESC, id DESC`; `NULL` partition keys are coalesced to empty strings for grouping so unset run/job/experiment dimensions group deterministically;
- `v_metric_coverage_v1`: per experiment and metric name, number of non-deleted runs with at least one non-deleted metric row over total non-deleted experiment runs;
- `v_wandb_sync_coverage_v1`: non-deleted run rows backed by `runs.external_system`, `runs.external_id`, and `sync_events` rows where `target_system='wandb'`, intended to identify which tracked runs have W&B provenance or sync evidence;
- `v_reconcile_log_v1`: one row per `reconcile_events` row, joined to `reconcile_operations` for operation count and stable counts.

### Decision: `fieldbook db path` is minimal in this phase

`fieldbook db path` resolves the same ledger discovery rules as other commands and returns `{"path": "<absolute path>"}` in JSON mode. A richer `db info` command can be added later if dogfood shows repeated need.

## Risks / Trade-offs

- **Risk: SQLite authorizer coverage is subtle** -> Mitigate with explicit tests for writes, ATTACH/DETACH, PRAGMA writes, and `load_extension`.
- **Risk: timeout tests are flaky** -> Use deterministic recursive CTE/progress-handler tests with a short timeout.
- **Risk: views ossify bad columns** -> Accept for `_v1`; add `_v2` instead of mutating contracts.
- **Risk: `--no-limit` causes huge outputs** -> Keep independent max-output-bytes cap and docs warning.
- **Risk: CSV metadata on stderr surprises humans** -> Document it; JSON remains the primary agent format.
