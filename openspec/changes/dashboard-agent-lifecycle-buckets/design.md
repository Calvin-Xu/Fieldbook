## Design

### Lifecycle Buckets

The dashboard index uses a deterministic single-assignment rule hierarchy:

1. `archived`: experiment is archived or deleted.
2. `needs_attention`: an agent-actionable problem exists now.
3. `in_progress`: work is currently running or recovery is underway.
4. `review`: reviewable activity exists after the latest review marker.
5. `open`: no active work, no actionable blocker, and no pending review.

This is intentionally rule-derived. Coding agents affect lifecycle by recording
facts in the ledger: job states, validations, artifacts, notes, handoffs, and
review markers. The dashboard does not maintain private UI state.

`In progress` intentionally has precedence over `Review`: if new outputs exist
while jobs are still running, the experiment remains operationally active. The
dashboard should still render a pending-review badge so completed partial
outputs are visible without hiding the running state.

### Actionable Issues

`Needs attention` is reserved for conditions that require intervention:

- blocking failed jobs;
- failing validations;
- stale submissions;
- stale advisory leases.

Recovery-in-progress failures do not enter `Needs attention` unless they become
stale or blocking. They belong in `In progress` because an active retry is
already the current work.

### In Progress

An experiment is `In progress` when it has active jobs, active leases, or
recovery-in-progress failures. Active jobs include `queued`, `running`,
`submitting`, and `unknown_submit`. Submission/lease staleness still escalates
to `Needs attention` by rule precedence.

### Reviewable Activity

An experiment is `Review` when the ledger has evidence that a human or coding
agent should inspect outputs or decide the next step. Reviewable activity is
the maximum timestamp across settled/reviewable events:

- terminal jobs, with `finished_at` preferred over `updated_at`;
- recovered failed jobs;
- experiment artifacts;
- experiment validations;
- experiment notes with `note_type IN ('next-action', 'debug', 'research',
  'decision')`.

Reviewable activity explicitly excludes `checkpoint`, `handoff`, and `review`
notes. Handoff freshness is separate from lifecycle, and review notes are
review markers rather than new review work.

The rule is:

```
pending_review = newest_reviewable_activity_at IS NOT NULL
  AND (
    last_reviewed_at IS NULL
    OR newest_reviewable_activity_at > last_reviewed_at
  )
```

This conservative rule may put broad research/theory experiments into `Review`
when new notes or artifacts appear. The correct way to consume the review is to
write an explicit review marker.

### Review Markers

Review markers are dedicated `review` notes on the experiment:

- `note_type='review'`;
- title defaults to `Experiment reviewed`;
- attrs include `fieldbook.review=true` and `fieldbook.reviewed_at=<UTC Z>`;
- body is Markdown supplied by the agent/human, or a bounded default summary.

The latest active review note's `created_at` determines `last_reviewed_at`.
`fieldbook.reviewed_at` is stamped to the same UTC timestamp for JSON consumers
and audit clarity. A review marker must not mutate jobs, validations, runs,
artifacts, handoffs, or leases. It only records that the current reviewable
state was inspected.

### Handoff Freshness

Handoff freshness remains visible as a chip/detail and prompt action:

- `handoff_status=idle|missing|stale|current`;
- `last_handoff_at`;
- `since_last_handoff_hours`.

It no longer controls the dashboard lifecycle bucket. Missing/stale handoffs
should prompt the agent to write a handoff before context switching, but they
do not imply an experiment lifecycle state by themselves.

### Stable View Contract

`v_dashboard_experiments_v1` exposes:

- `lifecycle_state`;
- `last_reviewed_at`;
- `last_reviewable_activity_at`;
- `has_pending_review`;
- `handoff_status`;
- existing actionability counts.

Dashboard handlers and prompt builders compute lifecycle from this stable view
rather than joining internal tables directly.

Canonical `lifecycle_state` tokens are `needs_attention`, `in_progress`,
`review`, `open`, and `archived`. Dashboard labels are display formatting only.

### Prompt Action

This phase adds a `review-outputs` prompt action to the existing closed prompt
catalog. It is applicable when `lifecycle_state='review'`, coexists with
`review-open-notes`, and points the coding agent at the experiment workloop or
context so it can inspect outputs and then record a review marker.

### Dependency

This change depends on Phase 20 `dashboard-agent-prompts`: dashboard summary
columns for actionability/handoff status, schema-aware dashboard rendering, and
the closed prompt catalog must land first. This phase extends those surfaces.

### Scope Boundaries

This phase does not add:

- dashboard write endpoints;
- manual UI drag/drop lifecycle overrides;
- auto-archiving;
- background monitoring;
- global multi-agent locks;
- review assignment or approval workflows.
