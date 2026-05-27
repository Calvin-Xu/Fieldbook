# Launch Protocol

Use this recipe before any live external submission.

1. Run `fieldbook db where --json` and confirm the ledger path and ledger ID.
2. Run `fieldbook session start` or `fieldbook session switch` for the active
   experiment.
3. Run `fieldbook experiment workloop <EXPERIMENT_ID> --json` and inspect
   scoped doctor issues before launching.
4. Create the Fieldbook job with `--status submitting`, the intended
   `--external-system`, and the exact `--command` before invoking the external
   launcher.
5. Invoke the external launcher outside Fieldbook.
6. If the launcher returns a reliable external identifier, run
   `fieldbook job update-status <JOB_ID> --status queued|running
   --external-system <SYSTEM> --external-id <EXTERNAL_ID> --json`.
7. If the launcher times out or the acknowledgment is ambiguous, run
   `fieldbook job update-status <JOB_ID> --status unknown_submit
   --failure-reason "<reason>" --json`.
8. If the external system explicitly rejects the submission, run
   `fieldbook job update-status <JOB_ID> --status failed
   --failure-reason "submission rejected: <details>" --json`.
9. On resume, run `fieldbook experiment workloop <EXPERIMENT_ID> --refresh
   <SOURCE> --json` first, inspect the manifest paths, then rerun with `--apply`
   when the dry-run is correct.

Do not defer job creation until after a successful external launch. The point of
Fieldbook is to preserve the attempted action even when the launcher is
interrupted or ambiguous.
