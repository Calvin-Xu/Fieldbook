## Context

Phase 7 intentionally stops before dashboard UI. It should not create a daemon,
admin server, or broad workflow orchestrator. Fieldbook remains a local-first
agent ledger. Agents can already compose commands, run SQL, reconcile external
state, and write Markdown notes.

The right pre-dashboard scope is therefore:

- make common agent command sequences easier to rediscover;
- add only read-only summary commands where the shape is already proven by
  `experiment status` and `experiment context`;
- define the read-only dashboard contract without building the dashboard;
- implement artifact locality/redaction because dogfood identified it as a real
  dashboard blocker.

## Goals / Non-Goals

**Goals:**

- Keep workflow packs side-effect free.
- Provide Markdown and JSON summaries suitable for agent context switching.
- Provide recipe/template files that agents can copy, edit, and run manually.
- Add a redacted artifacts view for dashboard/shared output.
- Pin a minimum useful dashboard contract with executable sample queries.
- Test docs/templates so they do not rot.

**Non-Goals:**

- No dashboard UI.
- No side-effecting pack commands.
- No lifecycle state machine or closeout table.
- No Marin-specific code paths.
- No automatic reconcile/writeback/apply behavior.
- No cross-experiment analytics beyond the minimum list/drilldown contract.

## Decisions

### Decision: Workflow-pack commands are read-only summaries

`experiment triage` and `experiment closeout-checklist` follow the established
`experiment context` pattern: they read the ledger and emit bounded Markdown or
JSON. They do not mutate the ledger, run reconcile, run writeback, archive
experiments, or create notes. Agents must explicitly run follow-up commands.

### Decision: Workflow recipes live in files, not orchestration code

Recipes for launch planning, eval refresh, failure triage, collaborator export,
handoff, and closeout are committed Markdown files under the Fieldbook skill
references directory. Manifest and note templates live under templates. Tests
execute or validate the example commands/templates against a fixture ledger.

### Decision: Closeout is a checklist, not a state

Research experiments rarely close cleanly. `experiment closeout-checklist`
reports missing pieces such as unresolved notes, failed/stale jobs, missing
snapshot/export artifacts, and doctor issues. The agent may attach the result as
a `decision` note manually. Fieldbook does not add a new closeout status.

### Decision: Dashboard readiness targets two screens

The minimum useful dashboard is:

- experiment portfolio list;
- single-experiment drilldown.

The contract maps each UI entity to stable views and sample queries. Anything
beyond those screens is explicitly deferred.

### Decision: Artifact locality/redaction is code

The dashboard contract is not credible if it only says local paths should be
redacted. Phase 7 adds a locality classifier for artifact URIs and a stable view
that exposes:

- `uri_locality`: `local-fs`, `gcs`, `s3`, `wandb`, `http`, `other`;
- `display_uri`: redacted/locality-aware display string;
- original `uri` remains available in the internal table and existing
  `v_artifacts_v1`.

The redacted view is the default dashboard/shared surface. Agents can still use
the original artifact view when local provenance is necessary.

Locality is implemented as a pure SQL `CASE` expression inside
`v_artifacts_redacted_v1`. The view must work for external SQLite readers and
future dashboard processes without requiring a Python SQLite UDF. The view
exposes an effective experiment association by coalescing direct artifact
experiment ownership, run membership, and job/run membership.

The redacted artifact view does not expose the raw `uri` column. Its stable
columns are:

- `artifact_id`
- `experiment_id`
- `run_id`
- `job_id`
- `type`
- `uri_locality`
- `display_uri`
- `content_hash`
- `created_at`
- `updated_at`
- `attrs_json`

For local filesystem artifacts, `display_uri` is exactly
`local:<artifact_id>/<basename>`. This keeps a useful label without exposing the
directory and avoids pure-basename collisions. For `file://` URIs, the basename
comes from the URL path. For remote artifacts, `display_uri` preserves the
original URI. `http://` and `https://` are intentionally collapsed into
`uri_locality='http'`. `wandb:` is reserved for forward-compatible W&B artifact
URIs even though current fixtures do not produce it.

### Decision: Committed examples use placeholders

Recipes, templates, and dashboard query docs must not contain private local
paths, real W&B URLs, or real cloud buckets. Tests grep committed examples for
known private patterns and require placeholders such as `<LEDGER>`,
`<EXPERIMENT_ID>`, and `<ARTIFACT_URI>`.

The concrete forbidden patterns are `/Users/`, `/home/`, `/private/`,
`wandb.ai/`, `gs://`, `s3://`, `api[_-]?key`, `token`, `password`, `secret`,
`Bearer `, `ghp_`, and `AKIA[0-9A-Z]{16}`. Placeholders may include these words
only when wrapped in angle brackets, for example `<WANDB_URL>` or
`<GCS_ARTIFACT_URI>`.

### Decision: File locations are stable

Workflow recipes live in `.codex/skills/fieldbook/references/workflows/`.
Reusable templates live in `.codex/skills/fieldbook/templates/`. Dashboard
readiness docs live in `docs/dashboard-readiness/`, with sample SQL under
`docs/dashboard-readiness/queries/`.

### Decision: Template tests use named fixture placeholders

Template tests substitute placeholders from a fixture ledger with
`<EXPERIMENT_ID>`, `<RUN_ID>`, `<JOB_ID>`, `<ARTIFACT_URI>`, `<METRIC_NAME>`,
and `<NOTE_BODY>`. Reconcile templates must dry-run successfully after that
substitution; note templates must pass note validation after placeholder
substitution.

## Risks / Trade-offs

- **Risk: packs become speculative** -> Restrict code packs to two read-only
  summaries and keep all other packs as recipes/templates.
- **Risk: docs rot** -> Execute sample queries and validate templates in tests.
- **Risk: redaction hides useful provenance** -> Keep raw `v_artifacts_v1`;
  dashboard/shared consumers should use the redacted view by default.
- **Risk: future UI needs different columns** -> Add `_v2` views later rather
  than mutating the `_v1` contract.
