## Why

Marin dogfood exposed a core Fieldbook modeling failure: experiments recorded Iris parent jobs, launch manifests, artifacts, validations, and notes, but not the run/datapoint rows that those jobs were intended to produce. The active Marin ledger could therefore report job status, but not answer the central research question: how many expected datapoints exist, which ones were submitted, which produced checkpoints, which were evaluated, and which metrics are missing.

The existing `runs` table is the right primitive, but Fieldbook needs to make runs first-class at plan time and support jobs that fan out to many runs. A single nullable `jobs.run_id` cannot model parent launchers or eval batches that touch tens or hundreds of runs.

## What Changes

- Define `run` as one logical datapoint/comparison-row in an experiment matrix.
- Add run idempotency scoped to each experiment, plus a small run kind enum.
- Add a `job_runs` many-to-many edge table with per-run role/status/failure evidence for fan-out jobs.
- Extend reconcile manifests to ingest expected runs and job-run edges idempotently, including same-manifest forward references.
- Add run-progress views and status/context summaries so agents can see planned/submitted/training/trained/evaluated/complete/failed coverage.
- Add doctor checks for expected-vs-observed run gaps, unlinked run artifacts, and orphan job-run edges.
- Update the agent skill and README launch protocol: create/reconcile planned runs before or during submission, not after successful completion.

## Capabilities

### New Capability

- `runs-as-datapoints`: first-class experiment matrix rows, job-run fan-out links, and run-progress reporting.

### Modified Capabilities

- `reconcile-core-hardening`: reconcile accepts run idempotency fields and top-level `job_runs`.
- `readonly-sql-stable-views`: stable views expose run kind/idempotency, job-run edges, and run progress.
- `agent-workflow`: status/context include a bounded matrix-progress block.
- `doctor-audit-portability`: doctor warns on matrix population and job-run linkage gaps.

## Impact

- Adds one migration for `runs.idempotency_key`, `runs.kind`, `job_runs`, indexes, and views.
- Keeps `jobs.run_id` as a deprecated compatibility column for now; new writes maintain both for 1:1 job-run links where possible, but read surfaces prefer `job_runs`.
- Existing ledgers backfill `job_runs` edges from non-null `jobs.run_id`.
- Status/context JSON changes are acceptable because Fieldbook remains pre-v1.
- Privacy/redaction is deferred from Phase 15 to Phase 16.
