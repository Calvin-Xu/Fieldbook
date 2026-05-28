## Why

Fieldbook's dashboard is read-only, but the current MVP renders stable views as
generic tables and suggests raw CLI commands. That does not match the intended
operating model: humans inspect the dashboard, while coding agents use the
Fieldbook CLI and skill to do the work.

This phase makes the dashboard ergonomic for humans and useful for agent
handoffs. It adds schema-aware experiment pages and copyable agent-instruction
prompts that point an ongoing coding agent at the relevant experiment issue
without embedding the Fieldbook skill or turning the dashboard into an action
surface.

## What Changes

- Add a closed catalog of agent prompt actions for common dashboard issues.
- Add `fieldbook prompt list`, `fieldbook prompt actions <experiment>`, and
  `fieldbook prompt build <action> <experiment>`.
- Render applicable prompt action cards in the read-only dashboard.
- Redesign dashboard pages around Fieldbook entities instead of generic raw
  tables.
- Replace dashboard copyable CLI command cards with copyable agent
  instructions.
- Preserve the read-only dashboard contract: no prompt sending, no agent
  invocation, no command execution, and no ledger mutation.

## Capabilities

### New Capability

- `dashboard-agent-prompts`: closed-catalog agent prompt builder and dashboard
  prompt cards.

### Modified Capabilities

- `dashboard-mvp`: improve experiment index and detail page rendering while
  keeping GET-only read-only routes.
- `agent-workflow`: document that dashboard prompts are human-to-agent
  instructions and that agents should rely on the Fieldbook skill for workflow
  details.
- `readonly-sql-stable-views`: dashboard and prompt builders continue to read
  only stable `_v1` or redacted views.

## Impact

- Adds a `prompt` CLI group and a shared prompt-rendering module.
- Adds dashboard render helpers and tests for schema-aware sections.
- Adds docs and Fieldbook skill guidance for copyable agent prompts.
- No new dashboard write routes, daemon, launcher, scheduler, monitor, or agent
  integration.
