## ADDED Requirements

### Requirement: Record reconcile session lineage
The system SHALL record optional session lineage on reconcile events.

#### Scenario: Stamp reconcile event with session
- **WHEN** reconcile applies a manifest while a valid current session exists
- **THEN** the reconcile event row stores the session ID

#### Scenario: Ignore stale or unknown session
- **WHEN** the resolved session ID is unknown, stale, or closed
- **THEN** the reconcile event row stores `session_id=null` and the write
  succeeds

#### Scenario: Stamp sync event attrs during reconcile
- **WHEN** reconcile records sync events while a valid current session exists
- **THEN** those sync events include `session_id` in attrs
