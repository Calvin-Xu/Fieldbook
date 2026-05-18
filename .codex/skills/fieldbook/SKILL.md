# Fieldbook

Use this skill when an ML research repo has Fieldbook installed and the user
asks to track experiments, recover context, reconcile jobs, document failures,
or export collaborator-ready data.

## Operating Principles

- Treat Fieldbook's SQLite ledger as the local source of truth.
- Use JSON output for agent workflows: pass `--json` on `list`, `show`,
  `status`, `create`, and `add` commands.
- Record external systems as links and provenance, not as the source of truth.
- Keep notes short and structured. Use `note_type=next-action` for work the
  next agent should perform.
- Do not dump the entire ledger into context. Start with one experiment's
  `status`, then drill into specific runs, jobs, artifacts, metrics, or notes.

## Initialize A Ledger

From a repo root or subdirectory:

```bash
uv run fieldbook init --json
```

If the repo has no Git root, this creates `.experiments/ledger.sqlite` under
the current working directory. Use `--ledger` or `FIELDBOOK_LEDGER` only when
the user wants an explicit non-default ledger.

## Context Switch Back To An Experiment

```bash
uv run fieldbook experiment list --json
uv run fieldbook experiment status "$EXP_ID" --json
```

Use the status payload to identify stale running jobs, failed jobs, key
artifacts, unresolved next actions, and recent notes. Then inspect only the
relevant entities:

```bash
uv run fieldbook job show "$JOB_ID" --json
uv run fieldbook run show "$RUN_ID" --json
uv run fieldbook note list --entity-type experiment --entity-id "$EXP_ID" --status open --json
```

## Record Work

Create an experiment:

```bash
uv run fieldbook experiment create \
  --name "short research thread name" \
  --description "one-sentence objective" \
  --tag marin \
  --attr marin.issue=5416 \
  --json
```

Record a run and job:

```bash
uv run fieldbook run add --experiment "$EXP_ID" --name "$RUN_NAME" --json
uv run fieldbook job add --run "$RUN_ID" --status running --launcher iris --external-system iris --external-id "$JOB_PATH" --json
```

Update status flexibly when the external system changes:

```bash
uv run fieldbook job update-status "$JOB_ID" --status succeeded --json
```

## Reconcile External State

Prefer reconcile when refreshing state after context switches:

```bash
uv run fieldbook reconcile file --experiment "$EXP_ID" --path manifest.json --source iris-refresh --json
uv run fieldbook reconcile file --experiment "$EXP_ID" --path manifest.json --source iris-refresh --apply --json
```

Dry-run first for ambiguous or large updates. Apply is atomic for one manifest.

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
