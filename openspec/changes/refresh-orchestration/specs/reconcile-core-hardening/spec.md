## MODIFIED Requirements

### Requirement: Reconcile with a consistent transaction snapshot
The system SHALL plan and apply reconcile operations using one consistent database snapshot.

#### Scenario: Refresh dry-run uses reconcile dry-run
- **WHEN** refresh runs without `--apply`
- **THEN** it invokes reconcile dry-run and records the dry-run counts without committing entity writes

#### Scenario: Refresh apply uses reconcile apply
- **WHEN** refresh runs with `--apply`
- **THEN** it invokes reconcile apply and records the resulting reconcile event ID

#### Scenario: Refresh reconcile failure is atomic
- **WHEN** reconcile fails during refresh apply
- **THEN** entity writes are rolled back and the refresh event records stage `reconcile`

#### Scenario: Refresh event points to reconcile event
- **WHEN** refresh apply succeeds
- **THEN** the refresh event references the reconcile event created by that apply
