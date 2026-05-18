## ADDED Requirements

### Requirement: Reconcile external state
The system SHALL provide a reconcile workflow that compares external job or
artifact state against the ledger and proposes or applies updates.

#### Scenario: Dry-run reconcile
- **WHEN** a user runs reconcile in dry-run mode
- **THEN** the system reports proposed ledger inserts and updates without
  modifying the database

#### Scenario: Apply reconcile
- **WHEN** a user runs reconcile with apply enabled
- **THEN** the system writes the accepted updates and records a reconcile event

#### Scenario: Atomic reconcile apply
- **WHEN** reconcile applies updates from one manifest
- **THEN** the system applies all accepted updates in one transaction or leaves
  the ledger unchanged

### Requirement: Support file-based reconcile inputs
The system SHALL support a generic file-based reconcile input for CSV or JSON
manifests before requiring project-specific adapters.

#### Scenario: Import job status manifest
- **WHEN** a user provides a manifest containing job identifiers, statuses, and
  artifact URIs
- **THEN** the system matches existing records when possible and proposes new
  records for unknown jobs or artifacts

#### Scenario: Import run and metric manifest
- **WHEN** a user provides a manifest containing runs, jobs, artifacts, metrics,
  notes, and custom attributes
- **THEN** the system matches existing records when possible and proposes new
  records or updates for each supported entity type

### Requirement: Keep reconcile auditable
The system SHALL record when reconcile changed the ledger and what source was
used.

#### Scenario: Reconcile event recorded
- **WHEN** reconcile applies updates
- **THEN** the system records the source, timestamp, per-entity insert counts,
  per-entity update counts, and related experiment when available

### Requirement: Support project-specific reconcile adapters
The system SHALL allow future project adapters to translate external systems
into the generic reconcile input model.

#### Scenario: Marin adapter emits generic updates
- **WHEN** a Marin adapter inspects Iris or GCS state
- **THEN** it emits generic job, artifact, metric, and custom attribute updates
  that the core reconcile workflow can dry-run or apply
