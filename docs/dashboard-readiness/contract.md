# Dashboard Readiness Contract

This contract defines the first dashboard phase. It does not build the UI.

## Target Screens

- Experiment portfolio: list active experiments and attention counts.
- Experiment drilldown: show one experiment's runs, jobs, artifacts, metrics,
  notes, reconcile events, and sync events.

## Entity Mapping

| UI Entity | Stable View |
| :--- | :--- |
| Experiment | `v_experiments_v1`, `v_experiment_summary_v1` |
| Run | `v_runs_v1`, `v_run_summary_v1` |
| Job | `v_jobs_v1`, `v_jobs_needing_attention_v1` |
| Artifact | `v_artifacts_redacted_v1` by default, `v_artifacts_v1` for local agents |
| Metric | `v_metrics_long_v1`, `v_metric_coverage_v1` |
| Note | `v_notes_v1` |
| ReconcileEvent | `v_reconcile_log_v1` |
| SyncEvent | `v_sync_events_v1`, plus W and B coverage views |

## Redaction Rules

Dashboards and shared payloads should use `v_artifacts_redacted_v1`. Local
filesystem artifacts display as `local:<artifact_id>/<basename>`. Remote artifact
URIs display unchanged.

`v_notes_v1` includes note bodies, and `v_sync_events_v1` includes external
identifiers and payload summaries. Treat both as authenticated operator views,
not unauthenticated public surfaces.

## Acceptance Criteria For The Future Dashboard

- Reads only stable `v_*_v1` views.
- Uses redacted artifact display by default.
- Does not query `v_artifacts_v1` from committed dashboard sample queries.
- Keeps all queries bounded with explicit `LIMIT`.
- Does not expose raw local filesystem paths in shared payloads.
- Does not mutate the ledger.

## Non-Goals

- No write-side dashboard operations.
- No realtime polling.
- No authentication system.
- No broad analytics beyond the target screens.
