## Context

The intended context-switch workflow is manual but disciplined:

1. save context on the current experiment;
2. switch to another experiment;
3. refresh external job/eval state only when needed;
4. reconcile the resulting state into Fieldbook;
5. inspect readiness and continue.

Existing adapters solve step 4 only when a local snapshot already exists. Phase 13 adds steps 3 through 5 as a single explicit command path while preserving the adapter safety boundary.

The launch side is deliberately handled as a workflow recipe, not a Fieldbook wrapper. A generic ledger cannot safely know every downstream scheduler, but it can make the correct protocol agent-obvious: record the job as `submitting`, run the external launcher, then resolve the job to `queued`, `running`, `failed`, or `unknown_submit` depending on the external acknowledgment.

## Goals / Non-Goals

**Goals:**

- Make refresh explicit, reproducible, and auditable.
- Store raw external snapshots before translating them.
- Keep adapters pure snapshot-to-manifest translators.
- Keep reconcile as the only writer to experiments, runs, jobs, artifacts, metrics, notes, and validations.
- Support source-specific helper commands without importing downstream repos into Fieldbook core.
- Make refresh failures resumable and debuggable.
- Make the external-job launch protocol explicit in the Fieldbook agent skill so agents use the ledger before, not after, live submissions.
- Let refresh outputs help resolve Phase 12 submission uncertainty.

**Non-Goals:**

- No daemon, scheduler, cron, background polling, or automatic refresh on session switch.
- No direct adapter writes to SQLite.
- No implicit `--all` refresh.
- No live W&B summary writeback; that remains the W&B phase.
- No `fieldbook launch iris`, `fieldbook launch wandb`, or other scheduler-specific launch wrappers.
- No dashboard UI.
- No hard dependency on Marin, Iris, W&B, GCS, or `uv`.

## Decisions

### Decision: Refresh orchestration owns external commands

Adapters stay pure. The refresh orchestrator owns:

- reading source config;
- running an external helper command when configured;
- writing the raw snapshot;
- invoking the named adapter on that snapshot;
- writing the reconcile manifest and adapter debug output;
- optionally applying reconcile;
- recording a refresh event.

This keeps external side effects in one CLI surface and makes adapter tests deterministic.

### Decision: Use `.fieldbook/refresh.toml`

Use TOML because Python 3.11 includes `tomllib` for parsing. The config is discovered relative to the resolved ledger root unless `--config` is supplied.

Example shape:

```toml
[sources.iris_jobs]
adapter = "iris-jobs-json"
kind = "command"
command = ["uv", "run", "python", "scripts/export_iris_jobs.py", "--experiment", "{experiment_id}"]
description = "Export Iris job summaries for the active experiment."

[sources.metrics_csv]
adapter = "metrics-csv"
kind = "file"
path = "artifacts/latest_metrics.csv"
description = "Import a local metrics CSV snapshot."
```

`kind="command"` sources run a command and capture stdout as the snapshot. `kind="file"` sources copy an existing file into the snapshot directory. Fieldbook does not interpret source-specific command arguments beyond simple documented placeholders.

### Decision: Require explicit source selection

`fieldbook refresh run --source <name>` is the default path. `--all` is allowed but must be explicit and is reported loudly in output. Running refresh without `--source` or `--all` is a validation error.

Session switch remains fast and does not refresh automatically.

### Decision: Store snapshots and derived files under `.experiments`

Refresh writes:

- `.experiments/refresh-snapshots/<source>/<timestamp>.json`
- `.experiments/refresh-snapshots/<source>/<timestamp>.manifest.json`
- `.experiments/refresh-snapshots/<source>/<timestamp>.debug.json`

Snapshots are local diagnostic artifacts. They may contain external metadata and should be git-ignored unless a downstream repo explicitly opts into tracking sanitized fixtures.

### Decision: Dry-run is the default

`fieldbook refresh run --source <name>` runs the source, writes snapshot and manifest files, runs reconcile dry-run, records a refresh event with status `dry_run`, and does not mutate entity rows.

`--apply` applies reconcile and records status `applied` if all steps succeed. Helper, adapter, and reconcile failures record failed refresh events with stable failure stage labels.

### Decision: Refresh events are separate from sync events

`sync_events` describe interactions with external systems at the row/entity level. `refresh_events` describe one orchestration attempt. A refresh event stores:

