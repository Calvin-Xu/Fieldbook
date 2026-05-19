## Why

Fieldbook is intended to be portable and agent-operated from ML research repos without becoming a dependency of those repos. Marin is the first serious dogfood target. Before building a dashboard, Fieldbook needs one realistic external-repo exercise that validates install ergonomics, context recovery, reconcile/adapters, doctor, snapshots, exports, and agent handoff surfaces.

## What Changes

- Pin the recommended no-pyproject install/invocation contract for using Fieldbook from another repo.
- Dogfood Fieldbook from the Marin checkout on one realistic local-only experiment ledger.
- Produce a redacted dogfood report artifact and a structured issue list for dashboard prerequisites and follow-on improvements.
- Patch only portability-blocking or data-correctness issues discovered during dogfood; defer ergonomics/dashboard wishes to the issue list.

## Out Of Scope

- No dashboard UI.
- No live training or eval jobs.
- No Fieldbook dependency added to Marin's `pyproject.toml`.
- No broad new adapters unless dogfood reveals a portability-blocking gap.
- No time-series metric ingestion.
- No committed real Marin ledger snapshot containing private paths or URLs.
