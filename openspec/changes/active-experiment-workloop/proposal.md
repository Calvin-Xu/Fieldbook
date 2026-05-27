## Why

Fieldbook now has the core primitives needed for agent-operated experiment
tracking: sessions, status/context, refresh, validations, freshness, and
run/datapoint progress. Marin dogfood showed that the remaining failure mode is
operational adoption. Agents can use Fieldbook correctly, but they often skip it
unless the user explicitly asks.

This phase adds a small active-experiment workloop that makes the expected
sequence obvious and low-friction: confirm ledger locality, choose the active
experiment, refresh external state when configured, show scoped health, surface
only actionable issues, and checkpoint before context switches.

The workloop preserves Fieldbook's boundary: Fieldbook records and guides
agent work, but it does not enforce ownership, schedule background work, launch
jobs, monitor clusters, or replace external systems of execution.

## What Changes

- Add an agent-facing `fieldbook experiment workloop` command that composes
  existing read/refresh/checkpoint surfaces without becoming a daemon,
  scheduler, launcher, or monitor.
- Add experiment-scoped doctor output so active work is not swamped by archived
  or unrelated ledger history.
- Add low-friction cleanup actions for stale recovered debug notes and
  superseded validations, with explicit dry-run/apply behavior.
- Add refresh/checkpoint guidance that agents can run at context-switch
  boundaries.
- Update the Fieldbook skill and README so active experiment checks start with
  the workloop rather than ad hoc `status` plus manual doctor calls.

## Capabilities

### New Capabilities

- `active-experiment-workloop`: an agent-facing workflow command for resuming,
  refreshing, triaging, and checkpointing one experiment.

### Modified Capabilities

- `doctor-audit-portability`: add experiment-scoped issue filtering and
  actionable defaults for active experiments.
- `refresh-orchestration`: allow workloop to invoke configured refresh sources
  explicitly and report dry-run/apply status.
- `agent-workflow`: update skill/docs so agents start with Fieldbook for active
  experiment work.

## Impact

- New CLI subcommand under `fieldbook experiment`.
- No schema migration expected unless implementation finds a need for stable
  workloop event views.
- README, Fieldbook skill, and workflow recipe updates.
- Tests focused on bounded JSON/text output, scoped doctor behavior, dry-run
  defaults, explicit apply semantics, and non-interference with archived
  history.
