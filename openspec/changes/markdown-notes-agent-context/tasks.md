## 1. Specification And Review

- [x] 1.1 Draft proposal, design, specs, and tasks for `markdown-notes-agent-context`.
- [x] 1.2 Validate the OpenSpec change.
- [x] 1.3 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [x] 1.4 Patch spec blockers from CC and revalidate.
- [ ] 1.5 Commit and push the reviewed spec.

## 2. Tests First

- [ ] 2.1 Add failing migration tests for note title and body format defaults/constraints.
- [ ] 2.2 Add failing CLI tests for body source validation, body-file/stdin, note title, body format, and note show.
- [ ] 2.3 Add failing status/context tests for compact previews, note categories, and full Markdown context.
- [ ] 2.4 Add failing reconcile tests for note metadata defaults and roundtrip.

## 3. Schema And Validation

- [ ] 3.1 Add migration `004_note_markdown_and_title.sql` and bump schema version.
- [ ] 3.2 Add note metadata/body validation constants and helpers.
- [ ] 3.3 Update repository note creation, retrieval, list, compact preview, status, and context methods.
- [ ] 3.4 Update reconcile note planning and apply logic for title/body format.

## 4. CLI And Output

- [ ] 4.1 Update note add/list/show CLI behavior and JSON/text output.
- [ ] 4.2 Add experiment context CLI behavior and Markdown text rendering.
- [ ] 4.3 Ensure default table/status text output uses previews and never shreds multiline note bodies.

## 5. Docs And Skill

- [ ] 5.1 Update README examples for Markdown notes, body files, status, context, and handoff notes.
- [ ] 5.2 Update the in-repo Fieldbook agent skill with the new note/status/context workflow.

## 6. Validation And Implementation Review

- [ ] 6.1 Run OpenSpec validation, full tests, and py_compile.
- [ ] 6.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --model claude-opus-4-7 --effort max`.
- [ ] 6.3 Patch CC blockers and rerun validation.
- [ ] 6.4 Commit and push the implementation.
