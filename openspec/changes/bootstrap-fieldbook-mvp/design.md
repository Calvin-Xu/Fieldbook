## Context

Fieldbook starts from an empty repository and should become a portable,
local-first experiment ledger for ML research agents. The first production
consumer is expected to be Marin, but the core must not depend on Marin, Iris,
GCS, or W&B. Those systems should appear as linked systems, artifacts, and
namespaced attributes.

The primary operator is a coding agent returning to an experiment after a
context switch. The human researcher is expected to give natural-language
instructions such as "check this experiment", "retry the failed jobs", or
"export the latest table"; the agent then uses Fieldbook to inspect and update
structured state. The agent needs a compact answer to: what was this
experiment, what runs/jobs exist, what is stale or failed, where are the
artifacts, and what should happen next?

## Goals / Non-Goals

**Goals:**

- Provide a repo-local SQLite ledger initialized under `.experiments/`.
- Provide a deterministic CLI that works in any ML repo with Python available.
- Track experiments, runs, jobs, artifacts, metrics, notes, custom fields, and
  provenance links.
- Make agent context recovery cheap through concise status and show commands.
- Support agent automation through stable JSON output and targeted drilldown
  commands that avoid loading entire experiment histories into context.
- Support incomplete metric coverage and follow-up eval jobs without corrupting
  provenance.
- Support project-specific metadata through namespaced JSON attributes.
- Provide export surfaces for collaborator-ready tables and custom dashboards.
- Include an initial reconcile pattern so agents can refresh state from
  external systems rather than relying only on perfect manual logging.
- Keep security simple: Fieldbook inherits repository and filesystem access
  controls and does not implement auth or encryption in the MVP.

**Non-Goals:**

- No background polling daemon in the MVP.
- No admin web UI in the MVP.
- No job scheduling or orchestration ownership.
- No full metric time-series storage in SQLite.
- No W&B two-way sync as a correctness dependency.
- No Marin-specific schema in the core.

## Decisions

### Decision: Build Fieldbook in its own repository

Fieldbook will be implemented directly in the Fieldbook repository, with Marin
used as the first integration target and test fixture.

Alternatives considered:

- Building inside Marin first would provide immediate realistic workflows, but
  it would likely bake in Marin-specific paths, Iris assumptions, and GCS/W&B
  conventions.
- Building Fieldbook first keeps portability as a forcing function.

### Decision: Use a repo-local SQLite database with WAL mode and foreign keys

The ledger lives at `.experiments/ledger.sqlite` by default. Initialization
enables WAL mode and records a schema version. Every connection enables
`PRAGMA foreign_keys = ON`; initialization records schema version in both a
schema metadata table and `PRAGMA user_version`.

Rationale:

- SQLite is portable, inspectable, and dashboard-friendly.
- WAL mode reduces write contention when multiple agents or shells touch the
  ledger.
- A local file avoids requiring a service account, daemon, server, or network.

### Decision: Use a small Python CLI with minimal runtime dependencies

The CLI will be implemented as a Python package with a `fieldbook` entry point.
The MVP should prefer the standard library (`argparse`, `sqlite3`, `json`,
`csv`) unless a dependency materially reduces implementation risk.

Rationale:

- A portable agent skill should not require a heavy runtime.
- Deterministic scripts are better than asking agents to rewrite SQL.
- A simple CLI is enough for agent-driven workflows and custom dashboards.
- Humans are not expected to memorize the CLI; commands should be easy for
  agents to call reliably from natural-language instructions.

### Decision: Keep runs in the model, but allow experiment-level jobs

The schema includes `experiments`, `runs`, and `jobs`. A job may attach to an
experiment even when no run is known yet; jobs that produce scientific
datapoints can later be linked to one or more runs.

Rationale:

- Marin-style work needs the run/datapoint concept: one run may have training,
  eval, collection, and repair jobs.
- Early workflows should not force users to create a perfect run object before
  logging useful execution state.

### Decision: Store custom metadata in namespaced JSON attributes

Core entities include an `attrs_json` column for project-specific fields such
as `marin.iris_job_path`, `marin.gcs_checkpoint_root`, or `slurm.job_id`.
Attribute keys are lowercase dotted identifiers. The prefix before the first
dot is the namespace; `fieldbook.*` is reserved for the core.

Rationale:

- JSON avoids a brittle entity-attribute-value schema.
- SQLite `json_extract` can support practical filtering.
- Namespaces keep portable core fields distinct from project adapters.

### Decision: Store summary metrics, not full time series

Metrics in SQLite are summary observations associated with a run, source job,
artifact, step, and metric name. Full metric histories remain in W&B, files, or
external artifacts and are linked through artifacts.

Rationale:

- Full time series can become large quickly.
- Fieldbook is a provenance and coordination ledger, not a metrics warehouse.
- Wide CSV exports can be generated from summary metrics when needed.

