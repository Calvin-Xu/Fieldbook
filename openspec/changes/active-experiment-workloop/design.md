## Context

Fieldbook's command set is powerful enough for agent-operated research, but the
current workflow depends on the agent remembering several separate commands.
The recurring Marin failure mode was not missing data structures; it was that
agents checked Iris or logbooks directly and only updated Fieldbook afterward,
if at all.

The next phase should make the correct behavior cheap without changing
Fieldbook's architecture. Fieldbook remains local-first, explicit, and
agent-operated. Fieldbook records and guides agent work; it does not enforce
ownership, schedule background work, launch jobs, monitor clusters, or replace
external systems of execution. There is no daemon, background poller, launcher
wrapper, or automatic refresh on session switch.

## Goals / Non-Goals

**Goals:**

- Make one experiment's current state easy to recover with one command.
- Keep output scoped to the requested experiment by default.
- Make refresh/checkpoint discipline hard to skip during context switches.
- Suppress unrelated archived-history noise unless explicitly requested.
- Provide dry-run cleanup plans for stale recovered notes and superseded
  validations.
- Keep all external-state mutation explicit.

**Non-Goals:**

- No scheduler wrapper or `fieldbook launch iris`.
- No daemon, cron, background polling, cluster monitor, or automatic refresh on
  session switch.
- No ownership enforcement or global code-lock manager.
- No direct SQL write escape hatch.
- No dashboard UI.
- No Marin-specific core dependency.

## Decisions

### Decision: Workloop composes existing surfaces

`experiment workloop` is a composition layer over existing status, context,
freshness, refresh, validation, note, run-progress, and doctor helpers.
`experiment status` and `experiment context` remain valid commands with their
existing purpose; workloop becomes the preferred active-experiment entrypoint
for agents because it gathers the bounded resume material in one place.

### Decision: Add `experiment workloop`

`fieldbook experiment workloop <experiment>` is the agent's active-experiment
entrypoint. It runs the same ledger discovery as other commands, resolves the
experiment, and returns a bounded report containing:

- ledger locality summary;
- current session summary;
- run/datapoint progress;
- active job and recovery readiness;
- latest warning/failing validations;
- freshness summary;
- open handoff/next-action/debug notes;
- scoped doctor issues;
- suggested next actions.

Text output is Markdown. JSON output is a structured envelope. Both are bounded
and safe for LLM context.

The JSON envelope uses these top-level keys:

```json
{
  "experiment": {"id": "exp_...", "name": "...", "status": "active"},
  "locality": {"ledger_path": "...", "ledger_id": "...", "cwd": "..."},
  "session": {"current_session_id": "ses_...", "agent": "codex"},
  "runs": {"total": 0, "by_phase": {}, "examples": []},
  "jobs": {"active": 0, "failed": 0, "blockers": []},
  "validations": {"failing": 0, "warning": 0, "recent": []},
  "freshness": {"drifted_artifact_count": 0, "checkpoint_status": "fresh"},
  "notes": {"open_handoffs": [], "open_next_actions": [], "open_debug": []},
  "doctor": {"scoped_issue_count": 0, "global_omitted_count": 0, "issues": []},
  "suggested_next_actions": [
    {"label": "Refresh W&B", "command": "fieldbook ..."}
  ]
}
```

The `runs`, `jobs`, `validations`, and `freshness` blocks reuse the shapes
introduced by their owning phases where possible. Example arrays are bounded;
summary counts are not.

### Decision: Workloop refresh is explicit

The command does not refresh by default. It may accept `--refresh <source>` or
`--refresh-all` to run configured refresh sources in dry-run mode, and `--apply`
to apply the generated reconcile manifests. The output must clearly distinguish
status before refresh, dry-run refresh proposals, applied refresh counts, and
post-refresh status.

This preserves the no-daemon/no-implicit-refresh rule while making the manual
sequence one command instead of several.

### Decision: Workloop checkpoint is explicit

`--checkpoint` writes a checkpoint note after the status/refresh/doctor pass.
It accepts the existing mutually exclusive note body sources: `--body`,
`--body-file`, or `--body-stdin`. If no body is supplied, Fieldbook writes a
generated bounded checkpoint. Fieldbook appends the generated
freshness/workloop summary to supplied checkpoint bodies.

The body-source flags are valid only with `--checkpoint`; otherwise workloop
rejects them as validation errors.

### Decision: Doctor gains experiment scope

`fieldbook doctor --experiment <experiment>` filters issues to the requested
experiment and its linked runs, jobs, artifacts, metrics, validations, notes,
sessions, reconcile events, refresh events, and sync events. Global ledger
issues remain available through normal `doctor`, but active work defaults should
not force agents to inspect unrelated archived experiments.

`experiment workloop` uses the scoped doctor internally.

Scoped doctor reports `global_omitted_count` as a total count plus bounded
counts by severity/code when available. It does not include unrelated issue
details.

### Decision: Cleanup is planned before applied

`fieldbook experiment cleanup <experiment>` plans low-risk bookkeeping cleanup:

- resolve open debug notes attached to recovered failed jobs;
- archive superseded warning/failure validations when a later validation for the
  same check passes;
- refresh local artifact metadata only when explicitly requested.

The default is dry-run. `--apply` is required for writes. Cleanup must record a
checkpoint note describing what changed. When cleanup archives superseded
validations, the checkpoint body includes the superseded validation ids and the
newer validation evidence.

Validation supersession uses the same logical key as validation idempotency:
entity type, entity id, check name/key, source job, and source artifact where
present.

### Decision: Skills remain the adoption layer

The Fieldbook CLI cannot force agents to use it. The global Fieldbook skill,
downstream repo guidance, and Fieldbook README should all say that active
experiment checks start with `experiment workloop`. The command exists to make
that instruction practical.

## Defaults

- `experiment workloop` is read-only unless `--apply`, `--checkpoint`, or a
  cleanup apply flag is supplied.
- `--refresh` dry-runs by default.
- Scoped doctor excludes archived experiments and archived rows by default.
- Output includes at most 20 examples per issue family.
- Cleanup never archives notes or validations outside the requested experiment.

## Risks / Trade-offs

- **Risk: one command becomes a hidden orchestrator** -> Keep side effects
  opt-in and visible in output.
- **Risk: scoped doctor hides real global issues** -> Include a global issue
  count and a suggested full `fieldbook doctor --json` command when non-scoped
  issues exist.
- **Risk: cleanup masks useful history** -> Only soft-archive or resolve rows
  with explicit superseding evidence; keep dry-run as default.
- **Risk: refresh sources are project-specific** -> Workloop calls configured
  refresh sources but does not embed Marin logic.
