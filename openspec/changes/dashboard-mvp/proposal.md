## Why

Fieldbook's CLI and JSON surfaces are optimized for coding agents, but humans
and agents still need a fast visual overview of active experiments: what is
running, what is stale, which datapoints are missing, who owns monitoring, and
where the latest artifacts and handoffs live.

This phase adds a read-only local dashboard. It is intentionally not an admin
console and not an action surface. Mutations stay in Fieldbook CLI/reconcile
paths operated by coding agents.

## What Changes

- Add `fieldbook dashboard serve` for an on-demand localhost web dashboard.
- Bind to `127.0.0.1` by default with no background daemon or auto-start.
- Render pages from stable `_v1` views only.
- Provide experiment list, experiment detail, run progress, job recovery,
  advisory lease, validation, freshness, notes, artifact, and external-link
  views.
- Expose action affordances as copyable CLI commands or external links, not
  dashboard writes.

## Capabilities

### New Capability

- `dashboard-mvp`: read-only local dashboard for Fieldbook experiment status.

### Modified Capabilities

- `readonly-sql-stable-views`: add or document dashboard-required stable views.
- `agent-workflow`: document dashboard as a read-only companion to CLI-first
  agent workflows.
- `privacy-redaction`: dashboard uses redacted/safe view conventions where
  available and does not bypass them.

## Impact

- Adds a dashboard CLI group and lightweight local HTTP server dependencies if
  needed.
- Adds dashboard-specific tests for read-only routing and stable view usage.
- No write endpoints, daemon, scheduler, launcher, or background monitor are
  added.
