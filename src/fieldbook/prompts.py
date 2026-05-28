from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from fieldbook.doctor import SECRET_PATTERNS
from fieldbook.errors import AmbiguityError, NotFoundError, ValidationError


PROMPT_CATALOG_VERSION = "prompts_v1"
PROMPT_ENVELOPE_VERSION = 1
PROMPT_MAX_CHARS = 1500
SKILL_BODY_OVERLAP_LIMIT = 200

FORBIDDEN_PROMPT_SUBSTRINGS = (
    "--apply",
    "--force",
    "--archive",
    "--errata",
    "--errata-force",
    "--checkpoint",
    "--update-existing",
    "--retry-of",
)

_QUERIES = {
    "experiment": (
        "SELECT * FROM v_dashboard_experiments_v1 "
        "WHERE experiment_id = ? OR name = ? ORDER BY experiment_id"
    ),
    "open_notes": (
        "SELECT note_id, note_type, status, title, body_preview, updated_at "
        "FROM v_dashboard_notes_v1 "
        "WHERE experiment_id = ? AND status = 'open' "
        "AND note_type IN ('handoff', 'next-action', 'debug') "
        "ORDER BY updated_at DESC LIMIT 10"
    ),
}


def prompt_queries() -> dict[str, str]:
    return dict(_QUERIES)


@dataclass(frozen=True)
class PromptAction:
    action_id: str
    title: str
    description: str
    constraint: str
    entry_command: Callable[[str], str]
    issue_summary: Callable[[dict[str, Any], dict[str, Any]], str]
    is_applicable: Callable[[dict[str, Any], dict[str, Any]], bool]

    def metadata(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "constraint": self.constraint,
            "entry_command": self.entry_command("<experiment>"),
        }


def prompt_catalog() -> dict[str, Any]:
    return {
        "catalog_version": PROMPT_CATALOG_VERSION,
        "actions": [action.metadata() for action in _CATALOG],
    }


def prompt_actions(conn: sqlite3.Connection, experiment_ref: str) -> dict[str, Any]:
    experiment = _resolve_experiment(conn, experiment_ref)
    context = _context(conn, experiment["experiment_id"])
    actions = [
        _action_payload(action, experiment, context, include_body=False)
        for action in _CATALOG
        if action.is_applicable(experiment, context)
    ]
    return {
        "catalog_version": PROMPT_CATALOG_VERSION,
        "experiment_id": experiment["experiment_id"],
        "experiment_name": experiment["name"],
        "actions": actions,
    }


