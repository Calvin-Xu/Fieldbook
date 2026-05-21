## Context

Fieldbook is meant to let agents leave and resume ML experiments without reopening long chat logs. The ledger currently knows that jobs failed, but not whether a later job recovered them. It also has notes and artifacts, but no structured place for coverage assertions like "all 262 matrix rows are complete" or "parity eval failures are resolved." This makes resume surfaces noisy and makes collaborator-ready exports harder to trust.

Dogfooding also exposed a second gap: an agent can attempt an external submission, get repeated scheduler timeouts, and have no honest job state for "I tried to submit, but the external job was never acknowledged." Treating that as `planned` hides the attempt; treating it as `running` overclaims success. Phase 12 adds the minimum schema needed to distinguish active blockers from historical failures, represent ambiguous submissions, and store machine-queryable validation facts.

## Goals / Non-Goals

**Goals:**

- Represent job retry lineage with one durable link.
- Represent submission attempts that are in-flight or ambiguous before external acknowledgment.
- Classify failed jobs as blocking, recovery-in-progress, or recovered from current ledger state.
- Store validation checks as structured ledger records, not prose-only notes.
- Make `experiment status` and `experiment context` bounded and action-oriented.
- Keep writes audited through existing repositories and reconcile.
- Preserve enough historical failure context for postmortems and debugging.

**Non-Goals:**

- No live external refresh, polling, daemon, or scheduler API calls.
- No generalized graph edge table.
- No job state history table.
- No validation rule engine or automatic metric computation.
- No automatic note resolution when a retry succeeds.
- No launcher wrappers around Iris, W&B, GCS, or other external systems.
- No dashboard UI.

## Decisions

### Decision: Use `jobs.retry_of` for recovery lineage

Add nullable `jobs.retry_of` referencing `jobs.id`. This is sufficient for the common "retry failed child under a fresh prefix" workflow and avoids a generic relation table before Fieldbook needs one.

A retry chain can have multiple hops. Failed jobs use a derived three-state classification:

- `blocking_failed`: failed, not archived, no transitive retry descendant is in `submitting`, `unknown_submit`, `queued`, or `running`, and no transitive retry descendant succeeded.
- `recovery_in_progress`: failed, not archived, at least one transitive retry descendant is in `submitting`, `unknown_submit`, `queued`, or `running`, and no transitive retry descendant succeeded.
- `recovered_failed`: failed, not archived, any transitive retry descendant succeeded.

`recovery_in_progress` is not a blocking failed job. It is active work that may still prevent an experiment from being ready for analysis because a retry is submitting, ambiguous, queued, or running, but it should not ask agents to launch another retry unless the in-flight recovery becomes stale or fails.

CLI and reconcile writes reject:

- missing retry targets;
- self-retry links;
- retry cycles.

Doctor also checks for cycles and missing targets so hand-edited or pre-v1 ledgers are diagnosable.

### Decision: Track submission-attempt lifecycle in job status

Add two job statuses:

- `submitting`: the agent has recorded the job and is currently attempting submission to an external system.
- `unknown_submit`: submission was attempted, but the agent did not receive a reliable acknowledgment from the external system because of a timeout, connection reset, interrupted submitter, or similar ambiguous failure.

These states are distinct from:

- `planned`: recorded locally but not yet attempted.
- `queued`/`running`/terminal states: externally acknowledged execution states.
- `unknown`: a previously acknowledged external job whose current execution state is unknown.

An external system that explicitly rejects a submission should be recorded as `failed` with a `failure_reason` such as `submission rejected: <details>`. `unknown_submit` is reserved for ambiguity, not definite rejection.

`submitting` and `unknown_submit` are active-uncertainty states. They do not count as blocking failed jobs, but they do prevent a "fully ready" interpretation until refresh or manual correction resolves them. Agents should use refresh, an external job lookup, or an explicit `job update-status` correction to move them to an acknowledged execution state or to `failed` if the submission never existed.

Doctor warns on stale submission states:

- `submitting` older than 1 hour by default;
- `unknown_submit` older than 6 hours by default.

These thresholds are configurable via `fieldbook doctor --stale-submitting-hours` and `fieldbook doctor --stale-unknown-submit-hours`.

### Decision: Preserve historical failures while adding blocker arrays

Existing `failed_jobs` output remains available as historical context until v1, but agents should use the clearer fields:

- `ready.has_active_blockers`
- `ready.blocker_count`
- `ready.recovery_in_progress_count`
- `ready.submission_uncertainty_count`
- `ready.validation_status`
- `blocking_failed_jobs`
- `recovery_in_progress_failed_jobs`
- `submission_in_progress_jobs`
- `submission_unknown_jobs`
- `recovered_failed_jobs`
- `historical.failed_jobs`

