# Collaborator Export Workflow

Use this recipe to prepare a shareable metric table.

1. Run `fieldbook doctor --json` and address high-severity issues.
2. Use `fieldbook export coverage` to inspect metric completeness.
3. Export long or wide metric tables with explicit metric selections.
4. Attach exported files as `metric-table` artifacts.
5. Prefer redacted dashboard views for shared artifact listings.
