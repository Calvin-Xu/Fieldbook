# Marin Dogfood Report

## Summary

Dogfood target: local-only Marin production-swarm mixture-design planning.

Fieldbook was invoked from the Marin checkout without adding Fieldbook to
Marin's `pyproject.toml`:

```bash
env -u VIRTUAL_ENV uv run --project <FIELDBOOK_CHECKOUT> fieldbook ...
```

The live ledger and full SQLite snapshots were kept under `<LOCAL_LEDGER>` in
Marin's gitignored `.experiments/` tree. They were not committed.

## Provenance

| Field | Value |
| :--- | :--- |
| Fieldbook checkout | `<FIELDBOOK_CHECKOUT>` |
| Fieldbook SHA | `43e8f6d530cc8fdb12648523cdf882e3c296eaeb` |
| Downstream repo | `<MARIN_CHECKOUT>` |
| Downstream SHA | `afa7e5a12294872df810546ed380826896ecf3b5` |
| Invocation | `uv run --project <FIELDBOOK_CHECKOUT> fieldbook` |
| Ledger | `<LOCAL_LEDGER>` |

## Ledger Contents

| Entity | Count |
| :--- | ---: |
| Experiments | 1 |
| Runs | 2 |
| Jobs | 2 |
| Artifacts | 2 |
| Metrics | 4 |
| Notes | 4 |
| Reconcile events | 1 |
| Reconcile operations | 2 |
| Sync events | 0 |

Experiment status showed two runs, one succeeded local job, one intentionally
running local planning job, four open notes, and no failed jobs.

## Exercised Workflows

- Created a local dogfood ledger from the Marin checkout with the sidecar
  Fieldbook invocation.
- Recorded a realistic experiment with baseline and candidate runs, local jobs,
  artifacts, scalar metrics, and Markdown research/decision/next-action/handoff
  notes.
- Ran `metrics-csv` adapter on `<LOCAL_LEDGER>/adapter/metrics.csv` to create
  a reconcile manifest.
- Ran reconcile dry-run and apply for the adapter metrics manifest.
- Exported metric coverage.
- Ran `experiment status` and `experiment context`.
- Ran `doctor --json`.
- Ran snapshot export, inspect, and import.
- Queried stable views through `fieldbook sql`.

## Doctor

`doctor --json` returned:

| Field | Value |
| :--- | :--- |
| `ok` | `true` |
| `issue_count` | `0` |
| `schema_version` | `6` |

All default checks ran: `attrs-json`, `note-entity`, `local-artifacts`,
`stale-jobs`, `external-ids`, `sync-events`, and `reconcile-log`.

## Snapshot

Snapshot export, inspect, and import all succeeded.

| Table | Count |
| :--- | ---: |
| `experiments` | 1 |
| `runs` | 2 |
| `jobs` | 2 |
| `artifacts` | 2 |
| `metrics` | 4 |
| `notes` | 4 |
| `reconcile_events` | 1 |
| `reconcile_operations` | 2 |

The committed report intentionally excludes the real snapshot path and metadata
path because full-ledger snapshots contain local paths and notes.

## Exports

Metric coverage export produced four rows:

| Metric | Run Count | Total Runs | Coverage |
| :--- | ---: | ---: | ---: |
| `dogfood/local_context_jobs` | 1 | 2 | 0.5 |
| `dogfood/local_design_jobs` | 1 | 2 | 0.5 |
| `dogfood/planned_partitions` | 1 | 2 | 0.5 |
| `dogfood/planned_swarm_points` | 1 | 2 | 0.5 |

## Findings

No `fix-in-phase` correctness blockers were found.

Two follow-on issues are captured in `issues.json`:

- `global-ledger-option-ergonomics`: `--ledger` is subcommand-scoped, so wrapper
  scripts must append it after the command. This is workable but easy to get
  wrong. This phase improved README and agent-skill guidance; accepting
  `--ledger` before the subcommand remains a follow-on CLI ergonomics change.
- `dashboard-redaction-local-paths`: status/export payloads naturally include
  absolute local artifact paths. A dashboard needs a redaction or locality
  presentation layer before data is shared.

## Interpretation

The sidecar invocation model is viable. It let Marin use Fieldbook without any
dependency change and exercised the main pre-dashboard surfaces from a real
downstream working tree. The main dashboard prerequisite is not storage; it is a
clear presentation/redaction layer over already-captured local provenance.
