# Fieldbook

Use this skill when an ML research repo has Fieldbook installed and the user
asks to track experiments, recover context, reconcile jobs, document failures,
or export collaborator-ready data.

## Operating Principles

- Treat Fieldbook's SQLite ledger as the local source of truth.
- Use JSON output for agent workflows: pass `--json` on `list`, `show`,
  `status`, `create`, and `add` commands.
- Record external systems as links and provenance, not as the source of truth.
- Keep notes concise but Markdown-structured. Use `note_type=handoff` for
  blockers or resume context the next agent must see, `note_type=next-action`
  for active work, `note_type=debug` for unresolved investigations, and
  `note_type=research` / `note_type=decision` for durable context.
- Do not dump the entire ledger into context. Start active-experiment work with
  `experiment workloop`, use `experiment status` for lower-level compact
  counts, use `experiment context` when full handoff context is needed, then
  drill into specific runs, jobs, artifacts, metrics, or notes.
- Before mutating a ledger after a context switch, run `fieldbook db where
  --json` to confirm ledger locality and identity.
- Use advisory sessions for agent context switching. They are provenance and
  handoff records, not locks.
- Treat `run` rows as planned experiment datapoints. Before launching a matrix
  job, create one run per intended result row and link launcher jobs to those
  runs with `run link-job`.
- Record live submissions before invoking external launchers. Use
  `submitting` while the launcher is in-flight and `unknown_submit` if the
  launcher exits without a reliable external acknowledgment.
- Refresh external state explicitly with `fieldbook refresh`; do not wait until
  after a successful launch to create the Fieldbook job record.

## Initialize A Ledger

From a repo root or subdirectory:

```bash
uv run fieldbook init --json
```

If the repo has no Git root, this creates `.experiments/ledger.sqlite` under
the current working directory. Use `--ledger` or `FIELDBOOK_LEDGER` only when
the user wants an explicit non-default ledger.

To share a ledger across worktrees without adding Fieldbook as a project
dependency, add a minimal `.fieldbook` file:

```yaml
ledger: ../shared-fieldbook/ledger.sqlite
```

Relative paths resolve relative to the `.fieldbook` file. Malformed configs
are hard errors; Fieldbook will not silently fall back to a different ledger.

From a downstream repo that should not depend on Fieldbook, use a sidecar
checkout instead of editing the downstream `pyproject.toml`:

```bash
uv run --project <FIELDBOOK_CHECKOUT> fieldbook <command> ...
```

The current CLI treats `--ledger` as command-scoped, so place it after the
command or subcommand: `fieldbook experiment list --ledger <path> --json`.

## Context Switch Back To An Experiment

```bash
uv run fieldbook db where --json
uv run fieldbook experiment list --json
uv run fieldbook experiment workloop "$EXP_ID" --json
uv run fieldbook experiment status "$EXP_ID" --json
uv run fieldbook experiment context "$EXP_ID"
uv run fieldbook experiment triage "$EXP_ID" --json
```

Use `workloop` as the preferred bounded resume surface. It includes locality,
session state, run/datapoint progress, jobs, validations, freshness, scoped
doctor issues, and suggested next commands without launching, monitoring,
refreshing, writing handoffs, or cleanup unless explicit flags are passed. Use
`context` for full Markdown note bodies. Then inspect only the relevant
entities:

```bash
uv run fieldbook job show "$JOB_ID" --json
uv run fieldbook run show "$RUN_ID" --json
uv run fieldbook note list --entity-type experiment --entity-id "$EXP_ID" --status open --json
uv run fieldbook note show "$NOTE_ID" --json
```

Before leaving an experiment, write a handoff:

```bash
uv run fieldbook experiment handoff "$EXP_ID" --body-file /tmp/handoff.md --json
```

Use `--archive` when the handoff should close the experiment. Archived
experiments reject normal writes; use `--errata` only for explicit
post-archive notes, artifacts, validations, or handoffs. Errata rows are
visible in status/context under historical evidence and do not reactivate the
experiment.

