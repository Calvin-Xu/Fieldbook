## Context

Fieldbook is primarily consumed by coding agents. Its resume surface should answer whether recorded evidence is still current enough to trust before the agent resumes analysis, exports a packet, or archives an experiment.

The system should not poll in the background. Freshness checks are explicit and local: compare ledger-captured metadata with current filesystem metadata, compare validation timestamps with source artifact changes, and record bounded checkpoint notes.

## Goals / Non-Goals

**Goals:**

- Capture local file mtime and size on artifact add and refresh.
- Let agents update local-file artifact freshness deliberately.
- Provide checkpoint notes for end-of-session and archive discipline.
- Surface freshness summaries in `experiment status` and `experiment context`.
- Warn through doctor when artifacts drift, validations depend on changed artifacts, or experiments lack recent checkpoints.
- Keep refresh explicit and snapshot-backed while reporting drift observed during refresh.

**Non-Goals:**

- No daemon, polling, background job watcher, or automatic session-switch refresh.
- No direct SQL write escape hatch.
- No general privacy/redaction implementation; that is Phase 15.
- No content hashing by default for all local artifacts, because large files can be expensive to hash.

## Decisions

### Decision: Store freshness metadata in attrs

Artifact freshness metadata is stored in reserved attrs:

- `fieldbook.local_mtime_at_capture`: floating-point Unix timestamp as observed by `stat`.
- `fieldbook.local_size_at_capture`: integer byte size when available.
- `fieldbook.local_path_at_capture`: resolved local path used for the capture.

This avoids a schema migration for metadata that is meaningful only for local-file artifacts. Non-local artifact URIs such as `gs://`, `s3://`, `http://`, `https://`, and `wandb://` do not receive local freshness attrs.

The `fieldbook.*` namespace remains reserved for system-managed attrs. Agents
cannot set these keys through CLI `--attr` or reconcile attrs; repository code
stamps them internally after user attrs pass validation.

### Decision: Drift is advisory

Artifact drift means a local artifact's current mtime or size differs from the captured metadata. It is a warning, not a blocker. Agents can resolve it by running `artifact refresh-local`, re-running the producing workflow, or recording an erratum/checkpoint explaining why drift is acceptable.

### Decision: Validation freshness follows source artifacts

A validation with `source_artifact_id` is stale when the source artifact changed after the validation was recorded or when the source artifact has local drift. The validation remains active; doctor and status/context surface it so agents know to rerun or update the validation.

### Decision: Checkpoints are bounded notes

`experiment checkpoint <experiment>` writes a `checkpoint` note. The body is Markdown, capped by existing note body limits, and should summarize what changed, current blockers, unresolved actions, and freshness risks. The command returns the same freshness summary used by status/context.

Checkpoint accepts at most one body source: `--body`, `--body-file`, or
`--body-stdin`. If no body source is supplied, Fieldbook writes an
auto-generated Markdown checkpoint from the experiment summary and freshness
block. If a body source is supplied, Fieldbook appends the generated freshness
block beneath the provided Markdown.

`--archive` archives the experiment after writing the checkpoint. `--errata`
permits writing a checkpoint to an archived experiment as explicit post-archive
evidence after the Phase 12 errata amendment is implemented. `--archive
--errata` is allowed: on an active experiment the checkpoint is marked as
errata and then archives the experiment; on an already archived experiment
`--archive` is a no-op.

### Decision: Status/context expose compact freshness

Freshness blocks are bounded and machine-readable:

```json
{
  "drifted_artifact_count": 1,
  "stale_validation_count": 2,
  "last_checkpoint_at": "2026-05-21T10:00:00Z",
  "since_last_checkpoint_hours": 3.5,
  "checkpoint_status": "current | stale | missing"
}
```

Context may include a few drifted/stale examples; status should stay compact.

`checkpoint_status` uses `idle` for active experiments with no activity and no
checkpoint, `missing` for experiments with activity but no checkpoint, `stale`
for experiments whose latest checkpoint is older than the stale threshold, and
`current` otherwise.

Stale validation examples include `source_drifted: true|false` so agents can
distinguish source-row updates from local-file drift.

### Decision: Refresh only reports drift it observes

Refresh stays explicit and snapshot-backed. It does not mutate local artifact freshness metadata. When refresh runs, it may include bounded `drifted_artifacts` in its output so agents can decide whether to refresh metadata or rerun validations.

## Defaults

- Checkpoint stale threshold: 24 hours, overridable where the CLI exposes a stale threshold.
- Drifted artifact output limit: 20 rows.
- `artifact refresh-local` updates mtime, size, and resolved path by default; content hash updates only with `--update-hash`.
- Checkpoint notes use note type `checkpoint`, status `open`, and body format `markdown`.
- Missing local artifact files are reported as drift with `drift_kind=missing_file` and also remain eligible for existing missing-local-artifact doctor warnings.

## Risks / Trade-offs

- **Risk: mtime changes from harmless file touches** -> Treat drift as advisory and allow `artifact refresh-local`.
- **Risk: hashing large artifacts is expensive** -> Make hash updates opt-in.
- **Risk: status/context become noisy** -> Keep only counts and bounded examples.
- **Risk: errata checkpoints blur archive state** -> Require explicit `--errata`; archived experiments remain archived.