Text output prints blocking failures first, submission uncertainty and in-progress recoveries as active work, recovered failures in a compact collapsed section, and full details only in JSON or drilldown commands.

### Decision: Store validations in a dedicated table

Add `validations` rather than overloading metrics or notes. Metrics are measurements; notes are prose; validations are assertions about readiness, coverage, provenance, or freshness.

The table stores:

- `id`
- `entity_type`
- `entity_id`
- `check_name`
- `status`
- `expected_value`
- `measured_value`
- `details_json`
- `source_artifact_id`
- `source_job_id`
- `session_id`
- `created_at`
- `updated_at`
- `deleted_at`
- `attrs_json`

`status` is one of `pass`, `fail`, `warning`, or `unknown`. A partial unique index covers active `(entity_type, entity_id, check_name)` so the same check can be updated idempotently.

### Decision: Keep validation computation outside core Fieldbook

Fieldbook stores validation facts and makes them queryable. It does not decide how to compute coverage, SNR, metric completeness, or external freshness. Agents, adapters, notebooks, or repo-specific scripts compute those values and write validation rows.

This keeps Fieldbook portable and avoids importing Marin-specific assumptions into the core.

Matrix-style validation checks SHOULD use stable check-name conventions so agents can query rollups without understanding repo-specific schemas:

- Experiment rollup checks: `<domain>.coverage.rollup`
- Row checks: `<domain>.coverage.row.<n>`
- Cell checks: `<domain>.coverage.cell.<row>.<col>`

The rollup status SHOULD be `pass` only when all component checks pass, `fail` when any component check fails, and `unknown` when at least one component is unknown and none fail. Fieldbook stores these rows but does not compute the matrix rule itself in Phase 12.

### Decision: Add `validation-report` artifacts

Validation rows should usually point to a compact report artifact when the evidence is larger than a scalar. Add `validation-report` as an artifact type for CSV, Markdown, JSON, HTML, or notebook-derived summaries.

The validation row stores the headline result; the artifact stores supporting details.

### Decision: Reconcile remains the bulk-write path

Reconcile manifests gain support for:

- `jobs[].retry_of`
- top-level `validations`

Validation row upsert uses `(entity_type, entity_id, check_name)` unless an explicit validation ID is supplied. Archives use either ID or the same key.

Manifest application remains one transaction. Invalid retry references or validation references reject the whole manifest before writes commit.

Retry target resolution is two-pass within a single manifest: the planner indexes manifest job IDs before validating `retry_of` references, so a retry row can appear before its target row in the manifest.

### Decision: Status readiness is derived, not manually toggled

An experiment is ready for analysis when:

- it has no active queued/running jobs unless explicitly allowed by the caller;
- it has no jobs in `submitting` or `unknown_submit` unless explicitly allowed by the caller;
- it has no blocking failed jobs;
- it has no active validation with status `fail`;
- it has no active validation with status `unknown` for checks marked blocking in attrs.

Recovery-in-progress failed jobs are not counted as blocking failed jobs, but their submitting, ambiguous, queued, or running retry descendants still appear in active-job readiness counts.

Submission-uncertainty jobs are also not blocking failed jobs, but they appear in readiness as active uncertainty with suggested next action `refresh external state or correct the job status`.

The readiness summary is derived at query time. Fieldbook does not add a mutable `experiment.ready` boolean.

## Defaults

- Retry lineage is optional. Existing jobs without `retry_of` retain current behavior.
- Validation body fields are short strings; long evidence belongs in artifacts.
- Default `experiment status` shows compact validation and recovery summaries.
- `experiment context` includes full Markdown note bodies for active notes, but validation details stay summarized with artifact links.
- Doctor reports retry/validation issues as warnings except referential integrity problems, which are errors.

## Risks / Trade-offs

- **Risk: retry lineage is too simple for fan-in recovery.** Accepted. A single retry link covers the current failure-only retry workflow. A later generic relation table can be added if real workflows need it.
- **Risk: validations become a second metrics table.** Mitigated by keeping validation values string/JSON and describing them as readiness assertions, not time series.
- **Risk: status output becomes too large.** Mitigated by bounded arrays, compact recovered-failure summaries, and drilldown commands.
- **Risk: agents misuse recovered failures as ignored failures.** Mitigated by preserving historical failures and doctor warnings when recovered failures still have open debug notes.
- **Risk: agents still bypass Fieldbook before launch.** Mitigated by making submission states honest and easy to use. The enforcement and launch protocol live in Phase 13 skills/docs, not in a fragile scheduler wrapper.
