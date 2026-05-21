## MODIFIED Requirements

### Requirement: Run adapters as pure manifest producers
The system SHALL run adapters without reading or writing the Fieldbook ledger.

#### Scenario: Refresh invokes adapter from snapshot
- **WHEN** refresh orchestration invokes an adapter
- **THEN** it passes only the local snapshot path and adapter options, not a ledger connection or repository handle

#### Scenario: Adapter remains pure under refresh
- **WHEN** an adapter is invoked by refresh orchestration
- **THEN** the adapter writes a reconcile manifest and debug output but does not mutate the ledger

#### Scenario: Adapter failure does not mutate ledger
- **WHEN** an adapter fails during refresh
- **THEN** no reconcile dry-run or apply is attempted and entity rows remain unchanged

#### Scenario: Adapter debug path is preserved
- **WHEN** an adapter writes debug output during refresh
- **THEN** refresh records the debug path in the refresh event and command output
