## Why

Fieldbook now has enough write paths, read-only SQL, reconcile logs, and adapters that agents need a fast way to audit ledger health before trusting a resumed experiment. Agents also need a safe way to move or share a complete ledger without hand-copying WAL sidecar files or losing schema/provenance context.

## What Changes

- Add `fieldbook doctor` as a read-only ledger health checker with stable issue codes, JSON/text output, check selection, stale-job thresholds, and CI-friendly exit behavior.
- Add full-ledger portability commands that export, inspect, and import clean SQLite snapshot files. The MVP portability path is full-ledger only; scoped logical merge/import is deferred.
- Add query cookbook and Fieldbook skill guidance for doctor, reconcile logs, stable SQL views, and snapshots.

## Capabilities

### New Capabilities

- `doctor-audit-portability`: Read-only ledger health checks and full-ledger snapshot export/import.

### Modified Capabilities

- Agent documentation explains how to debug a returned experiment with `doctor`, `reconcile log`, stable views, and snapshots.

## Out Of Scope

- No dashboard UI.
- No automatic repair command or direct SQL write escape hatch.
- No live W&B/Iris/GCS refresh.
- No scoped logical merge/import between existing ledgers.
- No artifact tarball bundling.
