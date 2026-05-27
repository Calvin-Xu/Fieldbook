## Why

Fieldbook is increasingly used by multiple coding agents across long-running
ML experiments. Agents can already record jobs, runs, notes, validations, and
refreshes, but the ledger does not yet answer a key coordination question:
which agent currently owns monitoring or follow-up for a job, run, or
experiment?

The goal is not to make Fieldbook a scheduler, daemon, job launcher, or global
lock manager. The goal is to make agent ownership visible and auditable so
long-running babysit loops and parallel agents avoid duplicate retries and
leave useful handoffs.

## What Changes

- Add generic advisory leases for `experiment`, `run`, and `job` entities.
- Add CLI commands for claim, heartbeat, release, list, and show.
- Support explicit expired takeover and force takeover with audit history.
- Store babysitter observations in lease attrs or later observation records,
  never as authoritative job status.
- Surface active, stale, expired, and force-taken-over leases in status,
  workloop, doctor, and stable read views.
- Update the agent skill and README so babysit loops claim ownership before
  monitoring and release or hand off ownership when stopping.

## Capabilities

### New Capability

- `advisory-leases-and-monitors`: advisory ownership and monitoring handoff
  records for agent-operated experiments.

### Modified Capabilities

- `agent-workflow`: active experiment status and workloop include ownership
  summaries and stale monitor warnings.
- `doctor-audit-portability`: doctor reports stale, expired, orphaned, and
  session-outliving leases.
- `readonly-sql-stable-views`: stable views expose active lease and lease
  history state for agents and dashboards.
- `job-recovery-validations`: retry depth remains derived from job retry
  lineage, not lease counters.

## Impact

- Adds one migration for leases, lease indexes, and stable lease views.
- Adds a top-level `fieldbook lease` CLI group.
- No daemon, scheduler, launcher wrapper, cluster monitor, or hard ownership
  enforcement is added.
- Dashboard prerequisites are improved, but dashboard UI is deferred to the
  next phase.
