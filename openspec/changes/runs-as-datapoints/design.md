## Context

Fieldbook is intended to be the source of truth for ML experiment progress. In ML mixture work, one launcher job may submit many training or eval specs. The experiment's scientific matrix is the set of expected datapoints, not the set of launcher jobs. A ledger that only records launcher jobs cannot support context switching, retry triage, metric coverage, or collaborator exports at the correct granularity.

The next phase makes `runs` carry that matrix. This is a schema and workflow correction, not a replacement for jobs or artifacts.

## Definitions

- **Experiment**: a research thread with a finite or intentionally open matrix of comparable datapoints.
- **Run**: one logical datapoint/comparison-row in that matrix. Examples: one candidate mixture at one scale/seed, one externally imported checkpoint row, or one aggregate row intentionally modeled as a row.
- **Job**: one execution attempt against an external or local system. Examples: an Iris parent launcher, eval batch, collection script, or retry.
- **Job-run edge**: the audited relationship between an execution attempt and each run it touched, with role/status information that can differ per child run.
- **Artifact**: durable byproduct, preferably linked to a run for checkpoints/eval results and to a job for logs/manifests.
- **Metric**: scalar observation keyed to a run.
- **Validation**: assertion about an entity's readiness, coverage, or correctness.

## Decisions

### Decision: Runs are planned datapoints

Runs SHALL be created at planning or submission time, before successful job completion. A run is not merely an observed W&B run or finished checkpoint; it is the expected row the experiment will later analyze.

This means a 117-row launcher manifest should produce 117 run rows immediately, plus one launcher job and 117 `job_runs` edges. If the launcher fails before dispatch, the planned runs remain useful: they define what was intended and what needs retry or cleanup.

### Decision: Run lifecycle is derived

Fieldbook keeps the existing `runs.status` as a coarse active/archived state. Matrix progress is derived from job-run edges, artifacts, metrics, and optional experiment attrs rather than stored as a mutable run lifecycle enum.

Derived phases:

- `planned`: run exists and has no active job-run edge.
- `submitted`: run has a job-run edge but no active/running/succeeded/failed edge.
- `training`: at least one train edge is `submitting`, `queued`, or `running`.
- `trained`: a train edge succeeded or a checkpoint artifact exists, but eval completion is not observed.
- `evaluated`: an eval edge succeeded or eval-result artifact exists, but required metric completion is unknown or incomplete.
- `complete`: required metrics are complete when declared; otherwise evaluated runs are complete.
- `failed`: the latest relevant job-run edge failed and no later successful edge supersedes it.
- `skipped`: all relevant active edges are skipped and no success evidence exists.

The exact derivation lives in stable views and repository helpers. Agents should treat it as a summary, not as a hand-edited field.

### Decision: Add `job_runs`

`jobs.run_id` cannot represent parent jobs and eval batches. Add `job_runs`:

- `job_id`
- `run_id`
- `role`: `train | eval | export | analyze | collect | other`
- `status`: `planned | submitting | queued | running | succeeded | failed | skipped | unknown`
- `started_at`
- `finished_at`
- `failure_reason`
- `attrs_json`
- `deleted_at`

`jobs.run_id` remains for compatibility in this phase and is maintained for simple 1:1 job additions. New progress/read surfaces use `job_runs`.

### Decision: Run idempotency is scoped per experiment

Runs gain:

- `experiment_id`: the primary experiment that owns the run idempotency key.
- `idempotency_key`: optional slug scoped to an experiment.
- `kind`: `datapoint | aggregate | analysis | external`, default `datapoint`.

The unique key is `(runs.experiment_id, runs.idempotency_key)` for active rows. A run can still belong to multiple experiments through `experiment_runs`; `runs.experiment_id` is the primary experiment used for idempotent creation and update. Additional experiment memberships are cross-links and do not get independent idempotency keys in this phase.

Run idempotency keys use the same slug shape as experiment idempotency keys: `^[a-z0-9][a-z0-9._-]{0,127}$`.

### Decision: Reconcile is the primary manifest ingest path

