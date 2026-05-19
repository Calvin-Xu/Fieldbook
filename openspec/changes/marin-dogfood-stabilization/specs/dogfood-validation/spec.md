## ADDED Requirements

### Requirement: Dogfood a realistic external repo ledger
The system SHALL exercise Fieldbook from Marin on a local-only realistic experiment ledger.

#### Scenario: Create dogfood ledger outside committed source
- **WHEN** the dogfood workflow initializes a ledger in Marin
- **THEN** the real SQLite ledger and full-ledger snapshot files are kept under a gitignored downstream path and are not committed to Fieldbook or Marin

#### Scenario: Record realistic experiment entities
- **WHEN** an agent reads the committed dogfood report
- **THEN** it shows the ledger contained at least one experiment, at least two runs, jobs for major local activities, artifacts, scalar summary metrics, Markdown notes, reconcile events, and exports

#### Scenario: Exercise audit and portability surfaces
- **WHEN** an agent reads the committed dogfood report
- **THEN** it shows doctor was run with JSON output and snapshot export, inspect, and import were run against the dogfood ledger

#### Scenario: Exercise reconcile and adapter surfaces
- **WHEN** an agent reads the committed dogfood report
- **THEN** it shows one reconcile dry-run and apply, plus either one adapter run or a structured adapter-gap issue-list entry

### Requirement: Produce redacted dogfood findings
The system SHALL commit redacted dogfood findings suitable for future agents and dashboard planning.

#### Scenario: Write dogfood report
- **WHEN** dogfood completes
- **THEN** it writes `openspec/changes/marin-dogfood-stabilization/dogfood/report.md` with commands, row counts, artifacts, doctor findings, snapshot status, export status, and interpretation

#### Scenario: Write structured issue list
- **WHEN** dogfood finds issues or dashboard prerequisites
- **THEN** it writes `openspec/changes/marin-dogfood-stabilization/dogfood/issues.json` with `envelope_version` and `items[]`

#### Scenario: Issue list schema is stable
- **WHEN** `issues.json` contains an item
- **THEN** the item has `id`, `title`, `evidence`, `proposed_shape`, and `disposition`, where disposition is one of `fix-in-phase`, `follow-on-spec`, `dashboard-prerequisite`, or `wontfix`

#### Scenario: Fix-in-phase issues point to commits
- **WHEN** dogfood is finalized
- **THEN** every `issues.json` item with `disposition="fix-in-phase"` includes a Fieldbook commit SHA that landed during this change

#### Scenario: Avoid private data in committed artifacts
- **WHEN** dogfood artifacts are committed
- **THEN** they exclude private W&B URLs, sensitive GCS paths, credentials, tokens, raw adapter debug rows, and full SQLite snapshots

#### Scenario: Use stable redaction placeholders
- **WHEN** committed dogfood artifacts refer to redacted provenance
- **THEN** they use stable placeholders such as `<FIELDBOOK_CHECKOUT>`, `<MARIN_CHECKOUT>`, `<WANDB_URL>`, `<GCS_URI>`, and `<LOCAL_LEDGER>` rather than personal absolute paths or private URLs
