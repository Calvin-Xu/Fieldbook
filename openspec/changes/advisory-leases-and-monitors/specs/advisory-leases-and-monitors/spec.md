## ADDED Requirements

### Requirement: Record advisory ownership leases
The system SHALL record advisory ownership leases for experiment, run, and job
entities without preventing unrelated ledger writes.

#### Scenario: Claim unleased entity
- **WHEN** an agent claims an unleased experiment, run, or job
- **THEN** Fieldbook records an active lease with owner, optional session,
  claim timestamp, heartbeat timestamp, optional expiration, and attrs

#### Scenario: Duplicate claim by same owner is idempotent
- **WHEN** the same owner claims the same active lease again, with either the
  same session or a new session
- **THEN** Fieldbook returns the existing lease without creating duplicate
  active leases and updates heartbeat

#### Scenario: Duplicate claim by another owner conflicts
- **WHEN** another owner claims an unexpired active lease without force
- **THEN** Fieldbook rejects the claim with a stable conflict error

#### Scenario: Expired takeover is audited
- **WHEN** an owner claims an entity whose active lease has expired
- **THEN** Fieldbook releases the old lease with `release_reason=expired` and
  inserts a new active lease in one transaction

#### Scenario: Force takeover is explicit and audited
- **WHEN** an owner force-claims an unexpired active lease
- **THEN** Fieldbook releases the old lease with
  `release_reason=force_takeover`, records the takeover actor, and inserts a
  new active lease in one transaction

### Requirement: Heartbeats are advisory
The system SHALL use heartbeats to report stale ownership without automatically
releasing leases.

#### Scenario: Heartbeat updates ownership freshness
- **WHEN** the lease owner sends a heartbeat
- **THEN** Fieldbook updates `heartbeat_at` without changing owner, session, or
  claim timestamp

#### Scenario: Stale heartbeat does not auto-release
- **WHEN** a lease heartbeat is older than the stale threshold but the lease is
  not expired or released
- **THEN** Fieldbook still treats the lease as active and reports a stale
  heartbeat warning

#### Scenario: Null expiration requires force takeover
- **WHEN** an active lease has no expiration
- **THEN** another owner cannot claim it unless force takeover is explicitly
  requested

### Requirement: Monitor observations are non-authoritative
The system SHALL store babysitter observations as lease metadata without
mutating authoritative job status.

#### Scenario: Observation attr does not update job status
- **WHEN** a lease attrs payload includes a last observed external job state
- **THEN** Fieldbook stores the attr without changing the linked job's status

#### Scenario: Retry count is derived from jobs
- **WHEN** a job has retry lineage through `jobs.retry_of`
- **THEN** Fieldbook derives retry depth from the job chain rather than a lease
  counter
