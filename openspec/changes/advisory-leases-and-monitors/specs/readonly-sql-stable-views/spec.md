## MODIFIED Requirements

### Requirement: Provide stable read-only views
The system SHALL expose advisory lease state through stable `_v1` views.

#### Scenario: Active lease view
- **WHEN** an agent queries `v_leases_active_v1`
- **THEN** the view returns unreleased, unexpired leases with owner, session,
  entity, claim, heartbeat, expiration, and attrs JSON columns

#### Scenario: Stale lease view
- **WHEN** an agent queries `v_leases_stale_v1`
- **THEN** the view returns active leases whose heartbeat is older than the
  stale threshold

#### Scenario: Lease history view
- **WHEN** an agent queries `v_lease_history_v1`
- **THEN** the view returns released and active lease audit history for
  experiments, runs, and jobs, including release actor, release session,
  release reason, and previous lease reference where applicable

#### Scenario: Ownership summary views
- **WHEN** an agent queries run, job, or experiment summary views
- **THEN** current advisory ownership is available without requiring direct
  table reads