def build_prompt(
    conn: sqlite3.Connection,
    action_id: str,
    experiment_ref: str,
    *,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    experiment = _resolve_experiment(conn, experiment_ref)
    context = _context(conn, experiment["experiment_id"])
    action = _action_by_id(action_id)
    if not action.is_applicable(experiment, context):
        raise ValidationError(f"prompt action {action_id!r} is not applicable to experiment {experiment['experiment_id']}")
    payload = _action_payload(action, experiment, context, include_body=True)
    _validate_prompt_body(payload["body"], skill_path=skill_path)
    return payload


def _context(conn: sqlite3.Connection, experiment_id: str) -> dict[str, Any]:
    open_notes = [_row(row) for row in conn.execute(_QUERIES["open_notes"], (experiment_id,)).fetchall()]
    return {"open_notes": open_notes}


def _resolve_experiment(conn: sqlite3.Connection, experiment_ref: str) -> dict[str, Any]:
    rows = [_row(row) for row in conn.execute(_QUERIES["experiment"], (experiment_ref, experiment_ref)).fetchall()]
    if not rows:
        raise NotFoundError(f"experiment not found: {experiment_ref}")
    if len(rows) > 1:
        raise AmbiguityError(f"experiment reference is ambiguous: {experiment_ref}")
    return rows[0]


def _action_by_id(action_id: str) -> PromptAction:
    for action in _CATALOG:
        if action.action_id == action_id:
            return action
    raise ValidationError(f"unknown prompt action: {action_id}")


def _action_payload(
    action: PromptAction,
    experiment: dict[str, Any],
    context: dict[str, Any],
    *,
    include_body: bool,
) -> dict[str, Any]:
    experiment_id = str(experiment["experiment_id"])
    issue_summary = action.issue_summary(experiment, context)
    payload: dict[str, Any] = {
        "envelope_version": PROMPT_ENVELOPE_VERSION,
        "catalog_version": PROMPT_CATALOG_VERSION,
        "action_id": action.action_id,
        "title": action.title,
        "description": action.description,
        "experiment_id": experiment_id,
        "experiment_name": experiment["name"],
        "applicable": True,
        "issue_summary": issue_summary,
        "entry_command": action.entry_command(experiment_id),
        "constraints": [action.constraint],
    }
    if include_body:
        payload["body"] = _render_body(payload)
    return payload


def _render_body(payload: dict[str, Any]) -> str:
    constraints = "\n".join(f"- {constraint}" for constraint in payload["constraints"])
    return (
        f"Fieldbook flagged `{payload['experiment_name']}` (`{payload['experiment_id']}`).\n\n"
        f"Issue: {payload['issue_summary']}\n\n"
        "Please use the Fieldbook skill to investigate. Start with exactly this read-only entry command:\n"
        f"{payload['entry_command']}\n\n"
        "Constraints:\n"
        f"{constraints}\n"
        "- Keep the dashboard as read-only context; make any ledger updates through Fieldbook CLI/reconcile paths."
    )


def _validate_prompt_body(body: str, *, skill_path: Path | None) -> None:
    if len(body) > PROMPT_MAX_CHARS:
        raise ValidationError("prompt body exceeds 1500 characters")
    for forbidden in FORBIDDEN_PROMPT_SUBSTRINGS:
        if forbidden in body:
            raise ValidationError(f"prompt body contains forbidden mutation option: {forbidden}")
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(body):
            raise ValidationError(f"prompt body contains suspected secret pattern: {name}")
    if _contains_skill_overlap(body, skill_path=skill_path):
        raise ValidationError("prompt body copies too much Fieldbook skill text")


def _contains_skill_overlap(body: str, *, skill_path: Path | None) -> bool:
    if skill_path is None or not skill_path.exists() or len(body) <= SKILL_BODY_OVERLAP_LIMIT:
        return False
    skill_text = skill_path.read_text(encoding="utf-8")
    width = SKILL_BODY_OVERLAP_LIMIT + 1
    for start in range(0, len(body) - width + 1):
        if body[start : start + width] in skill_text:
            return True
    return False


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _count_summary(count: int, singular: str, plural: str | None = None) -> str:
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"


def _entry_workloop(experiment_id: str) -> str:
    return f"fieldbook experiment workloop {experiment_id} --json"


def _entry_validation_list(experiment_id: str) -> str:
    return f"fieldbook validation list --entity-type experiment --entity-id {experiment_id} --json"


def _entry_lease_list(experiment_id: str) -> str:
    return f"fieldbook lease list --entity-type experiment --entity-id {experiment_id} --json"


def _entry_context(experiment_id: str) -> str:
    return f"fieldbook experiment context {experiment_id}"


_CATALOG: tuple[PromptAction, ...] = (
    PromptAction(
        action_id="refresh-external-state",
        title="Refresh external state",
        description="Recover current status for active jobs and external systems.",
        constraint="Refresh status intentionally before acting on running or externally updated work.",
        entry_command=_entry_workloop,
        issue_summary=lambda exp, _ctx: f"{_count_summary(int(exp['active_job_count']), 'active job')} may need current external state.",
        is_applicable=lambda exp, _ctx: int(exp["active_job_count"]) > 0,
    ),
    PromptAction(
        action_id="resolve-failed-jobs",
        title="Resolve failed jobs",
        description="Inspect blocking failures or in-progress recovery before retrying.",
        constraint="Inspect retry lineage and executor skip semantics before submitting retries.",
        entry_command=_entry_workloop,
        issue_summary=lambda exp, _ctx: (
            f"{_count_summary(int(exp['blocking_failed_job_count']), 'blocking failed job')} and "
            f"{_count_summary(int(exp['recovery_in_progress_failed_job_count']), 'recovering failure')} need review."
        ),
        is_applicable=lambda exp, _ctx: (
            int(exp["blocking_failed_job_count"]) + int(exp["recovery_in_progress_failed_job_count"]) > 0
        ),
    ),
    PromptAction(
        action_id="fix-failing-validations",
        title="Fix failing validations",
        description="Investigate validation failures before treating the experiment as ready.",
        constraint="Treat validations as evidence and record fixes or errata through Fieldbook.",
        entry_command=_entry_validation_list,
        issue_summary=lambda exp, _ctx: f"{_count_summary(int(exp['failing_validation_count']), 'failing validation')} need review.",
        is_applicable=lambda exp, _ctx: int(exp["failing_validation_count"]) > 0,
    ),
    PromptAction(
        action_id="write-handoff",
        title="Write handoff",
        description="Capture a bounded Markdown handoff for context switching.",
        constraint="Write a bounded Markdown handoff before context switching or archiving.",
        entry_command=_entry_workloop,
        issue_summary=lambda exp, _ctx: f"Experiment handoff is {exp['handoff_status']}.",
        is_applicable=lambda exp, _ctx: exp["handoff_status"] in {"missing", "stale"},
    ),
    PromptAction(
        action_id="resolve-stale-leases",
        title="Resolve stale leases",
        description="Inspect stale advisory ownership before taking over work.",
        constraint="Inspect ownership before releasing or taking over any lease.",
        entry_command=_entry_lease_list,
        issue_summary=lambda exp, _ctx: f"{_count_summary(int(exp['stale_lease_count']), 'stale lease')} may indicate abandoned work.",
        is_applicable=lambda exp, _ctx: int(exp["stale_lease_count"]) > 0,
    ),
    PromptAction(
        action_id="review-open-notes",
        title="Review open notes",
        description="Review handoff, next-action, or debug notes before acting.",
        constraint="Review open notes and update or resolve them after acting.",
        entry_command=_entry_context,
        issue_summary=lambda _exp, ctx: f"{_count_summary(len(ctx['open_notes']), 'open action note')} need review.",
        is_applicable=lambda _exp, ctx: len(ctx["open_notes"]) > 0,
    ),
    PromptAction(
        action_id="review-outputs",
        title="Review outputs",
        description="Review completed outputs and mark the experiment reviewed when current.",
        constraint="Inspect current outputs before marking the experiment reviewed.",
        entry_command=_entry_workloop,
        issue_summary=lambda exp, _ctx: (
            f"Reviewable activity at {exp['last_reviewable_activity_at']} is newer than latest review marker."
        ),
        is_applicable=lambda exp, _ctx: exp.get("lifecycle_state") == "review",
    ),
)
