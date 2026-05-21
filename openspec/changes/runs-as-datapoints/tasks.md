## 1. Specification And Review

- [x] 1.1 Treat the CC design critique in session `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, and `PHASES.md` entry for `runs-as-datapoints`.
- [x] 1.3 Validate `runs-as-datapoints`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for run idempotency scoped per primary experiment, run kind validation, invalid idempotency keys, and duplicate-create existing-row behavior.
- [x] 2.2 Add failing tests for `job_runs` many-to-many edges, role/status validation including `unknown_submit` and `killed`, per-edge status updates, and 1:1 `job add --run` backfill behavior.
- [x] 2.3 Add failing tests for reconcile manifests with `runs[]` and `job_runs[]`, including same-manifest forward references and idempotent re-apply.
- [x] 2.4 Add failing tests for progress derivation across planned, submitted, unknown-submit, training, trained, evaluated, complete, failed, killed, retry-superseded, and skipped runs.
- [x] 2.5 Add failing tests for experiment status/context `runs` blocks with expected-count gaps, metric coverage, checkpoint coverage, empty experiments, and bounded examples.
- [x] 2.6 Add failing tests for doctor checks: expected-vs-observed runs, checkpoint/eval artifacts without run links, and orphan/stale job-run edges.
- [x] 2.7 Add failing tests for stable views `v_job_runs_v1`, `v_runs_progress_v1`, and updated `v_runs_v1`/`v_jobs_v1` columns.

## 3. Schema And Views

- [x] 3.1 Add migration for `runs.experiment_id`, `runs.idempotency_key`, `runs.kind`, `job_runs`, indexes, and backfill from existing `jobs.run_id`.
- [x] 3.2 Add `v_job_runs_v1`.
- [x] 3.3 Update `v_runs_v1` and `v_run_summary_v1` with `kind` and `idempotency_key`.
- [x] 3.4 Update `v_jobs_v1` documentation/shape to keep legacy `run_id` but prefer job-run edges.
- [x] 3.5 Add `v_runs_progress_v1` with derived phase and coverage columns.

## 4. Repository, CLI, And Reconcile

- [x] 4.1 Extend run creation/list/show dictionaries with `idempotency_key` and `kind`.
- [x] 4.2 Add CLI flags `run add --idempotency-key` and `--kind`.
- [x] 4.3 Add repository and CLI support for `run link-job --run <run> --job <job> --role <role> --status <status>`.
- [x] 4.4 Ensure `job add --run <run>` creates or updates the matching `job_runs` edge for compatibility.
- [x] 4.5 Extend reconcile planning/apply for run idempotency and top-level `job_runs[]`.
- [x] 4.6 Support same-manifest job-run references to jobs/runs created in that manifest.

## 5. Status, Context, Doctor, Docs

- [x] 5.1 Add run progress summaries to `experiment status`.
- [x] 5.2 Add a Markdown matrix-progress section to `experiment context`.
- [x] 5.3 Add doctor checks for expected-vs-observed runs, unlinked run artifacts, and orphan job-run edges.
- [x] 5.4 Update README and Fieldbook agent skill launch protocol so agents create runs at plan time.
- [x] 5.5 Update `PHASES.md` to map Phase 15 to `runs-as-datapoints` and move privacy-redaction to Phase 16.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
