## Why

Fieldbook can already reconcile manifests, but agents still need repeatable ways to turn external refresh snapshots into those manifests. The adapter layer should solve that without making Fieldbook depend on Marin, Iris, W&B, or any downstream repo. Adapters should be pure translators from local exported files to reconcile manifests.

## What Changes

- Add a small adapter framework that emits reconcile manifests and never writes the ledger directly.
- Add CLI commands to list, describe, and run adapters.
- Add stdlib-only read adapters for pre-exported Iris job summaries, W&B run metadata, metrics CSVs, and artifact JSON files.
- Add clear debug output for malformed or skipped input rows.
- Add fixtures simulating a Marin-style training run plus follow-up eval refresh without importing Marin.
- Document the two-step workflow: adapter output is inspected and then passed to `fieldbook reconcile file`.

## Capabilities

### New Capabilities

- `refresh-adapter-framework`: Pure local adapters that transform external refresh snapshots into reconcile manifests.

### Modified Capabilities

None. Reconcile remains the only ledger mutation path.

## Impact

- New adapter module and CLI subcommands.
- New fixture inputs and expected manifest/debug outputs.
- README and agent skill updates for adapter-driven refresh workflows.
