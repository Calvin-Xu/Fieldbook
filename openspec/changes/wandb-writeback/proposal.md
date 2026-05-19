## Why

Fieldbook is the source of truth for local experiment provenance, but W&B remains
the place collaborators often inspect training curves and summary metrics. A
common workflow is to train a model with a limited metric set, run follow-up
evals later, then want those follow-up metrics visible on the original W&B run.
Today Fieldbook can record that such a sync happened, but it cannot perform the
writeback itself.

## What Changes

- Add an explicit `fieldbook writeback wandb` workflow for opt-in W&B summary
  metric writes.
- Keep mirror/import workflows out of this phase; W&B reads continue to use the
  adapter + reconcile path.
- Extend sync-event provenance so writeback rows identify the exact source
  metric, target W&B summary field, payload summary, and event origin.
- Use dry-run planning by default; `--apply` is required for network side
  effects and ledger sync-event writes.
- Namespace W&B summary keys under `fieldbook/` by default to avoid clobbering
  training-run metrics.
- Add a writer protocol with a fake writer for default tests and optional real
  W&B writer behind an extra dependency.
- Add `fieldbook writeback log` plus a stable coverage view for writeback
  inspection.

## Capabilities

### New Capabilities

- `wandb-writeback`: Explicit, audited W&B summary writeback from Fieldbook
  metrics to target W&B runs.

### Modified Capabilities

None. The W&B writeback capability owns its new views and doctor checks; prior
capabilities remain available.

## Impact

- SQLite migration adding sync-event provenance columns and a W&B writeback
  coverage view.
- New `fieldbook writeback` CLI group.
- New optional W&B writer module and fake writer test boundary.
- README, query cookbook, and agent-skill updates for safe writeback usage.
