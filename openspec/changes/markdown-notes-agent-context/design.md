## Context

Fieldbook is pre-v1, and its primary consumer is a coding agent acting from natural-language research instructions. The MVP currently stores note bodies as plain text and returns full note bodies in status/list payloads. Dogfooding in Marin showed that this is good enough to recover state, but insufficient for agent-first research notes: agents need Markdown, titles, and a bounded status surface that tells them what to inspect next without flooding context.

## Goals / Non-Goals

**Goals:**

- Treat note bodies as Markdown by default while keeping a plain-text escape hatch.
- Make note ingestion safe for multiline agent-authored notes.
- Separate compact navigation (`status`, `note list`) from full context loading (`note show`, `experiment context`).
- Keep Fieldbook portable and local-first; no new external runtime dependency.
- Keep notes concise ledger records and direct long reports/logs to artifacts.

**Non-Goals:**

- No backwards compatibility guarantee for status JSON before v1.
- No admin dashboard or Markdown renderer.
- No priority, pinned, or blocking columns.
- No note-to-artifact relation table.
- No W&B or scheduler integration in this phase.

## Decisions

### Decision: Store note title and body format as core columns

`title` and `body_format` are core note attributes rather than JSON attrs. Titles are used by compact agent resume surfaces, and body format is a contract for downstream renderers and agents. `body_format` is validated as `markdown` or `plain`; existing notes migrate to `markdown`.

Titles are optional, stripped before storage, and capped at 120 Unicode characters. Empty-after-strip titles are rejected.

### Decision: Status is compact; context is full

`fieldbook experiment status` remains the bounded navigation surface: counts, jobs, artifacts, and categorized compact note previews. `fieldbook experiment context` is the deliberate LLM handoff surface and may include full Markdown bodies within explicit caps.

Compact note previews use this deterministic algorithm: take the first non-empty body line after stripping leading/trailing whitespace; if that line is longer than 200 Unicode characters, truncate to 199 characters and append `…`; if the first non-empty line is absent, preview is an empty string.

Status JSON uses these note keys:

- `note_counts`: counts by `note_type` and `status`.
- `notes.open_handoffs`: open `handoff` notes, latest 10.
- `notes.open_next_actions`: open `next-action` notes, latest 10.
- `notes.open_debug`: open `debug` notes, latest 10.
- `notes.recent_research`: research notes of any status, latest 5.
- `notes.recent_decisions`: decision notes of any status, latest 5.

The old top-level `open_note_count`, `next_actions`, and `recent_notes` status keys are removed because Fieldbook is pre-v1.

Context JSON uses the same top-level experiment/job/artifact summary plus `notes` with full bodies. Context includes all open handoff, next-action, and debug notes, capped at 20 per active category; recent research and decision notes are capped at 5 each. If a selected note body is individually valid but the full context exceeds a future renderer's budget, callers should select individual notes with `note show`; the MVP does not truncate valid selected note bodies inside `experiment context`.

Context text output is Markdown with this shape:

```markdown
# Fieldbook Context: <experiment name>

## Summary

## Jobs

## Key Artifacts

## Open Handoffs

## Open Next Actions

## Open Debug Notes

## Recent Research

## Recent Decisions
```

### Decision: Use note type rather than priority columns for resume semantics

Open `handoff` notes are blocking/resume context for the next agent. Open `next-action` notes are active work. Open `debug` notes are unresolved investigations. Recent `research` and `decision` notes are durable context. This preserves a small schema and avoids inventing priority semantics before there is evidence that note type is insufficient.

### Decision: Enforce concise notes with a body size cap

Notes can be rich Markdown, but they are not logbooks or reports. A 64 KiB body cap keeps accidental log dumps out of SQLite notes and points agents toward `artifact add` for large material. The cap is exactly 65,536 UTF-8 bytes and applies to CLI input and reconcile inserts/updates.

`fieldbook note add` accepts exactly one of `--body`, `--body-file`, or `--body-stdin`. `--body ""` counts as a provided body source and is rejected as empty content. `--body-format markdown|plain` selects body format and defaults to `markdown`.

`fieldbook note show` text output prints note metadata first, then `---`, then the raw stored body as the final section so multiline Markdown is preserved.

## Risks / Trade-offs

- **Risk: status output changes break local scripts before v1** -> Acceptable pre-v1; tests will define the new contract.
- **Risk: compact previews hide important context** -> Mitigated by `note show` and `experiment context`.
- **Risk: agents overuse notes for large reports** -> Mitigated by the 64 KiB cap and documentation directing long outputs to artifacts.
- **Risk: text tables shred multiline Markdown** -> Mitigated by omitting full bodies from compact tables and printing full note bodies only in dedicated show/context surfaces.