Local-file artifacts are freshness-tracked. If status/context, refresh output,
or doctor reports drift, inspect the file and then either regenerate the
artifact, rerun the validation, or refresh the captured metadata:

```bash
uv run fieldbook doctor --check artifact.local_drift --json
uv run fieldbook artifact refresh-local "$ARTIFACT_ID" --update-hash --json
uv run fieldbook doctor --check validation.source_drift --json
```

If external job or metric state may have changed, refresh explicitly rather
than relying on memory or chat logs:

```bash
uv run fieldbook refresh list-sources --json
uv run fieldbook experiment workloop "$EXP_ID" --refresh iris_jobs --json
uv run fieldbook experiment workloop "$EXP_ID" --refresh iris_jobs --apply --json
uv run fieldbook refresh run --source iris_jobs --experiment "$EXP_ID" --json
uv run fieldbook refresh run --source iris_jobs --experiment "$EXP_ID" --apply --json
uv run fieldbook refresh log --json
```

Refresh is snapshot-backed. The dry-run writes local diagnostics and a refresh
event but does not mutate experiment rows. Apply only after inspecting the
manifest or when the source is already trusted. If the repo already uses
`.fieldbook` as a ledger-config file, pass `--config <path>` to point at the
refresh TOML explicitly. Command-source argv entries may use `{experiment_id}`,
`{ledger_path}`, and `{source}` placeholders.

Use sessions when starting, leaving, or switching active research context:

```bash
uv run fieldbook session start \
  --experiment "$EXP_ID" \
  --agent codex \
  --intent "debug downstream eval retries" \
  --json

uv run fieldbook session current --json

uv run fieldbook session switch \
  --to "$NEXT_EXP_ID" \
  --agent codex \
  --intent "collect completed metrics" \
  --json

uv run fieldbook session end --json
```

`session start` writes `.fieldbook.session` next to the resolved ledger root.
Fieldbook also adds `.fieldbook.session` to the marker directory's `.gitignore`
when needed. `FIELDBOOK_SESSION_ID` overrides the marker when present; unset it
in the parent shell after ending an env-selected session. The `session end`
JSON payload includes `env_hint` when this cleanup is needed. `session switch`
atomically closes the old session, writes a Markdown handoff note on the old
experiment, opens the new session, updates the marker, and prints the target
experiment context. Sessions are advisory: multiple open sessions are allowed,
and stale sessions are doctor warnings rather than locks.

Use advisory leases when a long-running agent owns a babysit loop or when
multiple agents are coordinating in the same repo:

```bash
uv run fieldbook lease claim --entity-type experiment --entity-id "$EXP_ID" --owner codex --json
uv run fieldbook lease claim --entity-type job --entity-id "$JOB_ID" --owner babysitter --expires-at "$EXPIRES_AT" --json
uv run fieldbook lease heartbeat "$LEASE_ID" --owner babysitter --attr monitor.observed_status=running --json
uv run fieldbook lease release "$LEASE_ID" --owner babysitter --reason handoff --json
uv run fieldbook doctor --check leases --json
```

Leases are advisory, not locks. They surface ownership, stale heartbeats,
expired claims, and force takeovers in `status`, `workloop`, doctor, and stable
SQL views. Lease attrs are monitor observations only; update authoritative job
status through `job update-status` or reconcile.

Use the dashboard only as a read-only human scan surface:

```bash
uv run fieldbook dashboard serve --json
```

The dashboard reads stable `_v1` views and shows copyable agent instructions or
external links. Treat each dashboard prompt card as a human-to-agent handoff:
the user may paste it into the current session, but the dashboard does not send
prompts, call agents, run commands, or mutate the ledger. Use the Fieldbook
skill for workflow practice rather than relying on the dashboard prompt as a
full procedure.
It has no write routes and does not send prompts.

Dashboard lifecycle buckets are rule-derived from the ledger:

