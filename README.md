# Fieldbook

Fieldbook is a local-first experiment ledger for AI research agents.

It is meant for ML research projects where experiments span many training jobs,
follow-up eval jobs, result artifacts, notes, and retries. The goal is not to
replace the training orchestrator, W&B, or custom analysis dashboards. The goal
is to give coding agents a durable source of truth for what was launched, what
finished, what failed, where the data lives, and what should happen next.

Fieldbook is agent-first. The expected interaction model is that a human gives
natural-language research direction, and a coding agent uses Fieldbook to
record jobs, refresh state, preserve provenance, export tables, and recover
context after switching experiments. Humans can run the CLI directly, but the
CLI and outputs are optimized for agents.

## Motivation

Modern ML research often has more live state than fits in one conversation:

- long-running jobs can finish or fail while the researcher works on another
  direction;
- follow-up evals may be launched days after the original training run;
- result tables need reproducible provenance, not just copied CSVs;
- debugging history matters when deciding whether to retry, skip, or trust a
  datapoint;
- collaborators need artifact exports that can be traced back to checkpoints,
  W&B runs, commands, and code revisions.

Fieldbook is designed around that workflow. It should be small enough to drop
into any ML repo, but structured enough that agents can recover context without
re-reading a long chat transcript.

## Intended Shape

Fieldbook will provide:

- a repo-local SQLite database, stored under `.experiments/`;
- a deterministic CLI for recording and querying experiments, runs, jobs,
  artifacts, metrics, and notes;
- compact agent-facing status summaries for context switching;
- machine-readable JSON for agent workflows and concise text summaries for
  human review;
- provenance-preserving CSV/JSON exports for collaborators and dashboards;
- a portable skill that teaches coding agents how to use the ledger;
- optional project-specific adapters, with Marin as the first target.

The database is the local source of truth. External systems such as W&B, Iris,
GCS, Slurm, or cloud storage are recorded as linked systems and artifact
pointers. Fieldbook may sync summaries to W&B, but it should not depend on W&B
as the only source of provenance.

## Non-Goals

The initial version will not include:

- a background polling daemon;
- an admin web UI;
- a replacement for MLflow, W&B, or a job scheduler;
- automatic ingestion of every metric time series;
- a Marin-only schema.

Custom dashboards should be built from the SQLite database and exported tables.
An admin UI can come later if the CLI and schema prove useful.

## Core Concepts

- **Experiment**: a research thread or question, such as "300M raw-PPL SNR" or
  "MoE mixture scaling ladder".
- **Run**: a scientific datapoint, model, mixture, or configuration whose
  provenance and metrics are tracked.
- **Job**: an execution attempt that trains, evaluates, collects, exports, or
  repairs one or more runs.
- **Artifact**: a durable pointer to a checkpoint, result file, plot, CSV,
  report, W&B run, or debug log.
- **Metric**: a summary observation tied to a run and usually backed by an
  artifact or external system.
- **Note**: a structured research, debug, or handoff entry.
- **Reconcile**: a refresh operation that inspects external systems and
  proposes ledger updates, reducing drift when humans or agents forget to log
  a job at launch time.

## First Implementation Phase

The first phase is tracked in OpenSpec under:

`openspec/changes/bootstrap-fieldbook-mvp/`

That phase should establish the portable MVP:

- initialize a local ledger;
- create and inspect experiments;
- record runs, jobs, artifacts, metrics, and notes;
- summarize active experiment state;
- support coding-agent context recovery through compact status, targeted
  drilldowns, next-action notes, and JSON output;
- support namespaced custom fields for repo-specific metadata;
- provide a first reconcile path for Marin-style manually launched jobs;
- export collaborator-ready tables with provenance columns.

The first implementation phase intentionally keeps the agent skill as a draft
usage guide. Publishing a stable, reusable skill is a follow-up once the CLI and
schema have been dogfooded.

## Agent Quickstart

This quickstart is intentionally written as commands an agent can run in a
temporary or real ML repo.

From another repo without adding Fieldbook as a dependency, run Fieldbook from a
sidecar checkout:

```bash
uv run --project <FIELDBOOK_CHECKOUT> fieldbook <command> ...
```

`--ledger` is command-scoped in the current CLI, so put it after the command,
for example `fieldbook experiment list --ledger <path> --json`.

