## Why

Fieldbook now tracks jobs, validations, refresh attempts, and agent sessions, but agents still have to infer whether local artifacts or validation evidence have drifted since the last useful checkpoint. This makes context switches fragile: a stale local dashboard, regenerated CSV, or outdated validation can look current in status/context even when the underlying file changed.

This phase adds explicit freshness discipline without adding a daemon, polling, or launcher wrapper. Agents can checkpoint an experiment, refresh local artifact metadata, and see bounded drift/staleness summaries in the resume surfaces.

## What Changes

- Stamp local-file artifacts with captured local mtime and size metadata.
- Add `fieldbook artifact refresh-local <artifact>` for updating local-file freshness metadata and, optionally, content hashes.
- Add `fieldbook experiment checkpoint <experiment>` to create a bounded Markdown checkpoint note, report freshness issues, and optionally archive the experiment.
- Add status/context freshness summaries for drifted artifacts, stale validations, and last checkpoint age.
- Add doctor checks for local artifact drift, validation source drift, and stale or absent experiment checkpoints.
- Extend refresh output to surface bounded local artifact drift when a refresh observes it.

## Capabilities

### New Capabilities

- `experiment-freshness`: checkpoint notes, local artifact drift detection, stale validation detection, and freshness blocks in agent resume surfaces.

### Modified Capabilities

- `doctor-audit-portability`: doctor warns about artifact and validation freshness risks.
- `markdown-notes-agent-context`: checkpoint notes are a first-class note type for bounded experiment summaries.
- `refresh-orchestration`: refresh output may include bounded local artifact drift evidence.

## Impact

- One SQLite migration may be needed only if freshness helpers require stable views; artifact metadata itself is stored in attrs.
- CLI additions under `artifact` and `experiment`.
- Status/context JSON shape changes because Fieldbook is pre-v1.
- README and Fieldbook agent skill updates for checkpoint and refresh-local workflows.
