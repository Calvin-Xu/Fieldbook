## ADDED Requirements

### Requirement: Store Markdown note metadata
The system SHALL store note titles and body formats as first-class note fields.

#### Scenario: Add Markdown note with title
- **WHEN** an agent adds a note with a title and no explicit body format
- **THEN** the system stores the title and records the body format as `markdown`

#### Scenario: Reject invalid note metadata
- **WHEN** an agent supplies a body format outside `markdown` or `plain`, an empty title, or a title longer than 120 Unicode characters
- **THEN** the system rejects the command with a validation error

#### Scenario: Migrate existing notes
- **WHEN** an existing ledger is migrated to the new schema
- **THEN** existing notes keep their bodies, receive `body_format=markdown`, and have no title

### Requirement: Ingest note bodies safely
The system SHALL accept exactly one note body source and enforce concise note bodies.

#### Scenario: Add note from file
- **WHEN** an agent adds a note using `--body-file`
- **THEN** the system stores the file contents as the note body

#### Scenario: Add note from stdin
- **WHEN** an agent adds a note using `--body-stdin`
- **THEN** the system stores standard input as the note body

#### Scenario: Reject invalid body source
- **WHEN** an agent supplies zero body sources or multiple body sources
- **THEN** the system rejects the command with a validation error

#### Scenario: Reject empty body
- **WHEN** an agent supplies an empty string body, empty file body, or empty standard input body
- **THEN** the system rejects the note body with a validation error

#### Scenario: Reject oversized body
- **WHEN** an agent supplies a note body larger than 65,536 UTF-8 bytes
- **THEN** the system rejects the note and directs the agent to store long material as an artifact

### Requirement: Separate compact note navigation from full note retrieval
The system SHALL use compact note previews for navigation commands and full bodies for explicit detail commands.

#### Scenario: List notes compactly
- **WHEN** an agent lists notes without verbose output
- **THEN** each row includes note identity, type, status, title, body format, deterministic first-line preview, and update timestamp without the full body

#### Scenario: List notes verbosely
- **WHEN** an agent lists notes with verbose output
- **THEN** each row includes the full stored note body and note metadata

#### Scenario: Show full note
- **WHEN** an agent shows one note
- **THEN** the system returns the full note body, title, body format, status, timestamps, and related entity

### Requirement: Provide compact experiment status
The system SHALL provide a bounded experiment status payload organized for agent context recovery.

#### Scenario: Status categorizes notes
- **WHEN** an agent requests experiment status
- **THEN** the system returns job/artifact summaries, note counts, and compact note previews grouped into `notes.open_handoffs`, `notes.open_next_actions`, `notes.open_debug`, `notes.recent_research`, and `notes.recent_decisions`

#### Scenario: Status omits full note bodies
- **WHEN** an experiment has multiline Markdown notes
- **THEN** the status payload contains compact previews rather than full note bodies

#### Scenario: Status uses bounded note buckets
- **WHEN** an experiment has more notes than the status bucket limits
- **THEN** status includes the latest 10 open handoff notes, 10 open next-action notes, 10 open debug notes, 5 research notes of any status, and 5 decision notes of any status

### Requirement: Provide LLM-ready experiment context
The system SHALL provide an explicit experiment context command for loading bounded full-note handoff context.

#### Scenario: Context includes active full notes
- **WHEN** an agent requests experiment context
- **THEN** the system includes full bodies for up to 20 open handoff notes, 20 open next-action notes, 20 open debug notes, 5 research notes of any status, and 5 decision notes of any status

#### Scenario: Context supports Markdown text output
- **WHEN** an agent requests experiment context without JSON output
- **THEN** the system emits Markdown suitable for direct LLM consumption

#### Scenario: Context supports structured JSON output
- **WHEN** an agent requests experiment context with JSON output
- **THEN** the system emits structured JSON with experiment summary, jobs, artifacts, note counts, and full selected notes

### Requirement: Reconcile note metadata
The system SHALL reconcile note title and body format metadata consistently with CLI note creation.

#### Scenario: Reconcile legacy note manifest
- **WHEN** a reconcile manifest contains note rows without title or body format
- **THEN** the system imports those notes with no title and `body_format=markdown`

#### Scenario: Reconcile note metadata
- **WHEN** a reconcile manifest contains note title and body format fields
- **THEN** the system validates and stores those fields

#### Scenario: Reconcile rejects invalid note body
- **WHEN** a reconcile manifest inserts or updates a note body that is empty or larger than 65,536 UTF-8 bytes
- **THEN** the system rejects the reconcile operation with a validation error
