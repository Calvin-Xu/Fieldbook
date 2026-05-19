## 1. Specification And Review

- [x] 1.1 Run CC ideation review before drafting spec.
- [x] 1.2 Draft proposal, design, specs, and tasks for `readonly-sql-stable-views`.
- [x] 1.3 Validate the OpenSpec change.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Commit and push the reviewed spec.

## 2. Tests First

- [x] 2.1 Add failing migration tests for stable view creation and view column contracts.
- [x] 2.2 Add failing CLI tests for `fieldbook db path`.
- [x] 2.3 Add failing SQL output tests for JSON envelope, NDJSON, CSV, truncation, and column metadata.
- [x] 2.4 Add failing SQL safety tests for writes, DDL, ATTACH/DETACH, PRAGMA writes, load_extension, multiple statements, timeout, and output-size caps.
- [x] 2.5 Add failing SQL type-mapping tests for NULL, large INTEGER, REAL, TEXT, BLOB, and multiline CSV-safe text.

## 3. Schema And Views

- [x] 3.1 Add migration `006_stable_views.sql` and bump schema version.
- [x] 3.2 Create all required `v_*_v1` views with explicit column lists.
- [x] 3.3 Add tests proving soft-deleted rows are filtered by default.
- [x] 3.4 Add tests proving underlying table-column additions do not change view outputs.

## 4. SQL Execution Layer

- [x] 4.1 Add read-only ledger opening with URI `mode=ro`, `PRAGMA query_only=ON`, and bounded busy timeout.
- [x] 4.2 Add SQLite authorizer denying writes, DDL, ATTACH/DETACH, side-effecting PRAGMAs, transaction control, and extension loading.
- [x] 4.3 Add single-statement validation and query source handling for `--query`, `--file`, and `--stdin`.
- [x] 4.4 Add progress-handler timeout and output-byte cap.
- [x] 4.5 Add `limit + 1` truncation semantics with default limit 1,000, `--limit`, and `--no-limit`.
- [x] 4.6 Add deterministic SQLite-to-JSON/CSV type mapping and optional `--allow-blobs`.

## 5. CLI, Docs, And Skill

- [x] 5.1 Add `fieldbook db path`.
- [x] 5.2 Add `fieldbook sql` with `--format json|ndjson|csv`, `--query`, `--file`, `--stdin`, `--limit`, `--no-limit`, `--timeout`, `--max-output-bytes`, and `--allow-blobs`.
- [x] 5.3 Update README with query examples, stable-view contract, safety limits, and output examples.
- [x] 5.4 Update the Fieldbook agent skill with view-first SQL guidance and warnings against direct table dependencies.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC risk checks and rerun validation.
- [x] 6.4 Commit and push the implementation.
