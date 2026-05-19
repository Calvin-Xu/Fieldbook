## Context

Fieldbook is operated primarily by coding agents. A single human may switch
between several experiments while jobs run externally, and multiple agents or
worktrees may touch the same repo. The ledger should make context switching
explicit without pretending it can enforce distributed ownership.

## Goals / Non-Goals

**Goals:**

- Make ledger identity and resolution visible before an agent writes anything.
- Preserve the default one-ledger-per-worktree behavior while supporting an
  explicit shared-ledger pointer.
- Make duplicate experiment creation avoidable with a stable idempotency key.
- Add advisory sessions for start/switch/end context workflows.
- Keep session provenance best-effort and non-blocking.
- Warn on stale sessions and likely worktree-locality mistakes.

**Non-Goals:**

- No daemon or background polling.
- No global active experiment stored in ledger metadata.
- No multi-agent locking, ownership transfer, ACLs, or leader election.
- No refresh wrapper, freshness block, `experiment touch`, or
  `export --max-stale`; these are deferred to Phase 12.
- No dashboard UI.

## Decisions

### Decision: Ledger identity is immutable metadata

Every ledger has a `ledger_id` stored in `schema_metadata`. New ledgers receive
one at init. Existing ledgers are backfilled once on open. Fieldbook never
rewrites an existing `ledger_id`. Snapshot imports preserve the source ledger ID
because a snapshot is a copy of a ledger, not a new ledger.

### Decision: `db where` is the first diagnostic command

`fieldbook db where --json` reports the resolved ledger path, ledger ID, current
working directory, git root/worktree information, and how resolution happened.
It is read-only and should work even when no ledger exists by returning
`ledger_path=null`, `ledger_id=null`, and `would_init_at`.

The JSON output shape is:

```json
{
  "envelope_version": 1,
  "ledger_path": "/absolute/path/or/null",
  "ledger_id": "uuid-or-null",
  "cwd": "/absolute/path",
  "git_root": "/absolute/path/or/null",
  "git_worktree_dir": "/absolute/path/or/null",
  "git_branch": "branch-or-null",
  "resolved_via": "--ledger | FIELDBOOK_LEDGER | .fieldbook | cwd-walk | null",
  "would_init_at": "/absolute/path/only-when-ledger-path-is-null"
}
```

Ledger resolution order is:

1. `--ledger`
2. `FIELDBOOK_LEDGER`
3. nearest `.fieldbook` config with `ledger: <path>`
4. cwd-walk for `.experiments/ledger.sqlite`

Relative `.fieldbook` ledger paths resolve relative to the config file.
Malformed `.fieldbook` files are hard validation errors; Fieldbook must not
silently fall back to cwd-walk after a malformed config or a missing `ledger`
key.

### Decision: Experiment idempotency returns existing rows

`experiment create --idempotency-key <key>` creates a new experiment only when
no active experiment has that key. If one exists, the command returns the
existing row with `existed=true` and does not update name, description, tags, or
attrs. Updating experiments remains out of scope.

Keys are lowercase slug-like values up to 128 characters so agents can choose
stable, human-readable keys.

The exact accepted shape is `^[a-z0-9][a-z0-9._-]{0,127}$`.

### Decision: Sessions are advisory context, not locks

Sessions represent agent context: agent name, cwd, optional experiment, git
metadata, intent, timestamps, and attrs. They are append-only work records with
an optional `ended_at`. Fieldbook allows multiple open sessions, allows writes
without sessions, and never treats a session as an exclusive lock.

`session start` opens a session and writes `.fieldbook.session` by default.
`session current` reads `FIELDBOOK_SESSION_ID` first, then the marker. Unknown
or stale session IDs are reported but do not make normal writes fail.

The session marker is `.fieldbook.session` adjacent to the resolved ledger root.
For the default `.experiments/ledger.sqlite` layout this is the repo/worktree
root. For a `.fieldbook` shared-ledger config this is the directory containing
the `.fieldbook` file. For an explicit standalone ledger path this is the
ledger file's parent directory. The marker format is exactly
`id: <session_id>\n`. The marker is git-ignored by default.

### Decision: Session switch is local and transactional

`session switch --to <experiment>` is the context-switch command. It closes the
current session when one exists, writes a Markdown handoff note on the old
experiment, opens a new session for the target experiment, updates the marker,
and prints the new experiment context. It does not call external systems or run
refresh.

The close/write/open sequence happens in one `BEGIN IMMEDIATE` transaction. The
handoff note body uses the existing Fieldbook handoff-note shape: open
handoffs, open next actions, open debug notes, stale jobs, failed jobs, and key
artifacts. The note attrs include the closing `session_id`.

If there is no open session, `switch` simply opens a new session and reports
that no handoff was written.

### Decision: Session lineage is best-effort

Reconcile events gain a nullable `session_id` column. Notes written during a
session store the ID in `attrs.session_id`. Sync events written during
reconcile also store the ID in `attrs.session_id`. Session resolution prefers
`FIELDBOOK_SESSION_ID` over `.fieldbook.session`. If the resolved ID does not
exist or is closed, Fieldbook writes without a session stamp and doctor surfaces
the stale marker/session problem later.

## Defaults

- `ledger_id`: UUID-format identifier stamped by migration
  `009_agent_sessions_locality.sql` when no existing `ledger_id` row exists.
- Idempotency key shape: `^[a-z0-9][a-z0-9._-]{0,127}$`.
- Session marker: `.fieldbook.session`, format `id: <session_id>\n`, adjacent
  to the resolved ledger root, git-ignored by default.
- Session intent flag: `session start --intent <one-line>`.
- Session list filters: `--experiment <ref>`, `--agent <name>`, `--open`, and
  `--limit` with a bounded default.
- `.fieldbook` config: nearest file discovered by walking upward from cwd;
  malformed files and missing `ledger` keys are validation errors.
- Stale session threshold: 24 hours, configurable with
  `--stale-session-hours`.
- Ledger-locality recent-ledger threshold: 7 days, configurable with
  `--locality-recent-days`.
- Session stamping covers `reconcile_events.session_id`,
  `notes.attrs.session_id`, and `sync_events.attrs.session_id`.

## Risks / Trade-offs

- **Risk: session marker race between two agents in one cwd** -> Accept it;
  sessions are advisory and doctor reports stale or inconsistent markers.
- **Risk: `.fieldbook` config becomes a project config surface** -> Keep only
  the `ledger` key in this phase.
- **Risk: `db where` becomes side-effecting** -> Keep it read-only and allow
  missing-ledger output.
- **Risk: phase scope expands into refresh orchestration** -> Defer refresh,
  freshness, touch, and stale-export checks to Phase 12.