- `Needs attention`: blocking failures, failing validations, stale submissions,
  or stale advisory leases need action.
- `Running`: queued/running jobs, submissions, or retry descendants are still
  live external work. Active advisory leases are ownership badges, not running
  work; stale leases still need action.
- `Review`: new outputs or evidence are newer than the latest review marker.
- `Open`: no current action is required, but work may be resumed later.
- `Archived`: intentionally closed historical work.

After reviewing current outputs, record that explicitly:

```bash
uv run fieldbook experiment mark-reviewed "$EXP_ID" --body-file /tmp/review.md --json
```

Do not archive merely because work is dormant. Use `Open` for dormant work that
might be resumed; use `Archived` only when the experiment is intentionally
closed. Handoff freshness remains a badge/detail, not a lifecycle bucket.

Useful read-only prompt commands:

```bash
uv run fieldbook prompt list --json
uv run fieldbook prompt actions "$EXP_ID" --json
uv run fieldbook prompt build refresh-external-state "$EXP_ID" --json
```

## Record Work

Create an experiment:

```bash
uv run fieldbook experiment create \
  --name "short research thread name" \
  --description "one-sentence objective" \
  --idempotency-key "project.short-research-thread-name" \
  --tag marin \
  --attr marin.issue=5416 \
  --json
```

Record planned runs and jobs:

```bash
RUN_ID=$(uv run fieldbook run add \
  --experiment "$EXP_ID" \
  --name "$RUN_NAME" \
  --kind datapoint \
  --idempotency-key "$EXPERIMENT_SLUG.$RUN_NAME" \
  --json | jq -r .id)
uv run fieldbook run add --experiment "$EXP_ID" --name "$DERIVED_RUN" --parent-run "$RUN_ID" --json
JOB_ID=$(uv run fieldbook job add --run "$RUN_ID" --status running --launcher iris --external-system iris --external-id "$JOB_PATH" --json | jq -r .id)
uv run fieldbook run link-job --run "$RUN_ID" --job "$JOB_ID" --role train --status running --json
```

Record jobs before launching when possible. Use `submitting` while the external
launcher is in-flight, `unknown_submit` when the submitter times out before a
reliable external acknowledgment, and `failed` only when the external system
explicitly rejected the submission:

```bash
JOB_ID=$(uv run fieldbook job add \
  --experiment "$EXP_ID" \
  --name "eval submission" \
  --status submitting \
  --launcher iris \
  --command "$LAUNCH_COMMAND" \
  --json | jq -r .id)

uv run fieldbook job update-status "$JOB_ID" \
  --status unknown_submit \
  --failure-reason "controller timeout before acknowledgment" \
  --json
```

The launch protocol is:

1. Run `fieldbook db where --json`.
2. Start or switch a session for the active experiment.
3. Add one run per intended result row. Use stable `--idempotency-key` values
   so rerunning the planner returns the same datapoints.
4. Add the job with `--status submitting` and the exact launcher command before
   invoking the external launcher.
5. Run the external launcher.
6. Link the job to each affected run with `run link-job`, using `role=train`,
   `role=eval`, or another explicit role and the best-known per-run status.
7. Update the job to an acknowledged state with the external identifier, or to
   `unknown_submit` / `failed` when the outcome is ambiguous or rejected.
8. Later, run `fieldbook refresh run --source <name> --apply` to reconcile
   external state and validations.

When retrying a failed job, link lineage so recovered failures stop appearing as
active blockers:

```bash
uv run fieldbook job add \
  --experiment "$EXP_ID" \
  --name "eval retry" \
  --status queued \
  --retry-of "$FAILED_JOB_ID" \
  --launcher iris \
  --external-system iris \
  --external-id "$RETRY_JOB_PATH" \
  --json
```

Update status flexibly when the external system changes:

```bash
uv run fieldbook job update-status "$JOB_ID" --status succeeded --json
```

