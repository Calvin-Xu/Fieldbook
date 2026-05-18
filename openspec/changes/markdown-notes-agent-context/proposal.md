## Why

Fieldbook's MVP note and status surfaces work for simple reminders, but dogfooding showed that agents need richer Markdown notes and a clearer distinction between compact status navigation and full LLM-ready context. This change makes notes first-class Markdown records while keeping default resume output bounded and scriptable.

## What Changes

- Add Markdown-first note metadata: optional note titles and explicit note body format.
- Add safer note body ingestion through `--body`, `--body-file`, or `--body-stdin`, with exactly one source required.
- Add full-note retrieval via `fieldbook note show`.
- Change note list and experiment status output to compact note previews instead of dumping full Markdown bodies by default.
- Add `fieldbook experiment context` for LLM-ready experiment handoff context with full Markdown note bodies for active resume notes.
- Add validation and migration coverage for note title length, body format, and maximum note body size.
- Update Fieldbook's agent-facing docs and skill guidance for status, context, handoff notes, and Markdown body files.

## Capabilities

### New Capabilities

- `markdown-notes-agent-context`: Markdown note storage, compact note navigation, and LLM-ready experiment context surfaces for agent-operated ledgers.

### Modified Capabilities

None. The MVP capabilities have not yet been archived into root OpenSpec specs, so this follow-up change records the next-phase requirements as a new capability.

## Impact

- SQLite schema migration for the `notes` table.
- CLI changes for note add/list/show and experiment status/context.
- Repository and reconcile updates for note metadata and compact/full note representations.
- Text and JSON output behavior changes for note-bearing commands.
- README and in-repo Fieldbook skill updates.
