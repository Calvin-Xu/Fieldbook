## MODIFIED Requirements

### Requirement: Diagnose ledger health issues
The system SHALL diagnose advisory lease issues without mutating lease state.

#### Scenario: Doctor reports stale heartbeat
- **WHEN** an active lease heartbeat is older than the configured stale
  threshold
- **THEN** doctor reports `lease.stale_heartbeat` without releasing the lease

#### Scenario: Doctor reports lease outliving session
- **WHEN** an active lease references an ended session
- **THEN** doctor reports `lease.outlived_session`

#### Scenario: Doctor reports orphaned lease
- **WHEN** a lease references an entity that no longer exists or is deleted
- **THEN** doctor reports `lease.orphaned`

#### Scenario: Doctor reports archived entity lease
- **WHEN** an active lease references an archived experiment or archived entity
- **THEN** doctor reports `lease.archived_entity`