Record structured validation evidence for coverage/readiness facts that agents
need to query later. Use notes for interpretation and `validation-report`
artifacts for larger supporting tables:

```bash
REPORT_ID=$(uv run fieldbook artifact add \
  --experiment "$EXP_ID" \
  --type validation-report \
  --uri reports/coverage.md \
  --json | jq -r .id)

uv run fieldbook validation add \
  --entity-type experiment \
  --entity-id "$EXP_ID" \
  --check-name matrix.coverage.rollup \
  --status fail \
  --expected-value "262 rows" \
  --measured-value "261 rows" \
  --source-artifact "$REPORT_ID" \
  --json
```

Record Markdown notes:

```bash
uv run fieldbook note add \
  --entity-type experiment \
  --entity-id "$EXP_ID" \
  --type handoff \
  --title "Blocked on eval retry" \
  --body-file /tmp/fieldbook-handoff.md \
  --json
```

Use `--body` for short one-line notes, `--body-file` for multiline Markdown,
and `--body-stdin` when piping generated note content. Notes are capped; store
large reports, logs, notebooks, dashboards, and CSVs as artifacts instead.

## Reconcile External State

Prefer reconcile when refreshing state after context switches:

```bash
uv run fieldbook reconcile file --experiment "$EXP_ID" --path manifest.json --source iris-refresh --json
uv run fieldbook reconcile file --experiment "$EXP_ID" --path manifest.json --source iris-refresh --apply --json
```

Dry-run first for ambiguous or large updates. Apply is atomic for one manifest.
Reconcile rows default to `_op=upsert`; use `_op=archive` for soft-archiving
existing runs, jobs, artifacts, metrics, or notes. Never use `_op=delete`:
Fieldbook rejects destructive deletes. Include `sync_events` entries when a
refresh touches an external system such as W&B, Iris, GCS, or a dashboard:

```json
{
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

Use the reconcile log when debugging refreshes:

```bash
uv run fieldbook reconcile log --json
uv run fieldbook reconcile log --event "$RECONCILE_EVENT_ID" --json
uv run fieldbook reconcile log --source iris-refresh --operations --json
```

## W&B Writeback

Use writeback only when the user explicitly wants Fieldbook metrics mirrored to
W&B. Fieldbook stays the source of truth.

Always dry-run first:

```bash
uv run fieldbook writeback wandb --run "$RUN_ID" --metric "eval/*" --json
```

Apply requires an explicit writer and, on the first Fieldbook write to a target
W&B run, `--first-write-ok`:

```bash
uv run fieldbook writeback wandb \
  --run "$RUN_ID" \
  --metric "eval/*" \
  --apply \
  --writer real \
  --first-write-ok \
  --json
```

Default W&B keys are `fieldbook/<metric_name>` to avoid clobbering training
metrics. Use `--writer fake` for local smoke tests. Do not use `--raw-keys`
unless the user explicitly accepts overwriting risk; it requires
`--force-target`.

Inspect history with:

```bash
uv run fieldbook writeback log --target-system wandb --json
```

## Workflow Recipes And Dashboard Readiness

Use read-only workflow summaries before deciding on side effects:

```bash
uv run fieldbook experiment triage "$EXP_ID" --json
uv run fieldbook experiment closeout-checklist "$EXP_ID" --json
```

Workflow recipes live in `.codex/skills/fieldbook/references/workflows/`.
Templates live in `.codex/skills/fieldbook/templates/`. Treat them as editable
scaffolds; dry-run generated manifests before apply.

Dashboard readiness docs live in `docs/dashboard-readiness/`. Use
`v_artifacts_redacted_v1` for shared artifact displays and `v_artifacts_v1` only
when a local agent needs raw provenance.

Use adapters when the external system state is already available as a local
snapshot. Adapters are pure translators: they never read or mutate the ledger.
They produce reconcile manifests and optional debug files:

```bash
uv run fieldbook adapter list --json
uv run fieldbook adapter describe wandb-runs-json --json
uv run fieldbook adapter run wandb-runs-json \
  --input /tmp/wandb_runs.json \
  --output /tmp/wandb_runs_manifest.json \
  --debug-output /tmp/wandb_runs_debug.json \
  --json
