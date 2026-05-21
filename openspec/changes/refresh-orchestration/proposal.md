## Why

Fieldbook adapters are intentionally pure: they transform local snapshots into reconcile manifests and never call Iris, W&B, GCS, or any downstream system. Dogfooding showed that agents still need a repeatable way to run the external snapshot command, store the raw snapshot, run the adapter, inspect or apply reconcile, and leave an audit trail. Phase 13 adds that orchestration layer without adding a daemon or making refresh implicit.

Phase 13 depends on the Phase 12 recovery and validation surfaces so refreshes can update job state, validations, and readiness without hiding failed or stale evidence.

Dogfooding also showed that agents can bypass Fieldbook entirely when launching experiments unless the agent skill makes Fieldbook the obvious first stop. This phase therefore updates the agent workflow docs with a launch protocol, but it does not add a launcher wrapper around Iris, W&B, GCS, or other external systems.

## What Changes

- Add explicit refresh commands: `fieldbook refresh list-sources`, `fieldbook refresh run`, and `fieldbook refresh log`.
- Add local refresh source configuration using `.fieldbook/refresh.toml` with stdlib parsing.
- Store raw snapshots under `.experiments/refresh-snapshots/<source>/<timestamp>.json`.
- Run external helper commands only when the agent explicitly asks for a source or passes a loud `--all`.
- Feed snapshots into pure adapters, then into reconcile dry-run or apply.
- Record `refresh_events` for dry-runs, applies, skipped refreshes, helper failures, adapter failures, and reconcile failures.
- Add `v_refresh_log_v1` for queryable refresh history.
- Add doctor checks for stale snapshots, failed refreshes, suspected secrets in snapshots, and refresh events with unapplied manifests.
- Update status/readiness surfaces after source-specific applied refreshes, because refresh manifests may update jobs and validations through reconcile.
- Update the Fieldbook agent skill with a launch protocol: `db where`, `session start`, `job add --status submitting`, external launcher, then `job update-status` to an acknowledged state or `unknown_submit`.
- Include submission-resolution information in refresh output when a source resolves or fails to resolve Phase 12 `submitting` / `unknown_submit` jobs.

## Capabilities

### New Capabilities

- `refresh-orchestration`: explicit external refresh workflow through snapshots, adapters, and reconcile.

### Modified Capabilities

- `refresh-adapter-framework`: adapters remain pure and are invoked by orchestration from local snapshots.
- `reconcile-core-hardening`: refresh apply uses reconcile as the only ledger mutation path.
- `doctor-audit-portability`: doctor gains refresh audit checks.

## Impact

- New migration, CLI commands, refresh config parser, event table, and tests.
- No daemon, no background polling, and no automatic refresh during session switch.
- No `fieldbook launch <external-system>` wrapper; launch discipline is a skill/workflow contract and job lifecycle records remain generic.
- Live external commands are opt-in, auditable, and snapshot-backed.
- Refresh outputs are local artifacts that can be replayed without re-querying external systems.
