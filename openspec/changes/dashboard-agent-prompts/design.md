## Context

Fieldbook is agent-operated. The human user usually does not run the
Fieldbook CLI directly; they inspect state and give natural-language
instructions to an ongoing coding agent. The dashboard should therefore help
the human identify what needs attention and copy a short instruction for the
agent, not teach the human CLI workflows or execute actions itself.

## Goals / Non-Goals

**Goals:**

- Make the dashboard a compact schema-aware experiment scan surface.
- Surface Fieldbook's data model through experiment grouping, run/datapoint
  progress, jobs, notes, artifacts, leases, validations, and external links.
- Generate short copyable instructions for coding agents.
- Keep the Fieldbook skill as the source of workflow best practices.
- Keep all dashboard routes read-only and GET-only.

**Non-Goals:**

- No prompt sending to Codex, Claude Code, IPC, or external services.
- No free-text prompt composer.
- No dashboard writes, command execution, refresh execution, job launching, or
  agent invocation.
- No Vue/Tailwind frontend in this phase.
- No Marin-specific dashboard dependency.

## Decisions

### Decision: Closed prompt catalog

Fieldbook exposes a fixed catalog of prompt actions. Each action has a stable
id, title, description, applicability logic, issue summary, one read-only entry
command, and a concise constraint. The initial actions are:

- `refresh-external-state`;
- `resolve-failed-jobs`;
- `fix-failing-validations`;
- `write-handoff`;
- `resolve-stale-leases`;
- `review-open-notes`.

There is no free-text prompt builder in the dashboard or CLI.

The catalog version is `prompts_v1`, implemented as an inline Python catalog in
`src/fieldbook/prompts.py`. Adding a prompt action requires adding catalog
metadata, applicability logic, a prompt template, tests, and OpenSpec coverage;
there is no runtime registration or user-provided action text.

| Action | Applicability, from stable views | Entry command | Constraint |
| --- | --- | --- | --- |
| `refresh-external-state` | `v_dashboard_experiments_v1.active_job_count > 0` | `fieldbook experiment workloop <id> --json` | Refresh status intentionally before acting on running or externally updated work. |
| `resolve-failed-jobs` | `v_dashboard_experiments_v1.blocking_failed_job_count > 0` or `v_dashboard_experiments_v1.recovery_in_progress_failed_job_count > 0` | `fieldbook experiment workloop <id> --json` | Inspect retry lineage and executor skip semantics before submitting retries. |
| `fix-failing-validations` | `v_dashboard_experiments_v1.failing_validation_count > 0` | `fieldbook validation list --entity-type experiment --entity-id <id> --json` | Treat validations as evidence and record fixes or errata through Fieldbook. |
| `write-handoff` | `v_dashboard_experiments_v1.handoff_status IN ('missing', 'stale')` | `fieldbook experiment workloop <id> --json` | Write a bounded Markdown handoff before context switching or archiving. |
| `resolve-stale-leases` | `v_dashboard_experiments_v1.stale_lease_count > 0` | `fieldbook lease list --entity-type experiment --entity-id <id> --json` | Inspect ownership before releasing or taking over any lease. |
| `review-open-notes` | `v_dashboard_notes_v1` has an open `handoff`, `next-action`, or `debug` note for the experiment | `fieldbook experiment context <id>` | Review open notes and update or resolve them after acting. |

`prompt actions` hides inapplicable actions by default. `prompt build` rejects
an inapplicable action with a validation error rather than rendering stale or
misleading instructions.

### Decision: Shared prompt builder

Prompt rendering lives in a shared module used by both CLI and dashboard.
The CLI exposes:

```text
fieldbook prompt list --json
fieldbook prompt actions <experiment> --json
fieldbook prompt build <action> <experiment> --json
```

Text output for `prompt build` is the Markdown prompt body. JSON output includes
an envelope with:

```json
{
  "envelope_version": 1,
  "catalog_version": "prompts_v1",
  "action_id": "resolve-failed-jobs",
  "title": "Resolve failed jobs",
  "experiment_id": "exp_...",
  "experiment_name": "Example",
  "applicable": true,
  "issue_summary": "1 failed job needs attention.",
  "entry_command": "fieldbook experiment workloop exp_... --json",
  "constraints": ["Inspect retry lineage before launching retries."],
  "body": "..."
}
```

