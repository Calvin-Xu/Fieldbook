# Eval Refresh Workflow

Use this recipe when follow-up eval results are available as local files.

1. Export or materialize the refresh data to local JSON or CSV.
2. Run the matching `fieldbook adapter run ... --output <MANIFEST_PATH>`.
3. Inspect the manifest.
4. Run `fieldbook reconcile file --path <MANIFEST_PATH> --source <SOURCE_NAME> --json`.
5. Apply only after the dry-run plan is correct.
6. Run `fieldbook experiment workloop <EXPERIMENT_ID> --json` to check scoped
   status, freshness, and doctor output after the refresh.
7. If W and B summary mirroring is wanted, dry-run `fieldbook writeback wandb` first.
