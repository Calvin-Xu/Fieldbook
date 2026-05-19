# Launch Plan Workflow

Use this recipe to record a planned experiment before any external job starts.

1. Create or identify the experiment with `fieldbook experiment create`.
2. Add one run per planned training or eval unit with `fieldbook run add`.
3. Add queued or planned jobs with `fieldbook job add`.
4. Attach a `next-action` note describing the first external action.
5. Run `fieldbook experiment triage <EXPERIMENT_ID> --json` before launching.