Adapters and agents should emit reconcile manifests with `runs[]`, `jobs[]`, and `job_runs[]`. Reconcile must be idempotent and support same-manifest forward references so a single manifest can create all planned rows atomically.

### Decision: Status/context show matrix progress

`experiment status` and `experiment context` should include a bounded `runs` block with:

- `total`
- `expected`
- `missing_expected_count`
- `by_kind`
- `by_phase`
- `coverage.has_checkpoint`
- `coverage.has_eval_result`
- `coverage.by_metric`
- bounded failed and missing examples

The block should be compact enough for agent context and precise enough to answer "what remains incomplete?"

The JSON shape is:

```json
{
  "runs": {
    "total": 117,
    "expected": 117,
    "missing_expected_count": 0,
    "by_kind": {"datapoint": 117},
    "by_phase": {"training": 8, "trained": 20, "complete": 89},
    "coverage": {
      "has_checkpoint": 109,
      "has_eval_result": 89,
      "by_metric": {
        "eval/uncheatable_eval/bpb": 89
      }
    },
    "failed_examples": [
      {"run_id": "run_...", "name": "candidate-017", "phase": "failed"}
    ],
    "missing_examples": [
      {"run_id": "run_...", "name": "candidate-042", "phase": "planned"}
    ]
  }
}
```

The `by_kind`, `by_phase`, and `coverage.by_metric` fields are dictionaries from stable string labels to integer counts. `coverage.has_checkpoint` and `coverage.has_eval_result` are integer run counts. Example arrays are bounded to 20 rows and include at least `run_id`, `name`, and `phase`.

### Decision: Required metric completion is optional

Fieldbook core does not impose a universal completion metric set. Experiments may set user attrs `progress.expected_runs` and `progress.required_metrics` to improve progress summaries. The `fieldbook.*` attr namespace remains system-managed and is not used for user-supplied progress hints. Without required metrics, evaluated runs are treated as complete.

Required metric matching is by `metric_name` only. Step/split-specific completion contracts are deferred. Missing or empty `progress.required_metrics` means evaluated runs are complete.

Phase precedence is deterministic:

1. `complete`
2. `training`
3. `failed`
4. `skipped`
5. `trained`
6. `evaluated`
7. `submitted`
8. `planned`

`unknown_submit` edges count as submitted ambiguity. `killed` edges count as failed. When ordering matters, Fieldbook uses edge `finished_at`, then `updated_at`, then `created_at`, then ID as a deterministic tie-breaker.

Precedence applies only after each phase's own preconditions are satisfied. For example, `complete` has highest priority only when the run also satisfies the evaluated/required-metric conditions; it does not short-circuit planned or unevaluated rows.

## Non-Goals

- Do not remove `jobs.run_id` in this phase.
- Do not build a Marin-specific parser for every launcher in core Fieldbook.
- Do not add background polling or automatic refresh.
- Do not implement privacy/redaction; defer to Phase 16.
- Do not store a mutable detailed run phase enum.
- Do not make runs errata-eligible in this phase. Post-archive errata remain limited to notes, artifacts, validations, and checkpoints.
- Do not implement many-source aggregate lineage beyond attrs; aggregate source-run tables are deferred.

## Risks / Trade-offs

- **Risk: job-run statuses drift from external systems.** Refresh adapters should reconcile edge status explicitly; doctor surfaces stale/missing edges.
- **Risk: run idempotency is ambiguous for multi-experiment shared rows.** Scope idempotency to one experiment and require explicit run links for sharing.
- **Risk: progress derivation is too generic.** Keep default phases conservative and let validations/attrs carry project-specific completeness.
- **Risk: manifests become large.** A few thousand rows is acceptable for SQLite/reconcile; streaming can wait until observed pressure.

## Launch Protocol Update

Agents should update launch workflows to:

1. Resolve the ledger and start or switch the session.
2. Generate the launch manifest locally.
3. Reconcile planned `runs[]` and `job_runs[]` in dry-run mode.
4. Apply the reconcile manifest before or during external job submission.
5. Record the launcher job as `submitting`, then update to acknowledged, `unknown_submit`, or `failed`.
6. Refresh external state later to update `job_runs[]`, artifacts, metrics, and validations.
