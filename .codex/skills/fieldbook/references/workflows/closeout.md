# Closeout Workflow

Use this recipe when an experiment has a stable conclusion.

1. Run `fieldbook experiment closeout-checklist <EXPERIMENT_ID> --json`.
2. Add any missing metric-table exports.
3. Resolve obsolete handoff, next-action, and debug notes.
4. Add a final `decision` note with the outcome and follow-up issues.
5. Archive the experiment only if the user explicitly asks.
