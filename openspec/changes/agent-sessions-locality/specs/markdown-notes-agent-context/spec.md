## ADDED Requirements

### Requirement: Record note session lineage
The system SHALL record best-effort session lineage in note attrs.

#### Scenario: Stamp note attrs
- **WHEN** a note is created while a valid current session exists
- **THEN** the note attrs include `session_id`

#### Scenario: Tolerate missing session
- **WHEN** no current valid session is set
- **THEN** the note is created without a `session_id` in attrs
