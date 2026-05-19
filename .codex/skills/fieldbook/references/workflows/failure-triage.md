# Failure Triage Workflow

Use this recipe when jobs failed or appear stale.

1. Run `fieldbook experiment triage <EXPERIMENT_ID> --json`.
2. Inspect failed and stale jobs.
3. Add a `debug` note with the suspected cause and retry plan.
4. Reconcile external status updates before changing local job state manually.
5. Resolve the debug note only after the recovery path is complete.
