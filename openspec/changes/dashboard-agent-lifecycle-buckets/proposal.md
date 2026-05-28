## Why

The dashboard's `Stale` bucket is not a useful experiment lifecycle state for
coding agents. Handoff freshness is important context, but it does not answer
the primary dashboard question: "what should an agent or human do with this
experiment now?"

This phase replaces the `Stale` lifecycle bucket with rule-derived agent
lifecycle buckets that distinguish active work, actionable blockers, reviewable
outputs, dormant open experiments, and archived history.

This phase depends on Phase 20 `dashboard-agent-prompts`; it extends the
dashboard summary view and closed prompt catalog introduced there.

## What Changes

- Replace the dashboard index groups with `Needs attention`, `In progress`,
  `Review`, `Open`, and `Archived`.
- Keep handoff freshness as a badge/detail and prompt action, not as a
  lifecycle bucket.
- Add rule-derived review state: an experiment is in `Review` when reviewable
  activity is newer than the latest explicit review marker.
- Represent review markers as auditable ledger records, not hidden dashboard
  state.
- Add a small CLI command to record review completion through a structured
  `review` note.
- Preserve the read-only dashboard contract: no dashboard writes or mark-review
  buttons.

## Capabilities

### New Capability

- `dashboard-agent-lifecycle-buckets`: agent-oriented dashboard lifecycle
  grouping and review markers.

### Modified Capabilities

- `dashboard-mvp`: replace stale grouping with lifecycle grouping.
- `dashboard-agent-prompts`: prompt applicability uses lifecycle/review state
  rather than raw historical failures or missing handoffs.
- `agent-workflow`: document how agents consume reviewable outputs and record
  review completion.
- `readonly-sql-stable-views`: add lifecycle/review columns to stable dashboard
  views.

## Impact

- Adds dashboard summary columns for lifecycle state, reviewable activity, and
  review markers.
- Adds tests for bucket precedence and review marker behavior.
- Adds `fieldbook experiment mark-reviewed` as an audited CLI write.
- Does not add dashboard write routes, daemon behavior, background polling,
  implicit archiving, or opaque per-agent UI state.
