## Context

Fieldbook's source of truth is SQLite plus stable read-only views. The CLI is
the primary interface for coding agents, but a read-only dashboard can make
experiment state easier to scan while preserving the agent-operated model.

The dashboard must not become the place where experiment state is edited. If a
user wants action, the dashboard should show a CLI command or external link and
let the coding agent execute the appropriate workflow.

## Goals / Non-Goals

**Goals:**

- Provide a local read-only overview of active Fieldbook experiments.
- Make run/datapoint progress, job recovery state, validation readiness,
  freshness, advisory lease ownership, notes, artifacts, and external links
  easy to inspect.
- Use stable `_v1` views as the dashboard data contract.
- Keep the server on-demand and localhost-bound by default.

**Non-Goals:**

- No write endpoints, forms that mutate state, or dashboard actions.
- No daemon, auto-start, scheduler, launcher, or background monitor.
- No authentication beyond localhost-only default binding.
- No direct reads from internal tables in dashboard handlers.
- No Marin-specific dashboard core dependency.

## Decisions

### Decision: On-demand local server

`fieldbook dashboard serve` starts a foreground HTTP server. It binds to
`127.0.0.1` by default on port `8765`. A non-local host requires an explicit
flag. Stopping the process stops the dashboard. The server handles SIGINT and
SIGTERM with clean shutdown and does not write PID files, auto-restart, watch
files, or auto-reload.

The MVP uses the Python standard library HTTP server stack with simple
server-rendered templates to keep Fieldbook portable. A later phase may change
the server framework if the dashboard requirements outgrow this.

### Decision: Read-only routing

The dashboard exposes GET-only routes. There are no POST, PUT, PATCH, or DELETE
routes. Every page is a read-only projection of the ledger.

### Decision: Stable views are the data contract

Dashboard handlers query `_v1` stable views, not internal tables. Any missing
aggregate needed by the dashboard should be added as a stable view during this
phase rather than embedded as a bespoke dashboard-only join.

### Decision: Actions are commands, not buttons

The dashboard may show copyable commands such as `fieldbook experiment
workloop <experiment> --refresh <source> --apply`, or links to W&B/Iris/GCS.
It does not execute those actions.

## Initial Pages

- Experiment index with active/stale/archived grouping.
- Experiment detail with progress, health, freshness, ownership, and latest
  handoff/checkpoint.
- Run/datapoint matrix progress with missing checkpoint/eval/metric coverage.
- Job recovery view with retries, recovered failures, and blockers.
- Lease ownership view with active owners, stale heartbeats, expired leases,
  and force-takeover history.
- Artifact and validation summaries with drift/staleness indicators.

The MVP may render these as sections on the index and experiment detail pages
rather than as separate routes. The required routes are index and experiment
detail; additional pages are optional if they remain read-only.

Experiment index grouping uses these definitions:

- archived: experiment is archived/deleted;
- needing attention: active blockers, failed validation, failed job needing
  recovery, or invalid lease state;
- stale: stale checkpoint, stale refresh, or stale lease heartbeat without a
  stronger needing-attention reason;
- active: open experiment not in another group.

If the resolved ledger path does not exist, `dashboard serve` exits with the
same non-init ledger-not-found error as other non-init commands.

Privacy/redaction behavior initially matches the stable `_v1` views the
dashboard reads. When the privacy-redaction phase lands, dashboard pages should
move to redacted/safe views where available without adding dashboard-specific
redaction logic.

## Risks / Trade-offs

- **Risk: dashboard becomes admin UI** -> Restrict routes to GET and show CLI
  commands for actions.
- **Risk: duplicated query logic** -> Enforce `_v1` view usage in tests.
- **Risk: unsafe sharing** -> Bind to localhost by default and use redacted
  view conventions.
- **Risk: framework sprawl** -> Keep dependencies minimal and portable.
