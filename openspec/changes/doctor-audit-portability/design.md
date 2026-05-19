## Context

Fieldbook is now useful enough that ledger drift becomes the next operational risk. Agents may resume an experiment after many manual actions, adapter runs, or reconcile attempts. Before exporting collaborator data or handing work off, the agent should be able to ask: is this ledger internally consistent, are there stale jobs, and are local artifact pointers still readable?

Portability has several possible meanings. Phase 4 deliberately supports the safest MVP: full-ledger SQLite snapshots. This solves moving/sharing one complete ledger and avoids the much harder merge semantics of scoped logical imports.

## Decisions

### Decision: `doctor` is read-only

`fieldbook doctor` opens the ledger read-only and never writes fixes. It reports stable issue codes and enough context for an agent to inspect with SQL or prepare a reconcile manifest. This avoids introducing a second write path.

Doctor requires the ledger to already be at the installed Fieldbook schema version. It uses SQLite `mode=ro` plus `PRAGMA query_only=ON`, checks `PRAGMA user_version`, and fails with `schema.version_mismatch` if the ledger is older or newer than the installed schema. It does not run migrations because that would violate the read-only contract. A user should run a normal write-capable command such as `fieldbook init --ledger <path>` to migrate an older ledger before doctor.

If another writer holds the ledger, doctor uses SQLite's normal busy timeout and exits with the existing ledger-busy code on lock contention.

### Decision: Doctor issues use stable codes and severities

Doctor output has an envelope with `envelope_version`, `generated_at`, `ledger`, `schema_version`, `ok`, `issue_count`, and `issues`. Each issue has:

- `code`: stable dotted code such as `dangling.note_entity`;
- `severity`: `error` or `warning`;
- `entity_type` and `entity_id` when applicable;
- `message`;
- `details` object;
- `suggested_next_action`.

Default exit behavior is zero if there are no `error` issues and nonzero if errors exist. `--strict` escalates warnings to failure. Text output is compact; `--json` preserves all details.

Any failing doctor condition uses `ExitCode.VALIDATION_ERROR` except lock contention, which uses `ExitCode.LEDGER_BUSY`.

### Decision: Doctor checks are individually selectable

`fieldbook doctor --list-checks` lists check IDs. `fieldbook doctor --check <id>` can be repeated. The MVP checks are:

- `attrs-json`: invalid JSON in `attrs_json` columns;
- `note-entity`: notes pointing at missing or deleted entities;
- `local-artifacts`: artifacts with `file://` URIs or bare local paths that are missing or unreadable;
- `stale-jobs`: queued/running jobs with `updated_at < now - --stale-hours` and no sync event for that job created inside the same threshold window;
- `external-ids`: duplicate active external identifiers for runs/jobs, plus active-vs-archived reuse warnings for the same external identifier;
- `sync-events`: sync events pointing at soft-deleted runs or jobs, plus duplicate non-null idempotency keys;
- `reconcile-log`: reconcile operation rows without parent events, and invalid JSON in reconcile event/operation audit columns.

Foreign-key-enforced relationships are not duplicated as doctor checks unless the relationship is intentionally loose, such as notes. `sync-events` does not report missing run/job rows because those are FK-enforced; it only reports soft-deleted referenced entities and idempotency anomalies.

All MVP checks are enabled by default. `--list-checks --json` returns objects with `id`, `description`, `default_enabled`, and `severity`.

`attrs-json` scans `attrs_json` on `experiments`, `runs`, `jobs`, `artifacts`, `notes`, `reconcile_events`, and `sync_events`. Values must decode to JSON objects, not arrays or scalars.

`local-artifacts` treats `file://` URIs and paths without a URI scheme as local. Bare paths are resolved relative to the current working directory. `~` is expanded. Cloud and HTTP(S) URIs are skipped.

`reconcile-log` explicitly does not flag zero-operation reconcile events, since an empty manifest reconcile is a valid no-op audit record.

### Decision: Full-ledger snapshot is the portability MVP

`fieldbook snapshot export --output <path>` creates a clean SQLite snapshot using SQLite backup semantics from a read-only connection. The resulting single `.sqlite` file is checkpointed and does not require `-wal` or `-shm` sidecars. It also writes a sidecar metadata JSON file by default at `<path>.metadata.json` containing `metadata_version`, `exported_at`, `source_ledger`, `schema_version`, `fieldbook_version`, and table counts.

`fieldbook snapshot inspect --input <path>` opens the snapshot read-only and returns metadata plus table counts and schema version.

`fieldbook snapshot import --input <path> --output <path>` creates a new ledger file from a snapshot. It refuses to overwrite an existing destination unless `--replace` is supplied. It runs migrations after import if the snapshot schema is older than the installed Fieldbook schema and rejects snapshots newer than the installed schema.

Snapshot includes all tables at the logical SQLite level: active rows, archived rows, notes, artifacts, metrics, reconcile history, sync events, and operation audit data. No scoped merge is supported in Phase 4. If users need collaborator tables, they should use existing metric exports; if they need a full ledger, they should share a snapshot.

Export and import write to temporary sibling files and then use `os.replace`. The crash contract is best-effort: a crash may leave temporary files, and after replacing the snapshot but before replacing metadata there may be a fresh snapshot with stale or missing metadata; the implementation must not report success unless both requested outputs are written. Import writes and migrates a temporary destination first; if migration fails, the target output is left untouched and the temporary file is removed when possible. Imported ledgers are put into WAL mode like `fieldbook init`.

Snapshot commands validate that input files are SQLite databases with a recognizable Fieldbook schema, using `PRAGMA user_version` and expected core tables. Non-SQLite or non-Fieldbook inputs fail with validation errors.

### Decision: Snapshot privacy is explicit

Snapshots include notes, artifacts, sync events, and local paths. The commands and documentation warn that snapshots can include sensitive provenance and should be reviewed before sharing. Redaction is deferred.

## Risks / Trade-offs

- Doctor does not fix issues automatically. This is intentional to preserve the single write boundary.
- Full-ledger snapshots are less flexible than scoped exports, but they avoid merge/id collision semantics.
- Local artifact checks are environment-dependent; they are limited to `file://` and bare local paths and skip cloud/HTTP URIs.
- `stale-jobs` can be noisy for intentionally long-running jobs; agents can tune `--stale-hours` or select specific checks.
