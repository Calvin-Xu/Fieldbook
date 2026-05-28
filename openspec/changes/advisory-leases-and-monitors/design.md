## Context

Fieldbook's current sessions identify who is working, but not what work they
claim responsibility for. Marin dogfood exposed two related needs:

- a long-running coding agent should be able to claim ownership of babysitting
  a job and keep a heartbeat/handoff trail;
- multiple agents working on one repository should see each other's active
  experiment/run/job ownership before duplicating work.

These are coordination needs, not scheduling needs. Fieldbook should make
ownership visible and auditable while leaving all actual execution to agents,
Iris, W&B, GCS, and repo-specific tools.

## Goals / Non-Goals

**Goals:**

- Track advisory ownership for experiments, runs, and jobs.
- Support long-running monitor loops with explicit claim, heartbeat, release,
  and handoff state.
- Make duplicate monitoring and stale ownership visible to agents.
- Preserve a reconstructible audit trail for expired and force-taken-over
  leases.
- Keep babysitter observations separate from authoritative job status.

**Non-Goals:**

- No daemon, background sweeper, cluster monitor, scheduler, or launcher.
- No hard locks that prevent normal ledger writes.
- No automatic job status mutation from monitor observations.
- No `restart_count` column; retry depth is derived from job retry lineage.
- No dashboard UI in this phase.

## Decisions

### Decision: One advisory lease primitive

Fieldbook adds one lease primitive for `experiment`, `run`, and `job` entities.
A lease records ownership intent with fields equivalent to:

- `entity_type` and `entity_id`;
- `owner_agent`;
- optional `session_id`;
- `claimed_at`, `heartbeat_at`, `expires_at`, `released_at`;
- `released_by`, `release_reason`;
- flexible `attrs_json`.

Only one unreleased lease may exist per entity. Released leases remain in
history.

The top-level CLI group is `fieldbook lease` because leases span experiments,
runs, and jobs. Entity-specific commands may link to it, but the canonical
mutation surface is the top-level lease group.

### Decision: Heartbeats are advisory

`heartbeat_at` is used to surface stale babysitters and stale coordination
state. A stale heartbeat does not automatically release the lease. Active lease
queries treat unreleased, unexpired leases as active; doctor reports stale
heartbeat separately.

The default stale-heartbeat threshold is 1 hour, with a CLI override for
doctor/status/workloop views.

### Decision: Lease expiration is optional

`expires_at` is optional. When it is null, the lease does not expire and another
owner can take over only with `--force`. When it is set and in the past, another
owner can claim the entity through an audited expired takeover.

### Decision: Takeover is explicit and audited

If a lease is expired, another agent may claim it by transactionally releasing
the old lease with `release_reason='expired'` and inserting a new lease. If a
lease is unexpired, another agent needs `--force`; force takeover
sets `release_reason='force_takeover'` and records the takeover actor.

`released_by` stores the releasing owner-agent string, and `released_session_id`
is recorded when available.

### Decision: Same-owner reclaims are idempotent

If `owner_agent` matches an active lease owner, claim returns the existing lease
and updates heartbeat even if the caller has a new session id. This supports
agent restart/resume without noisy force-takeover history. A different owner
must wait for expiration or pass `--force`.

### Decision: Observations are not authority

Babysit-specific observations such as last observed Iris state, last error
signal, or a resubmit command hash live in `attrs_json` or a later observation
table. They do not update `jobs.status`. Authoritative job state continues to
flow through existing job update and reconcile paths.

Lease attrs use non-reserved keys for caller metadata. Fieldbook-owned metadata
uses the existing `fieldbook.*` reserved namespace.

### Decision: Leases are visible in agent surfaces

`experiment status`, `experiment context`, `experiment workloop`, and doctor
include bounded lease summaries: current owner, stale heartbeat, expired
claim, force takeover history, and suggested next commands.

## Defaults

- Claiming an already leased entity by the same owner/session is idempotent.
- Claiming an already leased entity by the same owner is idempotent even if the
  current session differs.
- Claiming an unexpired lease owned by another agent fails unless forced.
- Claiming an expired lease performs an audited expired takeover.
- Releasing is explicit; ending a session does not automatically release
  leases, but doctor reports leases whose sessions have ended.
- Lease attrs may store monitor hints but cannot mutate linked jobs, runs, or
  experiments.

## Stable View Sketch

Lease views use `_v1` names and filter deleted records consistently with the
existing view conventions.

- `v_leases_active_v1`: `id`, `entity_type`, `entity_id`, `owner_agent`,
  `session_id`, `claimed_at`, `heartbeat_at`, `expires_at`, `attrs_json`.
- `v_leases_stale_v1`: active lease columns plus `stale_hours` and
  `stale_threshold_hours`. This view uses the default 1-hour threshold because
  SQL views are not parameterized; CLI/status/workloop thresholds remain the
  authoritative configurable surfaces.
- `v_lease_history_v1`: active and released lease columns plus `released_at`,
  `released_by`, `released_session_id`, `release_reason`, and
  `previous_lease_id` when applicable.
- Ownership summary views expose current lease id, owner, heartbeat age, and
  stale/expired flags for experiment, run, and job summaries.

## Doctor Check IDs

Lease doctor issues use dot-style codes:

- `lease.stale_heartbeat`;
- `lease.expired`;
- `lease.orphaned`;
- `lease.archived_entity`;
- `lease.outlived_session`;
- `lease.conflicting_active`.

## Risks / Trade-offs

- **Risk: scheduler creep** -> Keep leases advisory, never executable.
- **Risk: false safety from locks** -> Do not block unrelated ledger writes.
- **Risk: stale leases accumulate** -> Surface them through doctor and
  workloop, not a background sweeper.
- **Risk: monitor observations drift from job state** -> Treat observations as
  hints and keep authoritative status in existing job/reconcile paths.