### Decision: Prompt content contract

Each prompt identifies the experiment by name and id, states one dashboard
issue, says to use the Fieldbook skill, includes exactly one read-only
`fieldbook ...` entry command, and includes concise constraints.

Prompts must not include mutation flags or mutation-oriented options:
`--apply`, `--force`, `--archive`, `--errata`, `--errata-force`,
`--checkpoint`, `--update-existing`, or `--retry-of`. Prompts must also exclude
the Fieldbook skill body, full note bodies, raw `attrs_json`, local filesystem
paths, and large row dumps.

The only allowed entry command forms are:

- `fieldbook experiment workloop <id> --json`
- `fieldbook experiment status <id> --json`
- `fieldbook experiment context <id>`
- `fieldbook lease list --entity-type experiment --entity-id <id> --json`
- `fieldbook validation list --entity-type experiment --entity-id <id> --json`
- `fieldbook refresh list-sources --json`

`fieldbook refresh list-sources --json` is reserved for prompt actions that
need to enumerate available refresh sources without running a refresh. The
`review-open-notes` action intentionally uses Markdown text output from
`fieldbook experiment context <id>` because agents need readable note bodies
for note review.

Rendered prompt bodies are capped at 1500 characters. Prompt rendering reuses
`fieldbook.doctor.SECRET_PATTERNS`; if the rendered text matches a suspected
secret pattern, prompt building fails with a validation error. Prompt rendering
also rejects a body with more than 200 contiguous characters copied from
`.codex/skills/fieldbook/SKILL.md`.

### Decision: Dashboard prompt cards

The dashboard renders applicable prompt action cards on experiment detail
pages. Cards show the action title, issue summary, short constraint, and a
native `<details><summary>Preview agent instruction</summary><pre>...</pre></details>`
area containing the prompt body. The dashboard never sends the prompt anywhere.
Phase 20 does not need JavaScript for prompt preview or copy behavior.

### Decision: Ergonomic schema-aware dashboard

The root page is an experiment index with a compact category sidebar grouped by
needs attention, active, stale, and archived. Archived experiments are collapsed
by default. The same sidebar stays visible on experiment detail pages so a human
can switch between experiments without returning to the root page. Detail pages
use compact header metrics and a horizontal tab bar: overview, runs, jobs,
leases, validations, freshness, notes, artifacts, and external links. The
overview tab contains attention cards and agent instruction cards; other tabs
render one entity family at a time.

Vertical space is treated as scarce. The sidebar is only for experiment
switching and category navigation; experiment detail navigation is horizontal
tabs rather than stacking every section on a single page. Each tab query should
load only the stable-view data it needs. Entity sections omit page-context
columns such as `experiment_id` and render domain-specific cards or compact rows
instead of generic raw tables.

Minimum entity renderers are:

- Runs: run id/name, kind, status/progress summary, and latest update.
- Jobs: job id/name, status, retry/recovery state, and external link if present.
- Notes: note id, type, status, title, preview, and timestamp only.
- Artifacts: artifact id, type, redacted/display URI, freshness hint, and
  external system/id if present.
- Leases: lease id, target entity, owner/session, heartbeat/release state, and
  stale/expired status label.
- Validations: validation id, check name, status, measured/expected value, and
  timestamp.
- External links: system, target entity, and URL.

The experiment index renders compact experiment cards with name, id, status
badge, and count pills rather than every stable-view column.

### Decision: Stable views remain the data boundary

Dashboard handlers and prompt builders read stable `_v1` views or redacted
views where available. Artifact display should prefer `v_artifacts_redacted_v1`
when available and otherwise use existing dashboard `_v1` artifact surfaces. If
the current views do not expose enough information, the implementation adds or
extends stable views rather than querying internal tables from dashboard or
prompt code.

## Risks / Trade-offs

- **Risk: dashboard becomes an agent launcher** -> No send endpoints, no IPC,
  no POST routes, and no command execution.
- **Risk: prompts drift from best practices** -> Prompts reference the
  Fieldbook skill instead of embedding workflow instructions.
- **Risk: prompt leakage** -> Use bounded summaries, avoid local paths/raw
  attrs/full note bodies, and reject suspected secret patterns.
- **Risk: visual clutter** -> Prefer compact cards, category sidebar navigation,
  horizontal detail tabs, and entity-specific summaries over generic wide
  tables.
