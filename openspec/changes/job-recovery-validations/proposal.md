## Why

Dogfooding exposed a repeated failure mode: after an agent retried a failed job successfully, the original failed job still polluted the experiment status as an unresolved blocker. Agents also recorded coverage checks and readiness facts in notes, which are readable but not queryable. Phase 12 makes recovery and validation state first-class so context-switching back to an experiment answers the two important questions quickly: what is still blocking, and what evidence says the experiment is ready?

This phase intentionally stops before live refresh orchestration. It stores recovery lineage and validation results, but external systems are still queried manually or through pure adapters.

## What Changes

- Add `jobs.retry_of` to link retry jobs to the job they recover.
- Add `submitting` and `unknown_submit` job statuses so agents can honestly record in-flight
  and ambiguous submission attempts before an external scheduler acknowledges a job.
- Derive failed-job retry state as `blocking_failed`, `recovery_in_progress`, or `recovered_failed`.
- Add stable recovery/readiness views such as `v_jobs_with_recovery_v1`, `v_experiment_blockers_v1`, and `v_validations_v1`.
- Add a structured `validations` table for coverage, provenance, freshness, and readiness checks with status `pass`, `fail`, `warning`, or `unknown`.
- Add artifact type `validation-report`.
- Add CLI support for recording retry lineage and validations.
- Extend reconcile manifests to ingest `retry_of` and validation rows atomically.
- Update `experiment status` and `experiment context` so agents see active blockers first, while still preserving historical failed jobs.
- Add doctor checks for retry cycles, missing retry targets, active failed validations, retry loops, stale in-progress recoveries, recovered failures that still have open debug notes, and suspected secret patterns.
- Add doctor checks for stale submission attempts so agents are prompted to refresh or correct
  jobs whose submission outcome is still uncertain.

## Behavior Change: Archived Experiments Require Explicit Errata

Before this amendment, notes could be appended to archived experiments without a
special marker. Fieldbook is still pre-v1, and this phase intentionally tightens
that behavior: any post-archive evidence write to notes, artifacts, or
validations must be explicit via `--errata` or row-level `_errata: true` in
reconcile. Jobs and metrics remain closed after archive.

## Capabilities

### New Capabilities

- `job-recovery-validations`: retry lineage, recovered-failure classification, and structured validation evidence.

### Modified Capabilities

- `agent-sessions-locality`: status/context output gains active blocker and readiness sections.
- `reconcile-core-hardening`: reconcile can ingest retry links and validation rows.
- `doctor-audit-portability`: doctor gains recovery and validation checks.

## Impact

- New migration, repository helpers, CLI commands, views, and tests.
- Status/context JSON shape changes before v1, preserving legacy `failed_jobs` while adding clearer blocker and recovery arrays.
- Existing ledgers migrate without requiring retry lineage or validation rows.
- No daemon, scheduler polling, Iris/GCS/W&B calls, or implicit refresh behavior.
