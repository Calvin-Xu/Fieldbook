## 1. Specification And Review

- [x] 1.1 Treat the CC design critique in session
  `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for
  `dashboard-agent-prompts`.
- [x] 1.3 Validate `dashboard-agent-prompts`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume
  23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for prompt catalog listing, applicability, and
  prompt rendering.
- [x] 2.2 Add failing tests for prompt safety: length cap, suspected secret
  rejection, no mutation flags, no skill-body embedding, and one read-only
  entry command.
- [x] 2.3 Add failing tests for prompt CLI text and JSON output.
- [x] 2.4 Add failing tests for schema-aware dashboard index/detail rendering,
  including category sidebar navigation, archived collapsed by default, and
  horizontal tabs for experiment detail navigation.
- [x] 2.5 Add failing tests for dashboard prompt action cards and GET-only
  no-send routing.
- [x] 2.6 Add failing docs/skill tests for dashboard prompt guidance.
- [x] 2.7 Add failing tests proving prompt commands are classified read-only.

## 3. Prompt Builder

- [x] 3.1 Add a shared prompt action catalog and rendering module.
- [x] 3.2 Add applicability checks based on stable views.
- [x] 3.3 Add prompt body rendering and safety validation.
- [x] 3.4 Add `fieldbook prompt list`, `fieldbook prompt actions`, and
  `fieldbook prompt build`.
- [x] 3.5 Register `prompt` subcommands as read-only in `_is_read_only`.

## 4. Dashboard UI

- [x] 4.1 Replace generic table rendering with entity-specific renderers.
- [x] 4.2 Add compact experiment index cards grouped by dashboard state.
- [x] 4.3 Add detail header metrics, attention cards, and horizontal detail
  tabs.
- [x] 4.4 Render notes, runs, jobs, artifacts, leases, validations, and links
  without redundant page-context columns.
- [x] 4.5 Render applicable agent-instruction cards without dashboard write or
  send behavior.
- [x] 4.6 Remove Phase 19 raw CLI command cards from experiment detail pages.

## 5. Docs And Skill

- [x] 5.1 Update README dashboard guidance.
- [x] 5.2 Update Fieldbook skill guidance for dashboard agent prompts.
- [x] 5.3 Update dashboard smoke-test guidance.

## 6. Validation And Implementation Review

- [x] 6.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 6.2 Run CC implementation review with the resumed Fieldbook session.
- [x] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation if requested.