### Decision: Treat W&B as a linked mirror, not the source of truth

The ledger records W&B entity/project/run URLs and sync events. Follow-up eval
metrics may be mirrored to W&B, but MVP correctness does not depend on appending
to an original W&B run. A safer pattern is to create linked child runs with
`parent_run_id` or group metadata.

Rationale:

- W&B resume semantics and permissions are fragile across users and orgs.
- Fieldbook should still explain provenance if W&B state changes.
- The ledger can support both original-run pointers and follow-up-run pointers.

### Decision: Reconcile is a first-class workflow, not an afterthought

The MVP should include a small reconcile interface that can import or propose
updates from external state. The first adapters can be file/CSV based, with
Marin/Iris-specific probing added as an integration layer.

Rationale:

- The main failure mode is not schema design; it is write discipline.
- Agents and humans will launch jobs outside Fieldbook.
- Reconcile makes the ledger recoverable rather than purely aspirational.

### Decision: Use ULID-compatible sortable entity IDs

Core entities use lower-case type-prefixed ULID-compatible identifiers, such as
`exp_01hz...` or `job_01hz...`. The implementation should generate these with
a small internal helper using millisecond Unix time plus cryptographic random
bits, avoiding a mandatory runtime dependency.

Rationale:

- Sortable identifiers make CLI output and debugging easier.
- Type prefixes make agent output easier to read.
- Internal generation avoids adding a dependency for one primitive.

### Decision: Use SQL-only migrations for the MVP

Schema migrations are numbered SQL files applied in order inside a transaction.
Python code may orchestrate migration discovery and bookkeeping, but schema
changes themselves should be SQL files for the MVP.

Rationale:

- SQL migrations are inspectable and easy to review.
- Mixing SQL and Python migrations creates inconsistent transaction and dry-run
  behavior.

### Decision: Discover ledgers by walking upward from the current directory

CLI commands discover `.experiments/ledger.sqlite` by walking from the current
working directory toward the filesystem root. Users can override discovery with
`--ledger` or `FIELDBOOK_LEDGER`.

`fieldbook init` follows the same override rules. Without an override, it
creates the ledger at the Git repository root when run inside a Git repository,
and under the current working directory otherwise.

Rationale:

- Agents often run from subdirectories.
- Explicit overrides are still available for scripts and tests.

### Decision: Keep job status corrections flexible

Fieldbook records operational state; it is not a scheduler state machine. The
MVP validates known statuses but allows a job to move from any valid status to
any other valid status so agents can correct stale or mistaken records.

Rationale:

- Follow-up eval and retry workflows often discover that previous state was
  wrong or incomplete.
- Strict transition rules would make the ledger harder to repair.

### Decision: Use stable agent-readable exit codes

Commands exit with `0` for success, `1` for unexpected internal failures, `2`
for validation errors, `3` for not-found errors, `4` for ambiguity errors, and
`5` for ledger-busy errors.

Rationale:

- Coding agents need to distinguish recoverable user/input errors from
  unexpected failures.
- Stable exit codes are cheaper to parse than prose error messages.

## Risks / Trade-offs

- **Risk: Ledger rots because jobs are not logged.** → Add reconcile early,
  make status commands expose stale/missing state, and keep manual logging
  cheap.
- **Risk: Core becomes Marin-specific.** → Put Marin fields under namespaced
  attributes and keep adapters outside core schema.
- **Risk: Schema changes become painful.** → Add schema version and numbered
  migrations in the first implementation phase.
- **Risk: JSON attributes become unqueryable sprawl.** → Reserve JSON for
  project-specific metadata; keep identity, status, timestamps, and provenance
  links as first-class columns.
- **Risk: W&B sync creates inconsistent truth.** → Treat external sync as a
  recorded side effect and keep SQLite provenance authoritative.
- **Risk: CLI output overwhelms agent context.** → Make default commands
  concise, with explicit `--json`, `--verbose`, or entity-specific drilldowns.
- **Risk: Human-facing ergonomics dominate the design.** → Keep the CLI
  scriptable and deterministic first; polished human UI remains a non-goal for
  the MVP.

## Migration Plan

There is no existing Fieldbook state. The initial migration creates the schema
from scratch, records schema version `1`, and enables WAL mode during
initialization.

If a future schema change is needed, it should add a numbered migration and a
test that initializes a fresh ledger and upgrades a prior-version fixture.

## Open Questions

- Should notes be stored only in SQLite, or also optionally mirrored to
  repo-local Markdown files for easier review?
- Should the first project-specific reconcile adapter target Marin/Iris job
  summaries or stay file-manifest-only until the second change?
- Should stable Fieldbook skill packaging live in a second change immediately
  after the CLI MVP, or wait until after Marin dogfooding?
