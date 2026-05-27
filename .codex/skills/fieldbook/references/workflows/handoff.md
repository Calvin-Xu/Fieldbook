# Handoff Workflow

Use this recipe before switching away from an experiment.

1. Run `fieldbook experiment workloop <EXPERIMENT_ID> --json`.
2. Resolve or record any scoped doctor issues that affect handoff quality.
3. Record current state in a Markdown `handoff` note.
4. Record the next concrete action in a `next-action` note.
5. Link important reports, manifests, or metric tables as artifacts.
6. Verify the handoff with `fieldbook experiment workloop <EXPERIMENT_ID>
   --checkpoint --body-file <HANDOFF_MD> --json` when a durable checkpoint is
   needed, otherwise with `fieldbook experiment context <EXPERIMENT_ID>`.
