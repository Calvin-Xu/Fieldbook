## 1. Specification And Review

- [x] 1.1 Run CC ideation review before implementation resumes for Phase 12.
- [x] 1.2 Re-read this OpenSpec change and patch any stale assumptions from dogfood.
- [x] 1.3 Validate `job-recovery-validations`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [ ] 1.6 Commit and push the reviewed spec if it changed.

Do not begin implementation tasks until 1.6 is complete.

## 2. Tests First

- [ ] 2.1 Add failing tests for `jobs.retry_of`, missing target rejection, self-link rejection, and cycle rejection.
- [ ] 2.2 Add failing tests for submission lifecycle: `planned` -> `submitting` -> `queued`, `submitting` -> `unknown_submit`, `unknown_submit` -> `queued` via refresh, and `unknown_submit` -> `failed` via refresh-confirmed missing acknowledgment.
- [ ] 2.3 Add failing tests for blocking, recovery-in-progress, and recovered failed job classification across one-hop and multi-hop retry chains, including retry descendants in `submitting` and `unknown_submit`.
- [ ] 2.4 Add failing tests for `experiment status` and `experiment context` readiness sections, including submission-uncertainty buckets.
- [ ] 2.5 Add failing tests for validation row creation, update, archive, status validation, source artifact/job links, and session stamping.
- [ ] 2.6 Add failing tests for reconcile manifests with `retry_of`, including retry targets created in the same manifest, and `validations`.
- [ ] 2.7 Add failing tests for doctor retry, stale recovery, stale submission states, validation, and suspected-secret checks.
- [ ] 2.8 Add failing tests for stable views `v_jobs_with_recovery_v1`, `v_experiment_blockers_v1`, and `v_validations_v1`.

## 3. Schema And Views

- [ ] 3.1 Add migration for `jobs.retry_of`, `validations`, validation indexes, and artifact type validation updates.
- [ ] 3.2 Add `submitting` and `unknown_submit` to job status validation; this is a validation/config update, not a data migration.
- [ ] 3.3 Add recursive retry-chain view support without infinite loops on invalid legacy data.
- [ ] 3.4 Add `v_jobs_with_recovery_v1` with retry state plus blocking, recovery-in-progress, recovered, and submission-uncertainty flags.
- [ ] 3.5 Add `v_experiment_blockers_v1` with active job, submission uncertainty, blocking failure, and validation blocker rows.
- [ ] 3.6 Add `v_validations_v1` filtered to active validation rows.
- [ ] 3.7 Update snapshot export/import tests to cover the new schema.

## 4. Repository And CLI

- [ ] 4.1 Add repository helpers for setting retry lineage and querying recovery summaries.
- [ ] 4.2 Add validation repository helpers for create/update/archive/list/show.
- [ ] 4.3 Add `job add --retry-of` and a command to link an existing job to its retry target.
- [ ] 4.4 Add `validation add|list|show|archive`.
- [ ] 4.5 Add JSON and compact text output for validation commands.
- [ ] 4.6 Ensure archived experiments reject new job/validation writes unless an existing explicit archive override already applies.

## 5. Reconcile, Status, Context, And Doctor

- [ ] 5.1 Extend reconcile planning and operation audit for job `retry_of`.
- [ ] 5.2 Extend reconcile planning and operation audit for top-level `validations`.
- [ ] 5.3 Update `experiment status` with `ready`, `blocking_failed_jobs`, `recovery_in_progress_failed_jobs`, `recovered_failed_jobs`, and validation summaries.
- [ ] 5.4 Add `submission_in_progress_jobs`, `submission_unknown_jobs`, and `ready.submission_uncertainty_count` to status/context outputs.
- [ ] 5.5 Update `experiment context` to include readiness and validation evidence without dumping large artifacts.
- [ ] 5.6 Add doctor checks for retry cycles, missing retry targets, retry loops, stale recoveries, stale submitting jobs, stale unknown-submit jobs, active failed validations, recovered failures with open debug notes, and suspected secret patterns.
- [ ] 5.7 Add `fieldbook doctor --stale-submitting-hours` with default `1` and `--stale-unknown-submit-hours` with default `6`.
- [ ] 5.8 Update README and the Fieldbook agent skill with recovery/validation workflows.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
