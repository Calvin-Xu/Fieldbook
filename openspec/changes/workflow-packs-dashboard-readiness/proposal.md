## Why

Fieldbook now has the core ledger, reconcile, adapter, doctor, snapshot, SQL,
and W&B writeback surfaces needed before a dashboard. The remaining
pre-dashboard work should not add speculative orchestration. It should make the
agent workflows easier to repeat and define the minimum stable contract a later
dashboard can read.

Dogfood showed one concrete dashboard prerequisite: shared surfaces need
artifact locality/redaction so local filesystem provenance remains useful to
agents without leaking private paths in dashboards or collaborator payloads.

## What Changes

- Add read-only workflow-pack commands:
  - `fieldbook experiment triage`
  - `fieldbook experiment closeout-checklist`
- Add workflow recipe and template files for launch planning, eval refresh,
  failure triage, collaborator export, handoff, and closeout. These are
  scaffolds, not side-effecting commands.
- Add artifact URI locality classification and a redacted artifact view.
- Add dashboard-readiness docs that pin the minimum useful dashboard, UI entity
  to view mapping, sample queries, redaction rules, non-goals, and acceptance
  criteria for a later UI phase.
- Add tests that execute recipes/templates/sample queries against fixtures and
  guard committed examples against private path leakage.

## Capabilities

### New Capabilities

- `workflow-packs`: Read-only agent workflow summaries plus executable
  recipe/template scaffolds.
- `dashboard-readiness`: Artifact locality/redaction and a documented stable
  view contract for a future dashboard.

### Modified Capabilities

None.

## Impact

- New CLI subcommands under `fieldbook experiment`.
- SQLite migration adding artifact locality/redaction views.
- New docs and template files.
- Agent skill updates pointing to workflow recipes and dashboard contracts.
