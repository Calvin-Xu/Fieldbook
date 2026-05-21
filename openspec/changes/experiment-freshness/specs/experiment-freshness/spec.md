## ADDED Requirements

### Requirement: Capture local artifact freshness metadata
The system SHALL record local-file metadata when artifacts are added or refreshed.

#### Scenario: Stamp local artifact metadata
- **WHEN** an agent adds an artifact whose URI resolves to a local file
- **THEN** the artifact attrs include `fieldbook.local_mtime_at_capture`, `fieldbook.local_size_at_capture`, and `fieldbook.local_path_at_capture`

#### Scenario: Skip non-local artifact metadata
- **WHEN** an agent adds an artifact whose URI is non-local, such as `gs://`, `s3://`, `http://`, `https://`, or `wandb://`
- **THEN** the system does not add local freshness attrs

#### Scenario: Refresh local artifact metadata
- **WHEN** an agent runs `fieldbook artifact refresh-local <artifact>`
- **THEN** the system updates the artifact's captured local mtime, size, and path attrs

#### Scenario: Refresh local artifact content hash
- **WHEN** an agent runs `fieldbook artifact refresh-local <artifact> --update-hash`
- **THEN** the system also updates the artifact content hash to the current local file hash

#### Scenario: Reject refresh of non-local artifact
- **WHEN** an agent runs `artifact refresh-local` on a non-local artifact URI
- **THEN** the system rejects the command with a validation error

### Requirement: Detect local artifact drift
The system SHALL identify active local-file artifacts whose current filesystem metadata differs from captured metadata.

#### Scenario: Detect mtime drift
- **WHEN** a local artifact's current mtime differs from `fieldbook.local_mtime_at_capture`
- **THEN** freshness checks report the artifact as drifted

#### Scenario: Detect size drift
- **WHEN** a local artifact's current size differs from `fieldbook.local_size_at_capture`
- **THEN** freshness checks report the artifact as drifted

#### Scenario: Detect missing local artifact as drift
- **WHEN** a local artifact no longer exists at the captured local path
- **THEN** freshness checks report the artifact as drifted with `drift_kind=missing_file`

#### Scenario: Ignore missing capture metadata
- **WHEN** a local artifact has no captured local metadata
- **THEN** freshness checks do not classify it as drifted solely from missing metadata

### Requirement: Detect stale validations from changed evidence
The system SHALL report validations whose source artifacts changed after validation.

#### Scenario: Source artifact updated after validation
- **WHEN** a validation references a source artifact whose `updated_at` is later than the validation `updated_at`
- **THEN** freshness checks report the validation as stale

#### Scenario: Source artifact has local drift
- **WHEN** a validation references a source artifact that is currently drifted
- **THEN** freshness checks report the validation as stale

#### Scenario: Validation without source artifact
- **WHEN** a validation has no source artifact
- **THEN** validation-source freshness checks do not classify it as stale

### Requirement: Write experiment checkpoints
The system SHALL create bounded checkpoint notes for experiment handoff and archive discipline.

#### Scenario: Create checkpoint note
- **WHEN** an agent runs `fieldbook experiment checkpoint <experiment>`
- **THEN** the system writes an auto-generated Markdown note with note type `checkpoint` and returns a freshness summary

#### Scenario: Create checkpoint note with supplied body
- **WHEN** an agent runs `experiment checkpoint` with exactly one of `--body`, `--body-file`, or `--body-stdin`
- **THEN** the system writes the supplied Markdown plus a generated freshness section

#### Scenario: Archive after checkpoint
- **WHEN** an agent runs `experiment checkpoint <experiment> --archive`
- **THEN** the system writes the checkpoint and archives the experiment in the same command

#### Scenario: Archive and errata flags together
- **WHEN** an agent runs `experiment checkpoint <experiment> --archive --errata`
- **THEN** the system writes an erratum checkpoint and archives the experiment if it is not already archived

#### Scenario: Checkpoint archived experiment with errata
- **WHEN** an agent runs `experiment checkpoint <archived-experiment> --errata`
- **THEN** the system writes the checkpoint as an explicit erratum and leaves the experiment archived

#### Scenario: Reject normal checkpoint on archived experiment
- **WHEN** an agent runs `experiment checkpoint <archived-experiment>` without `--errata`
- **THEN** the system rejects the command with a validation error

### Requirement: Expose experiment freshness in resume surfaces
The system SHALL include bounded freshness summaries in experiment status and context.

#### Scenario: Status freshness block
- **WHEN** an agent runs `fieldbook experiment status <experiment> --json`
- **THEN** the output includes `freshness.drifted_artifact_count`, `freshness.stale_validation_count`, `freshness.last_checkpoint_at`, `freshness.since_last_checkpoint_hours`, and `freshness.checkpoint_status` with values `idle`, `missing`, `stale`, or `current`

#### Scenario: Context freshness block
- **WHEN** an agent runs `fieldbook experiment context <experiment> --json`
- **THEN** the output includes the same freshness summary and bounded examples of drifted artifacts and stale validations

#### Scenario: Freshness does not dump unrelated history
- **WHEN** status or context includes freshness information
- **THEN** the output remains bounded and scoped to the requested experiment
