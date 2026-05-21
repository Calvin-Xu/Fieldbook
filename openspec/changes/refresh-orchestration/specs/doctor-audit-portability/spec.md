## MODIFIED Requirements

### Requirement: Run read-only ledger doctor
The system SHALL audit ledger health without mutating the ledger.

#### Scenario: Detect failed refresh event
- **WHEN** doctor finds a recent refresh event with failed status
- **THEN** it reports `refresh.failed` as a warning with source and stage

#### Scenario: Detect missing refresh snapshot
- **WHEN** a refresh event references a local snapshot path that no longer exists
- **THEN** doctor reports `refresh.snapshot_missing` as a warning

#### Scenario: Detect stale refresh snapshot
- **WHEN** doctor finds a refresh snapshot under `.experiments/refresh-snapshots/` older than the stale snapshot threshold
- **THEN** doctor reports `refresh.snapshot_stale` as an informational issue using a default threshold of 30 days unless overridden

#### Scenario: Detect unapplied refresh manifest
- **WHEN** doctor finds a successful dry-run refresh with a manifest path and no later applied refresh for the same source and snapshot
- **THEN** it reports `refresh.unapplied_manifest` as an informational issue

#### Scenario: Detect stale refresh source
- **WHEN** a configured refresh source has no successful refresh event within the supplied stale threshold
- **THEN** doctor reports `refresh.stale_source` as a warning

#### Scenario: Detect suspected secrets in refresh snapshots
- **WHEN** doctor finds suspected secret patterns in files under `.experiments/refresh-snapshots/`
- **THEN** doctor reports `privacy.refresh_snapshot_secret_pattern` as a warning with snapshot path, source when inferable, pattern family, redacted snippet, and remediation guidance
