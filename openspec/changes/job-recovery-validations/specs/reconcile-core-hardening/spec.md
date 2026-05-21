## MODIFIED Requirements

### Requirement: Support explicit reconcile operations
The system SHALL support explicit reconcile row operations while preserving current upsert behavior.

#### Scenario: Reconcile job retry lineage
- **WHEN** a reconcile manifest job row contains `retry_of`
- **THEN** reconcile validates the retry target, stores the link, and records it in operation audit

#### Scenario: Reconcile retry target from same manifest
- **WHEN** a reconcile manifest creates a job and another job in the same manifest references it with `retry_of`
- **THEN** reconcile resolves the target from the manifest snapshot and applies both rows in one transaction

#### Scenario: Reject retry target absent from ledger and manifest
- **WHEN** a reconcile manifest references a `retry_of` job ID that is absent from the active ledger and absent from the same manifest
- **THEN** reconcile rejects the manifest with a stable validation error before committing writes

#### Scenario: Reject invalid retry lineage in reconcile
- **WHEN** a reconcile manifest contains a missing, self-referential, or cyclic retry link
- **THEN** reconcile rejects the manifest before committing any writes

#### Scenario: Reconcile validation row
- **WHEN** a reconcile manifest contains a validation row
- **THEN** reconcile validates, inserts or updates the validation, and records the operation in audit

#### Scenario: Reconcile validation archive
- **WHEN** a reconcile manifest validation row has `_op=archive`
- **THEN** reconcile resolves the validation by ID or validation key and soft-archives it

#### Scenario: Reject invalid validation reference in reconcile
- **WHEN** a reconcile validation row references a missing entity, source artifact, source job, or session
- **THEN** reconcile rejects the manifest before committing any writes

#### Scenario: Count validation operations
- **WHEN** reconcile returns counts for a manifest with validations
- **THEN** the count shape includes validation inserts, updates, archives, and noops
