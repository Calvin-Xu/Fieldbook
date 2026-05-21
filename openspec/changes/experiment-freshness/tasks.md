## 1. Specification And Review

- [x] 1.1 Treat CC design critique in session `23592491-85d8-4d6e-9cd3-3dbe7f265110` as the ideation gate.
- [x] 1.2 Draft proposal, design, specs, tasks, and `PHASES.md` entry for `experiment-freshness`.
- [x] 1.3 Validate `experiment-freshness`.
- [x] 1.4 Run CC spec review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 1.5 Patch spec blockers and revalidate.
- [x] 1.6 Begin implementation only after the Phase 12 archived-errata amendment is implemented.

Do not begin implementation tasks until 1.5 is complete.

## 2. Tests First

- [x] 2.1 Add failing tests for local artifact mtime/size stamping on add and skip behavior for non-local URIs.
- [x] 2.2 Add failing tests for `artifact refresh-local`, including optional hash update.
- [x] 2.3 Add failing tests for artifact local drift, missing local files as drift, and validation source drift doctor checks.
- [x] 2.4 Add failing tests for stale or missing experiment checkpoint doctor checks.
- [x] 2.5 Add failing tests for `experiment checkpoint`, including generated body, body-file/stdio ingestion, JSON output, `--archive`, and archived `--errata`.
- [x] 2.6 Add failing tests for status/context freshness blocks, idle experiments, and bounded examples.
- [x] 2.7 Add failing tests for refresh output `drifted_artifacts`.

## 3. Freshness Helpers And CLI

- [x] 3.1 Add local artifact metadata capture helpers.
- [x] 3.2 Stamp local artifact attrs in artifact add and refresh paths.
- [x] 3.3 Add `fieldbook artifact refresh-local <artifact>`.
- [x] 3.4 Add `fieldbook experiment checkpoint <experiment>`.
- [x] 3.5 Add `checkpoint` to valid note types and update compact note surfaces as needed.

## 4. Status, Context, Doctor, Refresh

- [x] 4.1 Add freshness summaries to `experiment status` and `experiment context`.
- [x] 4.2 Add doctor checks `artifact.local_drift`, `validation.source_drift`, and `experiment.checkpoint_stale`.
- [x] 4.3 Add bounded drift reporting to refresh JSON/text output.
- [x] 4.4 Update README and Fieldbook agent skill with checkpoint, drift, and refresh-local workflows.

## 5. Validation And Implementation Review

- [x] 5.1 Run OpenSpec validation, py_compile, and full tests.
- [x] 5.2 Run CC implementation review with `env -u ANTHROPIC_API_KEY claude --resume 23592491-85d8-4d6e-9cd3-3dbe7f265110 --model claude-opus-4-7 --effort max`.
- [x] 5.3 Patch CC blockers and rerun validation.