```bash
uv run fieldbook init --json
```

Create an experiment and capture its ID:

```bash
EXP_ID=$(uv run fieldbook experiment create \
  --name "300M eval proxy sprint" \
  --description "Track training, follow-up evals, and exports" \
  --tag marin \
  --attr marin.scale=300m_6b \
  --json | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

Record a run, a training job, an artifact, a metric, and a next action:

```bash
RUN_ID=$(uv run fieldbook run add \
  --experiment "$EXP_ID" \
  --name run_00097 \
  --external-system wandb \
  --external-id example-wandb-run \
  --attr marin.mixture=proportional \
  --json | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

uv run fieldbook run add \
  --experiment "$EXP_ID" \
  --name run_00097_followup_eval \
  --parent-run "$RUN_ID" \
  --json

JOB_ID=$(uv run fieldbook job add \
  --run "$RUN_ID" \
  --name train \
  --status running \
  --launcher iris \
  --external-system iris \
  --external-id /user/example-train \
  --command "uv run train.py" \
  --json | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

uv run fieldbook artifact add \
  --run "$RUN_ID" \
  --type checkpoint \
  --uri gs://example/checkpoints/step-100 \
  --json

uv run fieldbook metric add \
  --run "$RUN_ID" \
  --name eval/uncheatable_eval/bpb \
  --value 0.91 \
  --step 100 \
  --source-job "$JOB_ID" \
  --json

uv run fieldbook note add \
  --entity-type experiment \
  --entity-id "$EXP_ID" \
  --type handoff \
  --title "Refresh and export" \
  --body "Refresh job status and export collaborator table." \
  --json
```

Context-switch back to the experiment from any subdirectory:

```bash
uv run fieldbook experiment status "$EXP_ID" --json
uv run fieldbook experiment context "$EXP_ID"
```

`status` is the compact navigation surface for agents: counts, failed/stale
jobs, key artifacts, and note previews. `context` is the LLM-ready Markdown
handoff surface with full bodies for active handoff, next-action, and debug
notes plus recent research and decision notes.

For multiline Markdown notes, prefer a body file:

```bash
cat > /tmp/fieldbook-note.md <<'EOF'
# Finding

- Use `note_type=handoff` for blockers that the next agent must see.
- Use `note_type=next-action` for active work.
- Use `note_type=research` and `note_type=decision` for durable context.
EOF

uv run fieldbook note add \
  --entity-type experiment \
  --entity-id "$EXP_ID" \
  --type research \
  --title "Note conventions" \
  --body-file /tmp/fieldbook-note.md \
  --json

uv run fieldbook note show "$NOTE_ID" --json
```

Refresh from a file-based manifest:

```bash
uv run fieldbook reconcile file \
  --experiment "$EXP_ID" \
  --path tests/fixtures/marin/eval_completion_manifest.json \
  --source "manual-eval-refresh" \
  --apply \
  --json
```

Reconcile manifests default to upsert. Rows for runs, jobs, artifacts, metrics,
and notes can set `_op: "archive"` to soft-archive an existing row. `_op:
"delete"` is intentionally rejected. Manifests can also append external sync
events, which is useful for recording follow-up W&B, Iris, or artifact refresh
attempts without making those systems the ledger source of truth:

```json
{
  "jobs": [
    {
      "id": "job_...",
      "_op": "archive"
    }
  ],
  "sync_events": [
    {
      "target_system": "wandb",
      "target_identifier": "run-id",
      "status": "synced",
      "idempotency_key": "followup-eval-sync-1"
    }
  ]
}
```

Inspect reconcile history and per-operation audit rows:

```bash
uv run fieldbook reconcile log --json
uv run fieldbook reconcile log --event "$RECONCILE_EVENT_ID" --json
uv run fieldbook reconcile log --source "manual-eval-refresh" --operations --json
```

## W&B Writeback

Fieldbook can explicitly mirror selected Fieldbook metrics into W&B run
summaries. Fieldbook remains the source of truth; W&B is a presentation target.
Dry-run first:

```bash
uv run fieldbook writeback wandb \
  --run "$FOLLOWUP_RUN_ID" \
  --metric "eval/*" \
  --json
```

Apply requires an explicit writer. The first Fieldbook write to a W&B target also
requires `--first-write-ok`, and keys are namespaced under `fieldbook/` by
default:

```bash
uv run fieldbook writeback wandb \
  --run "$FOLLOWUP_RUN_ID" \
  --metric "eval/*" \
  --apply \
  --writer real \
  --first-write-ok \
  --json
```

Use `--writer fake` for local smoke tests that should not contact W&B. Real W&B
support is optional; install `fieldbook[wandb]` before using `--writer real`.
Do not use `--raw-keys` unless the user explicitly wants to risk overwriting
existing W&B summary keys; it requires `--force-target`.

Inspect writeback history with:

```bash
uv run fieldbook writeback log --target-system wandb --json
```

Use adapters when external state has already been exported to local files.
Adapters do not read or write the ledger. They translate snapshots into
reconcile manifests, which an agent can inspect and then apply explicitly:

```bash
uv run fieldbook adapter list --json
uv run fieldbook adapter describe iris-jobs-json --json

uv run fieldbook adapter run iris-jobs-json \
  --input /tmp/iris_jobs.json \
  --output /tmp/iris_jobs_manifest.json \
  --debug-output /tmp/iris_jobs_debug.json \
  --json

uv run fieldbook reconcile file \
  --experiment "$EXP_ID" \
  --path /tmp/iris_jobs_manifest.json \
  --source "iris-jobs-refresh" \
  --apply \
  --json
```

Use `--strict` when a refresh should fail on any skipped input row. Adapter
debug output contains unredacted source rows and should be treated as local
diagnostic material.

Audit the ledger before trusting a resumed experiment or export:

```bash
uv run fieldbook doctor --json
uv run fieldbook doctor --list-checks --json
uv run fieldbook doctor --check stale-jobs --stale-hours 12 --json
```

`doctor` is read-only. It reports stable issue codes, severities, affected
entities, details, and suggested next actions. It exits nonzero for errors;
`--strict` also exits nonzero for warnings. Use `reconcile log` and stable
views such as `v_jobs_needing_attention_v1` or `v_reconcile_log_v1` to debug
specific findings.

Create a portable full-ledger snapshot when moving a ledger or sharing the
entire provenance database:

```bash
uv run fieldbook snapshot export --output /tmp/fieldbook-ledger.sqlite --json
uv run fieldbook snapshot inspect --input /tmp/fieldbook-ledger.sqlite --json
uv run fieldbook snapshot import \
  --input /tmp/fieldbook-ledger.sqlite \
  --output /tmp/restored-ledger.sqlite \
  --json
```

Snapshots are full-ledger copies. They include notes, local paths, sync events,
reconcile history, archived rows, and other provenance that may be sensitive.
Review before sharing. For collaborator metric tables, prefer `export
metrics-long`, `export runs-wide`, or `export coverage`.

Inspect the ledger through stable SQL views:

```bash
uv run fieldbook db path --json

uv run fieldbook sql \
  --query "SELECT run_id, metric_name, value FROM v_metrics_long_v1 WHERE metric_name = 'eval/uncheatable_eval/bpb'" \
  --limit 100 \
  --json
```

`fieldbook sql` is read-only and bounded. It rejects writes, DDL, PRAGMAs,
`ATTACH`, extension loading, multiple statements, runaway queries, and
oversized output. JSON output uses an envelope with `envelope_version`,
`columns`, `rows`, `row_count`, and `truncated`. NDJSON and CSV are available
with `--format ndjson|csv`.

Use `v_*_v1` views as the public SQL contract. Tables are internal
implementation details; future breaking query-contract changes should add
`_v2` views instead of changing `_v1` columns.

Export collaborator-ready tables:

```bash
uv run fieldbook export metrics-long \
  --experiment "$EXP_ID" \
  --output .experiments/metrics_long.csv \
  --json

uv run fieldbook export runs-wide \
  --experiment "$EXP_ID" \
  --output .experiments/runs_wide.csv \
  --metric eval/uncheatable_eval/bpb \
  --json
```

## Why "Fieldbook"?

A fieldbook is where researchers keep observations, coordinates, sketches,
measurements, and follow-up notes while work is still in progress. That is the
role this project should play for agent-led ML research: practical, local,
portable, and reliable enough to return to after context switches.