uv run fieldbook reconcile file \
  --experiment "$EXP_ID" \
  --path /tmp/wandb_runs_manifest.json \
  --source wandb-refresh \
  --apply \
  --json
```

Run adapters with `--strict` when skipped rows should fail the refresh. Without
`--strict`, partial coverage succeeds and skipped rows are recorded in the
debug output. Treat adapter debug files as local-only diagnostics because they
include unredacted source rows.

Metric and artifact adapters require ledger IDs. If a snapshot only has
external run IDs, first run and apply `wandb-runs-json`, query `v_runs_v1` for
the ledger IDs, then produce the metric or artifact manifest.

## Audit And Portability

Run doctor before trusting stale context, collaborator exports, or a recovered
ledger:

```bash
uv run fieldbook doctor --json
uv run fieldbook doctor --list-checks --json
uv run fieldbook doctor --check stale-jobs --stale-hours 12 --json
uv run fieldbook doctor --check stale-sessions --stale-session-hours 24 --json
uv run fieldbook doctor --check job-recovery --stale-unknown-submit-hours 6 --json
uv run fieldbook doctor --check runs.expected_missing --json
uv run fieldbook doctor --check job_runs.stale_state --json
uv run fieldbook doctor --check validations --json
uv run fieldbook doctor --check ledger-locality --locality-recent-days 7 --json
```

`doctor` is read-only. It returns stable issue codes and suggested next
actions. If it finds errors, inspect the affected entities with stable SQL views
or `reconcile log`; do not repair by raw SQL writes. Use `--strict` when warning
findings should block automation.

Use full-ledger snapshots to move or share the entire local source of truth:

```bash
uv run fieldbook snapshot export --output /tmp/fieldbook-ledger.sqlite --json
uv run fieldbook snapshot inspect --input /tmp/fieldbook-ledger.sqlite --json
uv run fieldbook snapshot import --input /tmp/fieldbook-ledger.sqlite --output /tmp/restored.sqlite --json
```

Snapshots include notes, archived rows, sync events, local paths, and reconcile
history. Treat them as sensitive provenance artifacts. For collaborator metric
tables, prefer `export metrics-long`, `export runs-wide`, or `export coverage`.

## Query The Ledger

Use stable views for ad hoc analysis and dashboard prototypes:

```bash
uv run fieldbook db where --json
uv run fieldbook db path --json
uv run fieldbook sql --query "SELECT * FROM v_experiment_summary_v1" --limit 100 --json
uv run fieldbook sql --query "SELECT run_id, phase, has_checkpoint, metric_count FROM v_runs_progress_v1" --json
uv run fieldbook sql --file /tmp/query.sql --format csv > /tmp/results.csv
```

`fieldbook sql` is read-only and bounded. It rejects writes, DDL, PRAGMAs,
`ATTACH`, extension loading, and multiple statements. Prefer explicit
`--limit` values. Use `v_*_v1` views as the compatibility contract; avoid
depending on internal table shapes unless the user explicitly asks for a local
debug query. JSON output includes `envelope_version`, `columns`, `rows`,
`row_count`, and `truncated`.

## Export Collaborator Tables

```bash
uv run fieldbook export metrics-long --experiment "$EXP_ID" --output .experiments/metrics_long.csv --json
uv run fieldbook export runs-wide --experiment "$EXP_ID" --output .experiments/runs_wide.csv --metric eval/loss --json
uv run fieldbook export coverage --experiment "$EXP_ID" --metric eval/loss --json
```

Exports are recorded back into the ledger as `metric-table` artifacts.

## Optional Marin Reference

For Marin-specific conventions, see `references/marin.md` in this skill
directory. Keep those conventions optional; Fieldbook itself is repo-agnostic.