- source name;
- experiment ID when supplied;
- session ID when current;
- status;
- stage;
- started/finished timestamps;
- snapshot path;
- manifest path;
- debug path;
- reconcile event ID when applied;
- counts JSON;
- command argv JSON when configured;
- error message;
- attrs JSON.

This makes refresh-level failures visible even when no reconcile event exists.

### Decision: Helper failure stops before adapter/reconcile

If the external helper exits nonzero, Fieldbook records the snapshot if any output was captured, records a failed refresh event, and does not run the adapter or reconcile.

If the adapter fails, Fieldbook records the adapter debug output if available and does not run reconcile.

If reconcile dry-run fails, Fieldbook records the failure and leaves entity rows unchanged.

### Decision: Refresh can create validation rows indirectly

The refresh orchestrator does not compute coverage. Source helpers or adapters may emit validations into the reconcile manifest. Those validations are applied through reconcile like any other rows.

After `fieldbook refresh run --source <name> --apply`, status and context surfaces reflect the updated job and validation state from that source because applied refreshes use reconcile synchronously before returning.

### Decision: Refresh source ordering stays agent-controlled

Fieldbook does not model dependencies between refresh sources in Phase 13. Repos can document multi-source workflows such as "refresh Iris jobs, then refresh GCS artifacts" in README, skills, or local runbooks. Agents should run those sources in the documented order and use `experiment status` after each applied source when the order matters.

### Decision: Launch protocol lives in skills, not core commands

Fieldbook should not prevent downstream agents from running `iris`, `wandb`, `gcloud`, shell scripts, or repo-specific launchers directly. Instead, the Fieldbook skill documents a launch protocol that makes ledger recording the path of least resistance:

1. `fieldbook db where` to confirm ledger identity.
2. `fieldbook session start` or `fieldbook session switch` to bind the agent's work to an experiment.
3. `fieldbook job add --status submitting --command ... --external-system ...` before invoking the external launcher.
4. Run the external launcher.
5. Update the job to an acknowledged execution state with the external identifier, or to `unknown_submit` if submission outcome is ambiguous, or to `failed` if the external system explicitly rejected it.
6. Later, run `fieldbook refresh run --source <name> --apply` to reconcile external state and validations.

This avoids brittle scheduler wrappers while still addressing the dogfood failure where Fieldbook was remembered only after a launch problem occurred.

### Decision: Refresh reports submission resolutions

Refresh manifests may update jobs in `submitting` or `unknown_submit` to acknowledged execution states or terminal failures. Refresh output should surface these cases in a `submission_resolutions` section so agents can see whether an ambiguous submission was resolved, remains unknown, or should be resubmitted/marked failed.

Each `submission_resolutions` entry has stable fields:

- `job_id`
- `previous_status` (`submitting` or `unknown_submit`)
- `resolved_status` (acknowledged execution state, `failed`, or `unknown_submit` when still ambiguous)
- `external_system`
- `external_id`, when newly assigned or already known
- `suggested_action`, one of `none`, `resubmit`, `mark_failed`, or `wait`

This is output derived from the generated manifest and/or reconcile result. It is not a new mutation path; changes still apply only through reconcile.

## Defaults

- Default result is dry-run.
- Default snapshot directory is under the resolved ledger root.
- Default command timeout is finite and configurable per source.
- Default config path is `.fieldbook/refresh.toml`.
- Default refresh log limit is 20 newest events.
- Default doctor stale snapshot warning threshold is 30 days.
- Unknown source names fail with a validation error.

## Risks / Trade-offs

- **Risk: refresh becomes a brittle Marin-specific wrapper.** Mitigated by source config and pure adapters; Fieldbook core only understands commands, files, snapshots, adapters, and reconcile.
- **Risk: snapshots contain sensitive data.** Mitigated by storing them locally under `.experiments`, documenting privacy expectations, warning on suspected secret patterns in doctor, and recording artifacts only when agents choose to.
- **Risk: agents accidentally refresh too much.** Mitigated by requiring `--source` or explicit `--all`.
- **Risk: dry-run events clutter logs.** Accepted. Dry-run audit is useful for agent accountability and can be filtered in `refresh log`.
- **Risk: agents still bypass Fieldbook before launch.** Mitigated by the launch-protocol skill, Phase 12 submission states, and refresh output that makes ambiguous submissions easier to recover when recorded in Fieldbook than when left only in chat or markdown.
