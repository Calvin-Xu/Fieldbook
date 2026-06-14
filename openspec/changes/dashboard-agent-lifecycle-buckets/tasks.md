## 1. Specification And Review

- [x] 1.1 Run CC ideation review with `env -u ANTHROPIC_API_KEY` and Opus 4.7
  max effort.
- [x] 1.2 Draft proposal, design, tasks, and spec deltas for
  `dashboard-agent-lifecycle-buckets`.
- [x] 1.3 Update `PHASES.md`.
- [x] 1.4 Validate `dashboard-agent-lifecycle-buckets`.
- [x] 1.5 Run CC spec review.
- [x] 1.6 Patch blockers and revalidate before implementation.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for lifecycle bucket precedence.
- [x] 2.2 Add failing tests that recovered historical failures do not create
  `Needs attention`.
- [x] 2.3 Add failing tests that active jobs and recovery-in-progress failures
  create `Running`.
- [x] 2.4 Add failing tests that reviewable activity newer than the latest
  review marker creates `Review`.
- [x] 2.5 Add failing tests that `mark-reviewed` creates a structured review
  note and moves the experiment to `Open` when no newer reviewable activity
  exists.
- [x] 2.6 Add failing tests that handoff freshness renders as a badge/detail
  and does not control lifecycle grouping.

## 3. View And Repository Contract

- [x] 3.1 Add review/lifecycle columns to dashboard stable views.
- [x] 3.2 Add `review` to the note type allow-list.
- [x] 3.3 Add helper logic for latest review marker and newest reviewable
  activity.
- [x] 3.4 Keep dashboard handlers reading only stable `_v1` views.

## 4. CLI And Dashboard

- [x] 4.1 Add `fieldbook experiment mark-reviewed`.
- [x] 4.2 Replace dashboard index groups with `Needs attention`, `Running`,
  `Review`, `Open`, and `Archived`.
- [x] 4.3 Render `lifecycle`, `handoff_status`, and review timestamps on index
  cards/detail metrics.
- [x] 4.4 Update prompt applicability to use actionable/review state.

## 5. Docs And Skill

- [x] 5.1 Update README dashboard lifecycle guidance.
- [x] 5.2 Update the Fieldbook skill with review/open/archive guidance.
- [x] 5.3 Document that archived means intentionally closed; use `Open` for
  dormant work that might be resumed.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review.
- [x] 6.3 Patch blockers and rerun validation. No blockers were reported.
