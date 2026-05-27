## MODIFIED Requirements

### Requirement: Provide stable read-only views
The system SHALL expose dashboard data through stable `_v1` views.

#### Scenario: Dashboard uses stable views
- **WHEN** a dashboard handler reads ledger data
- **THEN** it queries stable `_v1` views rather than internal tables

#### Scenario: Dashboard view contract is tested
- **WHEN** dashboard-required views are validated
- **THEN** tests assert the required columns for active experiments, run
  progress, job recovery, lease ownership, validations, freshness, notes,
  artifacts, and refresh/reconcile history

#### Scenario: Stable views remain additive
- **WHEN** dashboard-required `_v1` views evolve
- **THEN** existing columns are not removed or renamed within the MVP contract
