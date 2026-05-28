## MODIFIED Requirements

### Requirement: Provide stable read-only views
The system SHALL expose dashboard and prompt-builder data through stable `_v1`
or redacted views.

#### Scenario: Prompt builder uses stable views
- **WHEN** prompt applicability or prompt content is computed
- **THEN** Fieldbook reads stable `_v1` views or redacted views rather than
  internal tables directly

#### Scenario: Artifact display uses redacted artifact views when available
- **WHEN** dashboard or prompt rendering needs artifact URI context
- **THEN** it uses `v_artifacts_redacted_v1` where available, otherwise an
  existing dashboard `_v1` artifact view, and never queries internal artifact
  tables directly

#### Scenario: Dashboard UI uses stable views
- **WHEN** dashboard handlers render schema-aware sections
- **THEN** they continue to query stable `_v1` views rather than internal
  tables directly
