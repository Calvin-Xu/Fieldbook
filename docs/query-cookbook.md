# Fieldbook Query Cookbook

Use stable `v_*_v1` views for agent debugging, custom dashboards, and ad hoc
analysis. Internal tables may change before v1; the views are the compatibility
contract.

## Experiment Resume Summary

```sql
SELECT *
FROM v_experiment_summary_v1
ORDER BY updated_at DESC;
```

## Jobs Needing Attention

```sql
SELECT experiment_id, job_id, name, status, updated_at, external_system, external_id
FROM v_jobs_needing_attention_v1
ORDER BY updated_at ASC;
```

## Latest Artifact Per Type

```sql
SELECT experiment_id, run_id, type, uri, updated_at
FROM v_artifact_latest_per_type_v1
ORDER BY experiment_id, run_id, type;
```

## Metric Coverage

```sql
SELECT experiment_id, metric_name, run_count, missing_run_count
FROM v_metric_coverage_v1
ORDER BY metric_name;
```

## Reconcile Events

```sql
SELECT event_id, source, created_at, counts_json
FROM v_reconcile_log_v1
ORDER BY created_at DESC
LIMIT 20;
```

## W&B Sync Coverage

```sql
SELECT run_id, run_name, external_id, latest_wandb_sync_status, latest_wandb_sync_at
FROM v_wandb_sync_coverage_v1
ORDER BY latest_wandb_sync_at DESC;
```

## W&B Writeback Coverage

```sql
SELECT source_run_id, source_entity_id, target_identifier, target_field, latest_status, attempt_count
FROM v_wandb_writeback_coverage_v1
ORDER BY latest_event_at DESC;
```

Run examples through the read-only SQL command:

```bash
uv run fieldbook sql --query "SELECT * FROM v_experiment_summary_v1" --limit 100 --json
uv run fieldbook sql --file docs/query-cookbook-example.sql --format csv > /tmp/fieldbook.csv
```
