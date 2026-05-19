# Handoff Workflow

Use this recipe before switching away from an experiment.

1. Run `fieldbook experiment triage <EXPERIMENT_ID> --json`.
2. Record current state in a Markdown `handoff` note.
3. Record the next concrete action in a `next-action` note.
4. Link important reports, manifests, or metric tables as artifacts.
5. Verify the handoff with `fieldbook experiment context <EXPERIMENT_ID>`.
