# Marin Fieldbook Usage Notes

These are optional conventions for Marin-style experiments. They are not core
Fieldbook requirements.

- Use `marin.issue=<number>` for linked GitHub experiment issues.
- Use `marin.scale=<scale-key>` for historical scale keys such as `300m_6b`.
- Use `marin.checkpoint_root=<gcs-uri>` on runs or artifacts when checkpoints
  back the datapoint.
- Use Iris job paths as `external_system=iris`, `external_id=/user/job-name`.
- Use W&B run identifiers as `external_system=wandb`, `external_id=<run-id>`.
- Record follow-up eval jobs as separate jobs linked to the same run as the
  original training job.
- If follow-up eval metrics are also synced to W&B, record that as a
  `sync_event` or as an artifact/attribute; the ledger remains authoritative.
