## Context

Phase 5 is an integration sprint, not primarily a new storage capability. The real capability contract is portability: a coding agent should be able to use Fieldbook inside Marin without modifying Marin's dependencies or import graph.

## Decisions

### Decision: Invocation uses a sidecar Fieldbook checkout

Recommended development invocation from Marin:

```bash
uv run --project <FIELDBOOK_CHECKOUT> fieldbook <args>
```

This keeps Fieldbook out of Marin's `pyproject.toml`, pins behavior to the Fieldbook checkout and git SHA, and works from any downstream repo without activation state. The fallback for repeated local use is:

```bash
uv tool install --editable <FIELDBOOK_CHECKOUT>
fieldbook <args>
```

Use `--force` only when intentionally replacing an existing global tool install. The dogfood report must record which invocation was used, the working directory, the checkout path, and the Fieldbook git SHA.

### Decision: Dogfood uses hybrid replay plus in-flight local work

The dogfood ledger represents a realistic Marin local-only experiment selected from current work. It records replay-style provenance from existing local artifacts plus in-flight notes/actions, without launching live jobs. Candidate-mixture generation for a future production swarm is a suitable subject if it is still current, but the normative requirement is the ledger shape rather than that exact research topic.

The ledger must include at least:

- one experiment;
- at least two runs;
- at least one job row per major local activity;
- artifacts for generated files or reports;
- metrics or synthetic/local summary observations where meaningful;
- Markdown research, decision, next-action, and handoff notes;
- one reconcile dry-run and apply;
- one adapter run or an explicit adapter-gap issue-list entry;
- one doctor run;
- one snapshot export, inspect, and import round trip;
- one metrics export or coverage export.

### Decision: Dogfood artifacts are redacted by default

The real `.experiments/ledger.sqlite` in Marin is local-only and not committed. Committed dogfood artifacts are redacted Markdown/CSV/JSON summaries under the Fieldbook repo. They may include relative paths and fake/example external IDs, but not private W&B URLs, sensitive GCS paths, credentials, tokens, or raw adapter debug rows.

Committed dogfood artifacts live under `openspec/changes/marin-dogfood-stabilization/dogfood/`:

- `report.md`: redacted narrative report and command log;
- `issues.json`: structured follow-on issue list;
- optional small redacted CSV/JSON exports referenced by the report.

Full SQLite ledgers and snapshots stay under a gitignored downstream path such as the downstream repo's `.experiments/` tree and are not committed.

Redaction placeholders are stable:

- personal or repo-local absolute paths: `<FIELDBOOK_CHECKOUT>`, `<MARIN_CHECKOUT>`, or `<LOCAL_LEDGER>`;
- W&B URLs or run IDs that are private: `<WANDB_URL>` or `<WANDB_RUN>`;
- sensitive GCS or cloud paths: `<GCS_URI>`;
- credentials, tokens, and secrets: `<REDACTED_SECRET>`.

### Decision: Triage rule prevents scope creep

Findings are classified as:

- `fix-in-phase`: portability-blocking or data-correctness issues in Fieldbook itself;
- `follow-on-spec`: missing views, adapters, docs, or workflow surfaces that are useful but not blocking;
- `dashboard-prerequisite`: information model or stable-view requirement for the later dashboard;
- `wontfix`: expected limitation or out-of-scope request.

Only `fix-in-phase` findings are patched during Phase 5. Every issue-list entry must include `id`, `title`, `evidence`, `proposed_shape`, and `disposition`. Entries with `disposition=fix-in-phase` must also include `fixed_by_commit`.

### Decision: Dogfood report is the main deliverable

The report documents commands, redacted ledger path, Fieldbook SHA, downstream SHA, row counts, doctor findings, snapshot validation, exports produced, friction encountered, and dashboard prerequisites. The report is committed; the live Marin ledger is not.
