## ADDED Requirements

### Requirement: Diagnose experiment freshness risks
The system SHALL report local drift and stale checkpoint risks through doctor.

#### Scenario: Warn on local artifact drift
- **WHEN** doctor finds an active local-file artifact whose current mtime or size differs from captured metadata
- **THEN** it reports issue code `artifact.local_drift` with a suggested `artifact refresh-local` action

#### Scenario: Warn on stale validation source
- **WHEN** doctor finds an active validation whose source artifact changed after validation or has local drift
- **THEN** it reports issue code `validation.source_drift` with a suggested validation rerun action

#### Scenario: Warn on missing checkpoint
- **WHEN** doctor checks an active experiment with activity and no checkpoint note
- **THEN** it reports issue code `experiment.checkpoint_stale`

#### Scenario: Warn on stale checkpoint
- **WHEN** doctor checks an active experiment whose latest checkpoint is older than the checkpoint stale threshold
- **THEN** it reports issue code `experiment.checkpoint_stale`
