import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fieldbook.db import CURRENT_SCHEMA_VERSION, schema_version
from fieldbook.freshness import drifted_artifacts, experiment_freshness, stale_validations
from fieldbook.time_utils import utc_now


STALE_JOB_STATUSES = ("queued", "running")
ATTR_TABLES = (
    "experiments",
    "runs",
    "jobs",
    "artifacts",
    "notes",
    "reconcile_events",
    "sync_events",
    "sessions",
    "validations",
    "refresh_events",
)
ENTITY_TABLES = {
    "experiment": "experiments",
    "run": "runs",
    "job": "jobs",
    "artifact": "artifacts",
    "metric": "metrics",
}
SECRET_PATTERNS = {
    "api_key_assignment": re.compile(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)=[^\s'\"]{8,}"),
    "openai_style_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
}


@dataclass(frozen=True)
class DoctorIssue:
    code: str
    severity: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] | None = None
    suggested_next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "message": self.message,
            "details": self.details or {},
            "suggested_next_action": self.suggested_next_action,
        }


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    description: str
    default_enabled: bool
    severity: str
    runner: Callable[[sqlite3.Connection, "DoctorOptions"], list[DoctorIssue]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "default_enabled": self.default_enabled,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class DoctorOptions:
    stale_hours: float
    stale_lease_hours: float
    stale_session_hours: float
    stale_submitting_hours: float
    stale_unknown_submit_hours: float
    retry_loop_threshold: int
    stale_refresh_snapshot_days: float
    locality_recent_days: float
    cwd: Path
    ledger_path: Path
    resolved_via: str | None


def list_doctor_checks() -> dict[str, Any]:
    return {"checks": [check.to_dict() for check in DOCTOR_CHECKS.values()]}


def run_doctor(
    ledger_path: Path,
    *,
    check_ids: list[str] | None,
    stale_hours: float,
    cwd: Path,
    experiment_ref: str | None = None,
    stale_lease_hours: float = 1.0,
    stale_session_hours: float = 24.0,
    stale_submitting_hours: float = 1.0,
    stale_unknown_submit_hours: float = 6.0,
    retry_loop_threshold: int = 3,
    stale_refresh_snapshot_days: float = 30.0,
    locality_recent_days: float = 7.0,
    resolved_via: str | None = None,
) -> dict[str, Any]:
    selected_checks = _selected_checks(check_ids)
    conn = _connect_readonly(ledger_path)
    try:
        version = schema_version(conn)
        if version != CURRENT_SCHEMA_VERSION:
            return _envelope(
                ledger_path=ledger_path,
                schema=version,
                checks=[],
                issues=[
                    DoctorIssue(
                        code="schema.version_mismatch",
                        severity="error",
                        message=(
                            f"ledger schema version {version} does not match installed "
                            f"Fieldbook schema {CURRENT_SCHEMA_VERSION}"
                        ),
                        details={"ledger_schema_version": version, "installed_schema_version": CURRENT_SCHEMA_VERSION},
                        suggested_next_action="Migrate older ledgers with a normal write-capable Fieldbook command.",
                    )
                ],
            )
        options = DoctorOptions(
            stale_hours=stale_hours,
            stale_lease_hours=stale_lease_hours,
            stale_session_hours=stale_session_hours,
            stale_submitting_hours=stale_submitting_hours,
            stale_unknown_submit_hours=stale_unknown_submit_hours,
            retry_loop_threshold=retry_loop_threshold,
            stale_refresh_snapshot_days=stale_refresh_snapshot_days,
            locality_recent_days=locality_recent_days,
            cwd=cwd,
            ledger_path=ledger_path,
            resolved_via=resolved_via,
        )
        issues: list[DoctorIssue] = []
        for check in selected_checks:
            issues.extend(check.runner(conn, options))
        global_issue_count = len(issues)
        if experiment_ref is not None:
            experiment_id = _resolve_experiment_id(conn, experiment_ref)
            issues = _filter_issues_for_experiment(conn, issues, experiment_id)
            envelope = _envelope(
                ledger_path=ledger_path,
                schema=version,
                checks=[check.id for check in selected_checks],
                issues=issues,
            )
            envelope["experiment_id"] = experiment_id
            envelope["global_issue_count"] = global_issue_count
            envelope["global_omitted_count"] = max(global_issue_count - len(issues), 0)
            return envelope
        return _envelope(
            ledger_path=ledger_path,
            schema=version,
            checks=[check.id for check in selected_checks],
            issues=issues,
        )
    finally:
        conn.close()


def doctor_failed(envelope: dict[str, Any], *, strict: bool) -> bool:
    severities = {issue["severity"] for issue in envelope["issues"]}
    return "error" in severities or (strict and bool(severities))


def format_doctor_text(envelope: dict[str, Any]) -> str:
    if envelope["ok"]:
        return f"Fieldbook doctor: ok ({envelope['ledger']})"
    lines = [
        f"Fieldbook doctor: {envelope['issue_count']} issue(s) ({envelope['ledger']})",
        f"schema_version: {envelope['schema_version']}",
    ]
    for issue in envelope["issues"]:
        identity = ""
        if issue["entity_type"] and issue["entity_id"]:
            identity = f" {issue['entity_type']}:{issue['entity_id']}"
        lines.append(f"- {issue['severity']} {issue['code']}{identity}: {issue['message']}")
    return "\n".join(lines)


def _selected_checks(check_ids: list[str] | None) -> list[DoctorCheck]:
    if not check_ids:
        return [check for check in DOCTOR_CHECKS.values() if check.default_enabled]
    unknown = [check_id for check_id in check_ids if check_id not in DOCTOR_CHECKS]
    if unknown:
        unknown_text = ", ".join(sorted(unknown))
        raise ValueError(f"unknown doctor check(s): {unknown_text}")
    return [DOCTOR_CHECKS[check_id] for check_id in check_ids]


def _resolve_experiment_id(conn: sqlite3.Connection, ref: str) -> str:
    row = conn.execute(
        "SELECT id FROM experiments WHERE id = ? OR (name = ? AND deleted_at IS NULL) ORDER BY id",
        (ref, ref),
    ).fetchall()
    if len(row) == 1:
        return str(row[0]["id"])
    if len(row) > 1:
        raise ValueError(f"experiment reference {ref!r} is ambiguous")
    raise ValueError(f"experiment not found: {ref}")


def _filter_issues_for_experiment(
    conn: sqlite3.Connection,
    issues: list[DoctorIssue],
    experiment_id: str,
) -> list[DoctorIssue]:
    return [
        issue
        for issue in issues
        if experiment_id in _issue_experiment_ids(conn, issue)
    ]


def _issue_experiment_ids(conn: sqlite3.Connection, issue: DoctorIssue) -> set[str]:
    if issue.entity_type == "experiment" and issue.entity_id:
        return {issue.entity_id}
    if issue.entity_type == "run" and issue.entity_id:
        return _run_experiment_ids(conn, issue.entity_id)
    if issue.entity_type == "job" and issue.entity_id:
        return _job_experiment_ids(conn, issue.entity_id)
    if issue.entity_type == "artifact" and issue.entity_id:
        return _artifact_experiment_ids(conn, issue.entity_id)
    if issue.entity_type == "lease" and issue.entity_id:
        row = conn.execute("SELECT entity_type, entity_id FROM leases WHERE id = ?", (issue.entity_id,)).fetchone()
        if row:
            return _target_experiment_ids(conn, str(row["entity_type"]), str(row["entity_id"]))
    if issue.entity_type == "note" and issue.entity_id:
        row = conn.execute("SELECT entity_type, entity_id FROM notes WHERE id = ?", (issue.entity_id,)).fetchone()
        if row:
            return _target_experiment_ids(conn, str(row["entity_type"]), str(row["entity_id"]))
    if issue.entity_type == "validation" and issue.entity_id:
        row = conn.execute("SELECT entity_type, entity_id FROM validations WHERE id = ?", (issue.entity_id,)).fetchone()
        if row:
            return _target_experiment_ids(conn, str(row["entity_type"]), str(row["entity_id"]))
    if issue.entity_type == "job_run" and issue.entity_id and ":" in issue.entity_id:
        job_id, run_id = issue.entity_id.split(":", 1)
        return _job_experiment_ids(conn, job_id) | _run_experiment_ids(conn, run_id)
    return set()


def _target_experiment_ids(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> set[str]:
    if entity_type == "experiment":
        return {entity_id}
    if entity_type == "run":
        return _run_experiment_ids(conn, entity_id)
    if entity_type == "job":
        return _job_experiment_ids(conn, entity_id)
    if entity_type == "artifact":
        return _artifact_experiment_ids(conn, entity_id)
    return set()


def _run_experiment_ids(conn: sqlite3.Connection, run_id: str) -> set[str]:
    ids = {
        str(row["experiment_id"])
        for row in conn.execute(
            "SELECT experiment_id FROM experiment_runs WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        if row["experiment_id"]
    }
    row = conn.execute("SELECT experiment_id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row and row["experiment_id"]:
        ids.add(str(row["experiment_id"]))
    return ids


def _job_experiment_ids(conn: sqlite3.Connection, job_id: str) -> set[str]:
    ids: set[str] = set()
    row = conn.execute("SELECT experiment_id, run_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return ids
    if row["experiment_id"]:
        ids.add(str(row["experiment_id"]))
    if row["run_id"]:
        ids.update(_run_experiment_ids(conn, str(row["run_id"])))
    for edge in conn.execute("SELECT run_id FROM job_runs WHERE job_id = ? AND deleted_at IS NULL", (job_id,)).fetchall():
        ids.update(_run_experiment_ids(conn, str(edge["run_id"])))
    return ids


def _artifact_experiment_ids(conn: sqlite3.Connection, artifact_id: str) -> set[str]:
    ids: set[str] = set()
    row = conn.execute("SELECT experiment_id, run_id, job_id FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not row:
        return ids
    if row["experiment_id"]:
        ids.add(str(row["experiment_id"]))
    if row["run_id"]:
        ids.update(_run_experiment_ids(conn, str(row["run_id"])))
    if row["job_id"]:
        ids.update(_job_experiment_ids(conn, str(row["job_id"])))
    return ids


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _envelope(
    *,
    ledger_path: Path,
    schema: int,
    checks: list[str],
    issues: list[DoctorIssue],
) -> dict[str, Any]:
    issue_rows = [issue.to_dict() for issue in issues]
    return {
        "envelope_version": 1,
        "generated_at": utc_now(),
        "ledger": str(ledger_path),
        "schema_version": schema,
        "checks": checks,
        "ok": not any(issue["severity"] == "error" for issue in issue_rows),
        "issue_count": len(issue_rows),
        "issues": issue_rows,
    }


def _check_attrs_json(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for table in ATTR_TABLES:
        for row in conn.execute(f"SELECT id, attrs_json FROM {table}").fetchall():
            try:
                decoded = json.loads(row["attrs_json"])
            except (TypeError, ValueError):
                decoded = None
            if not isinstance(decoded, dict):
                issues.append(
                    DoctorIssue(
                        code="attrs.invalid_json",
                        severity="error",
                        entity_type=_entity_type_for_table(table),
                        entity_id=row["id"],
                        message=f"{table}.attrs_json must decode to an object",
                        details={"table": table},
                        suggested_next_action="Repair attrs_json through a controlled migration or reconcile update.",
                    )
                )
    return issues


def _check_note_entity(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    rows = conn.execute(
        "SELECT id, entity_type, entity_id, attrs_json FROM notes WHERE deleted_at IS NULL ORDER BY updated_at, id"
    ).fetchall()
    for row in rows:
        attrs = json.loads(row["attrs_json"])
        table = ENTITY_TABLES.get(row["entity_type"])
        if table is None:
            missing = True
            deleted = False
        else:
            target = conn.execute(f"SELECT deleted_at FROM {table} WHERE id = ?", (row["entity_id"],)).fetchone()
            missing = target is None
            deleted = bool(target and target["deleted_at"] is not None)
        if deleted and attrs.get("fieldbook.erratum") is True:
            continue
        if missing or deleted:
            issues.append(
                DoctorIssue(
                    code="dangling.note_entity",
                    severity="error",
                    entity_type="note",
                    entity_id=row["id"],
                    message="note references a missing or archived entity",
                    details={
                        "target_entity_type": row["entity_type"],
                        "target_entity_id": row["entity_id"],
                        "target_missing": missing,
                        "target_deleted": deleted,
                    },
                    suggested_next_action="Inspect the note and archive or retarget it with a reconcile manifest.",
                )
            )
    return issues


def _check_local_artifacts(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    rows = conn.execute("SELECT id, uri FROM artifacts WHERE deleted_at IS NULL ORDER BY updated_at, id").fetchall()
    for row in rows:
        path = _local_artifact_path(row["uri"], cwd=options.cwd)
        if path is None:
            continue
        if not path.exists():
            issues.append(
                DoctorIssue(
                    code="artifact.local_missing",
                    severity="error",
                    entity_type="artifact",
                    entity_id=row["id"],
                    message="local artifact path does not exist",
                    details={"uri": row["uri"], "path": str(path)},
                    suggested_next_action="Refresh the artifact URI, recreate the file, or archive the artifact.",
                )
            )
            continue
        if not os.access(path, os.R_OK):
            issues.append(
                DoctorIssue(
                    code="artifact.local_unreadable",
                    severity="error",
                    entity_type="artifact",
                    entity_id=row["id"],
                    message="local artifact path is not readable",
                    details={"uri": row["uri"], "path": str(path)},
                    suggested_next_action="Fix permissions or update the artifact URI.",
                )
            )
    return issues


def _check_stale_jobs(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    cutoff = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=options.stale_hours)
    ).isoformat().replace("+00:00", "Z")
    rows = conn.execute(
        "SELECT id, name, status, updated_at FROM jobs WHERE deleted_at IS NULL "
        "AND status IN (?, ?) AND updated_at < ? ORDER BY updated_at, id",
        (*STALE_JOB_STATUSES, cutoff),
    ).fetchall()
    issues: list[DoctorIssue] = []
    for row in rows:
        recent_sync = conn.execute(
            "SELECT 1 FROM sync_events WHERE job_id = ? AND created_at >= ? LIMIT 1",
            (row["id"], cutoff),
        ).fetchone()
        if recent_sync:
            continue
        issues.append(
            DoctorIssue(
                code="job.stale_active",
                severity="warning",
                entity_type="job",
                entity_id=row["id"],
                message="queued/running job has not been updated recently",
                details={"status": row["status"], "updated_at": row["updated_at"], "stale_hours": options.stale_hours},
                suggested_next_action="Refresh external job state and reconcile the result.",
            )
        )
    return issues


def _check_external_ids(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for table in ("runs", "jobs"):
        entity_type = _entity_type_for_table(table)
        active_duplicates = conn.execute(
            f"SELECT external_system, external_id, GROUP_CONCAT(id, ', ') AS ids, COUNT(*) AS n "
            f"FROM {table} WHERE deleted_at IS NULL AND external_system IS NOT NULL AND external_id IS NOT NULL "
            f"GROUP BY external_system, external_id HAVING COUNT(*) > 1"
        ).fetchall()
        for row in active_duplicates:
            issues.append(
                DoctorIssue(
                    code="external_id.duplicate_active",
                    severity="error",
                    entity_type=entity_type,
                    message="active rows share an external identifier",
                    details=dict(row),
                    suggested_next_action="Archive or update duplicate external identifiers through reconcile.",
                )
            )
        archived_duplicates = conn.execute(
            f"SELECT active.external_system, active.external_id, active.id AS active_id, archived.id AS archived_id "
            f"FROM {table} active JOIN {table} archived "
            f"ON active.external_system = archived.external_system AND active.external_id = archived.external_id "
            f"WHERE active.deleted_at IS NULL AND archived.deleted_at IS NOT NULL "
            f"AND active.external_system IS NOT NULL AND active.external_id IS NOT NULL"
        ).fetchall()
        for row in archived_duplicates:
            issues.append(
                DoctorIssue(
                    code="external_id.duplicate_archived",
                    severity="warning",
                    entity_type=entity_type,
                    entity_id=row["active_id"],
                    message="active row reuses an external identifier from an archived row",
                    details=dict(row),
                    suggested_next_action="Confirm the archived row is historical and not a mistaken duplicate.",
                )
            )
    return issues


def _check_sync_events(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    soft_deleted = conn.execute(
        "SELECT se.id, se.run_id, se.job_id, r.deleted_at AS run_deleted_at, j.deleted_at AS job_deleted_at "
        "FROM sync_events se "
        "LEFT JOIN runs r ON r.id = se.run_id "
        "LEFT JOIN jobs j ON j.id = se.job_id "
        "WHERE (se.run_id IS NOT NULL AND r.deleted_at IS NOT NULL) "
        "OR (se.job_id IS NOT NULL AND j.deleted_at IS NOT NULL)"
    ).fetchall()
    for row in soft_deleted:
        issues.append(
            DoctorIssue(
                code="sync_event.dangling_entity",
                severity="warning",
                entity_type="sync_event",
                entity_id=row["id"],
                message="sync event references an archived run or job",
                details=dict(row),
                suggested_next_action="Confirm the sync event remains useful provenance for the archived entity.",
            )
        )
    duplicates = conn.execute(
        "SELECT target_system, COALESCE(target_identifier, '') AS target_identifier, idempotency_key, "
        "GROUP_CONCAT(id, ', ') AS ids, COUNT(*) AS n FROM sync_events "
        "WHERE idempotency_key IS NOT NULL AND origin = 'manifest' "
        "GROUP BY target_system, COALESCE(target_identifier, ''), idempotency_key "
        "HAVING COUNT(*) > 1"
    ).fetchall()
    for row in duplicates:
        issues.append(
            DoctorIssue(
                code="sync_event.duplicate_idempotency_key",
                severity="warning",
                entity_type="sync_event",
                message="sync events share an idempotency key",
                details=dict(row),
                suggested_next_action="Inspect duplicate sync events and confirm reconcile idempotency.",
            )
        )
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_options.stale_hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    failed_writebacks = conn.execute(
        "WITH ranked AS ("
        "SELECT id, run_id, source_entity_id, target_identifier, target_field, error_message, created_at, status, "
        "ROW_NUMBER() OVER (PARTITION BY target_system, COALESCE(target_identifier, ''), idempotency_key "
        "ORDER BY created_at DESC, id DESC) AS rn "
        "FROM sync_events WHERE origin = 'writeback' AND idempotency_key IS NOT NULL"
        ") "
        "SELECT id, run_id, source_entity_id, target_identifier, target_field, error_message, created_at "
        "FROM ranked WHERE rn = 1 AND status = 'failed' AND created_at <= ? "
        "ORDER BY created_at DESC, id DESC",
        (cutoff,),
    ).fetchall()
    for row in failed_writebacks:
        issues.append(
            DoctorIssue(
                code="sync_event.failed_writeback",
                severity="warning",
                entity_type="sync_event",
                entity_id=row["id"],
                message="writeback sync event failed and may need retry",
                details=dict(row),
                suggested_next_action="Inspect writeback log and rerun the explicit writeback command if appropriate.",
            )
        )
    return issues


def _check_reconcile_log(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for table, columns in {
        "reconcile_events": ["inserts_json", "updates_json", "counts_json", "attrs_json"],
        "reconcile_operations": ["input_json", "diff_json"],
    }.items():
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            for column in columns:
                try:
                    json.loads(row[column])
                except (TypeError, ValueError):
                    issues.append(
                        DoctorIssue(
                            code="reconcile_log.anomaly",
                            severity="error",
                            entity_type=table.rstrip("s"),
                            entity_id=row["id"],
                            message=f"{table}.{column} is not valid JSON",
                            details={"table": table, "column": column},
                            suggested_next_action="Inspect reconcile log rows and repair only through a controlled migration.",
                        )
                    )
    orphaned = conn.execute(
        "SELECT ro.id, ro.reconcile_event_id FROM reconcile_operations ro "
        "LEFT JOIN reconcile_events re ON re.id = ro.reconcile_event_id WHERE re.id IS NULL"
    ).fetchall()
    for row in orphaned:
        issues.append(
            DoctorIssue(
                code="reconcile_log.anomaly",
                severity="error",
                entity_type="reconcile_operation",
                entity_id=row["id"],
                message="reconcile operation references a missing event",
                details=dict(row),
                suggested_next_action="Inspect reconcile log rows and repair only through a controlled migration.",
            )
        )
    return issues


def _check_stale_sessions(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    cutoff = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=options.stale_session_hours)
    ).isoformat().replace("+00:00", "Z")
    rows = conn.execute(
        "SELECT id, experiment_id, agent, cwd, started_at, last_touch_at FROM sessions "
        "WHERE ended_at IS NULL AND last_touch_at < ? ORDER BY last_touch_at, id",
        (cutoff,),
    ).fetchall()
    return [
        DoctorIssue(
            code="session.stale_open",
            severity="warning",
            entity_type="session",
            entity_id=row["id"],
            message="open session has not been touched recently",
            details={
                "experiment_id": row["experiment_id"],
                "agent": row["agent"],
                "cwd": row["cwd"],
                "started_at": row["started_at"],
                "last_touch_at": row["last_touch_at"],
                "stale_session_hours": options.stale_session_hours,
            },
            suggested_next_action=f"Run `fieldbook session end --id {row['id']} --force` if this session is stale.",
        )
        for row in rows
    ]


def _check_job_recovery(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    cutoff_submitting = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=options.stale_submitting_hours)
    ).isoformat().replace("+00:00", "Z")
    cutoff_unknown = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=options.stale_unknown_submit_hours)
    ).isoformat().replace("+00:00", "Z")
    for row in conn.execute(
        "SELECT id, name, status, updated_at FROM jobs WHERE deleted_at IS NULL AND status = 'submitting' "
        "AND updated_at < ? ORDER BY updated_at, id",
        (cutoff_submitting,),
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="job_submission.submitting_stale",
                severity="warning",
                entity_type="job",
                entity_id=row["id"],
                message="job submission has not been acknowledged recently",
                details={"status": row["status"], "updated_at": row["updated_at"]},
                suggested_next_action="Refresh external job state or correct the job status.",
            )
        )
    for row in conn.execute(
        "SELECT id, name, status, updated_at FROM jobs WHERE deleted_at IS NULL AND status = 'unknown_submit' "
        "AND updated_at < ? ORDER BY updated_at, id",
        (cutoff_unknown,),
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="job_submission.unknown_stale",
                severity="warning",
                entity_type="job",
                entity_id=row["id"],
                message="ambiguous job submission has not been resolved recently",
                details={"status": row["status"], "updated_at": row["updated_at"]},
                suggested_next_action="Refresh external job state, mark failed, or resubmit with retry lineage.",
            )
        )
    for row in conn.execute(
        "SELECT id, retry_of FROM jobs WHERE deleted_at IS NULL AND retry_of IS NOT NULL ORDER BY updated_at, id"
    ).fetchall():
        target = conn.execute("SELECT id FROM jobs WHERE id = ? AND deleted_at IS NULL", (row["retry_of"],)).fetchone()
        if target is None:
            issues.append(
                DoctorIssue(
                    code="job_retry.missing_target",
                    severity="error",
                    entity_type="job",
                    entity_id=row["id"],
                    message="retry job references a missing or archived target",
                    details={"retry_of": row["retry_of"]},
                    suggested_next_action="Repair retry lineage through a controlled update.",
                )
            )
    for job_id, path in _retry_cycles(conn):
        issues.append(
            DoctorIssue(
                code="job_retry.cycle",
                severity="error",
                entity_type="job",
                entity_id=job_id,
                message="job retry lineage contains a cycle",
                details={"path": path},
                suggested_next_action="Break the retry cycle through a controlled update.",
            )
        )
    for row in _retry_loops(conn, threshold=options.retry_loop_threshold):
        issues.append(
            DoctorIssue(
                code="job_retry.loop",
                severity="warning",
                entity_type="job",
                entity_id=row["root_id"],
                message="job retry chain exceeds the configured loop threshold without a successful descendant",
                details=row,
                suggested_next_action="Inspect the retry chain before launching another retry.",
            )
        )
    stale_cutoff = (
        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=options.stale_hours)
    ).isoformat().replace("+00:00", "Z")
    for row in conn.execute(
        "SELECT r.job_id AS failed_job_id, r.active_descendant_id, child.status, child.updated_at "
        "FROM v_jobs_with_recovery_v1 r "
        "JOIN jobs child ON child.id = r.active_descendant_id "
        "WHERE r.retry_state = 'recovery_in_progress' AND child.updated_at < ? "
        "ORDER BY child.updated_at, r.job_id",
        (stale_cutoff,),
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="job_retry.recovery_stale",
                severity="warning",
                entity_type="job",
                entity_id=row["failed_job_id"],
                message="retry recovery is still in progress and has not updated recently",
                details=dict(row),
                suggested_next_action="Refresh external state for the retry or mark the recovery failed.",
            )
        )
    for row in conn.execute(
        "SELECT r.job_id, r.experiment_id, r.success_descendant_id FROM v_jobs_with_recovery_v1 r "
        "WHERE r.retry_state = 'recovered_failed' AND EXISTS ("
        "SELECT 1 FROM notes n WHERE n.deleted_at IS NULL AND n.note_type = 'debug' AND n.status = 'open' "
        "AND ((n.entity_type = 'job' AND n.entity_id = r.job_id) "
        "OR (n.entity_type = 'experiment' AND n.entity_id = r.experiment_id))"
        ") ORDER BY r.job_id"
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="job_retry.recovered_debug_open",
                severity="warning",
                entity_type="job",
                entity_id=row["job_id"],
                message="recovered failed job still has an open debug note",
                details=dict(row),
                suggested_next_action="Resolve or supersede the debug note if the recovery is complete.",
            )
        )
    return issues


def _check_validations(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for row in conn.execute(
        "SELECT id, entity_type, entity_id, check_name, status FROM validations "
        "WHERE deleted_at IS NULL AND status = 'fail' ORDER BY updated_at, id"
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="validation.failed",
                severity="warning",
                entity_type="validation",
                entity_id=row["id"],
                message="active validation is failing",
                details=dict(row),
                suggested_next_action="Inspect validation evidence and rerun or fix the underlying experiment step.",
            )
        )
    for row in conn.execute(
        "SELECT id, entity_type, entity_id, check_name, status FROM validations "
        "WHERE deleted_at IS NULL AND status = 'unknown' AND INSTR(attrs_json, '\"validation.blocking\":true') > 0 "
        "ORDER BY updated_at, id"
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="validation.unknown_blocking",
                severity="warning",
                entity_type="validation",
                entity_id=row["id"],
                message="active validation has unknown blocking status",
                details=dict(row),
                suggested_next_action="Refresh or recompute the validation check.",
            )
        )
    return issues


def _check_leases(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_z = now.isoformat().replace("+00:00", "Z")
    stale_cutoff = (now - timedelta(hours=options.stale_lease_hours)).isoformat().replace("+00:00", "Z")
    rows = conn.execute("SELECT * FROM leases WHERE released_at IS NULL ORDER BY heartbeat_at, id").fetchall()
    for row in rows:
        lease_id = row["id"]
        details = dict(row)
        if row["heartbeat_at"] < stale_cutoff:
            issues.append(
                DoctorIssue(
                    code="lease.stale_heartbeat",
                    severity="warning",
                    entity_type="lease",
                    entity_id=lease_id,
                    message="active lease heartbeat is stale",
                    details=details,
                    suggested_next_action="Heartbeat, release, or explicitly take over the stale advisory lease.",
                )
            )
        if row["expires_at"] is not None and row["expires_at"] <= now_z:
            issues.append(
                DoctorIssue(
                    code="lease.expired",
                    severity="warning",
                    entity_type="lease",
                    entity_id=lease_id,
                    message="active lease has expired but has not been released",
                    details=details,
                    suggested_next_action="Release the lease or claim it from the next active agent.",
                )
            )
        if row["session_id"]:
            session = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (row["session_id"],)).fetchone()
            if session and session["ended_at"] is not None:
                issues.append(
                    DoctorIssue(
                        code="lease.outlived_session",
                        severity="warning",
                        entity_type="lease",
                        entity_id=lease_id,
                        message="active lease references an ended session",
                        details=details,
                        suggested_next_action="Release or re-claim the lease from the current session.",
                    )
                )
            if session is None:
                issues.append(
                    DoctorIssue(
                        code="lease.orphaned",
                        severity="warning",
                        entity_type="lease",
                        entity_id=lease_id,
                        message="active lease references a missing session",
                        details=details,
                        suggested_next_action="Release or force-takeover the orphaned lease.",
                    )
                )
        entity = _lease_entity_row(conn, row["entity_type"], row["entity_id"])
        if entity is None:
            issues.append(
                DoctorIssue(
                    code="lease.orphaned",
                    severity="warning",
                    entity_type="lease",
                    entity_id=lease_id,
                    message="active lease references a missing entity",
                    details=details,
                    suggested_next_action="Release or force-takeover the orphaned lease.",
                )
            )
        elif "deleted_at" in entity.keys() and entity["deleted_at"] is not None:
            issues.append(
                DoctorIssue(
                    code="lease.archived_entity",
                    severity="warning",
                    entity_type="lease",
                    entity_id=lease_id,
                    message="active lease references an archived or deleted entity",
                    details=details,
                    suggested_next_action="Release the lease or record a handoff on an active experiment.",
                )
            )
    for row in conn.execute(
        "SELECT entity_type, entity_id, COUNT(*) AS count FROM leases WHERE released_at IS NULL "
        "GROUP BY entity_type, entity_id HAVING COUNT(*) > 1"
    ).fetchall():
        issues.append(
            DoctorIssue(
                code="lease.conflicting_active",
                severity="error",
                entity_type="lease",
                entity_id=f"{row['entity_type']}:{row['entity_id']}",
                message="entity has multiple active leases",
                details=dict(row),
                suggested_next_action="Repair duplicate active leases through a controlled migration.",
            )
        )
    return issues


def _lease_entity_row(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> sqlite3.Row | None:
    table = {"experiment": "experiments", "run": "runs", "job": "jobs"}.get(entity_type)
    if table is None:
        return None
    return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()


def _check_artifact_local_drift(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for row in drifted_artifacts(conn, cwd=options.cwd, limit=1_000_000):
        issues.append(
            DoctorIssue(
                code="artifact.local_drift",
                severity="warning",
                entity_type="artifact",
                entity_id=row["id"],
                message="local artifact metadata differs from captured metadata",
                details=row,
                suggested_next_action="Run `fieldbook artifact refresh-local` after deciding the drift is expected.",
            )
        )
    return issues


def _check_validation_source_drift(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for row in stale_validations(conn, cwd=options.cwd, limit=1_000_000):
        issues.append(
            DoctorIssue(
                code="validation.source_drift",
                severity="warning",
                entity_type="validation",
                entity_id=row["id"],
                message="validation source artifact changed after validation",
                details=row,
                suggested_next_action="Rerun the validation or record a new validation erratum.",
            )
        )
    return issues


def _check_experiment_checkpoint_stale(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    for row in conn.execute("SELECT id, name FROM experiments WHERE deleted_at IS NULL ORDER BY updated_at, id").fetchall():
        freshness = experiment_freshness(
            conn,
            experiment_id=row["id"],
            cwd=options.cwd,
            stale_checkpoint_hours=options.stale_hours,
        )
        if freshness["checkpoint_status"] not in {"missing", "stale"}:
            continue
        issues.append(
            DoctorIssue(
                code="experiment.checkpoint_stale",
                severity="warning",
                entity_type="experiment",
                entity_id=row["id"],
                message="experiment has activity without a current checkpoint",
                details={
                    "name": row["name"],
                    "checkpoint_status": freshness["checkpoint_status"],
                    "last_checkpoint_at": freshness["last_checkpoint_at"],
                    "since_last_checkpoint_hours": freshness["since_last_checkpoint_hours"],
                },
                suggested_next_action="Run `fieldbook experiment checkpoint` before context switching or archiving.",
            )
        )
    return issues


def _check_secret_patterns(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    scans = [
        ("job", "jobs", "id", "command", "SELECT id, command FROM jobs WHERE deleted_at IS NULL AND command IS NOT NULL"),
        (
            "note",
            "notes",
            "id",
            "body",
            "SELECT id, body FROM notes WHERE deleted_at IS NULL AND body IS NOT NULL",
        ),
    ]
    scans.extend(
        (
            _entity_type_for_table(table),
            table,
            "id",
            "attrs_json",
            _attrs_secret_query(table),
        )
        for table in ATTR_TABLES
    )
    for entity_type, _table, id_column, field, query in scans:
        for row in conn.execute(query).fetchall():
            text = row[field] or ""
            for family, pattern in SECRET_PATTERNS.items():
                match = pattern.search(text)
                if not match:
                    continue
                issues.append(
                    DoctorIssue(
                        code="privacy.secret_pattern",
                        severity="warning",
                        entity_type=entity_type,
                        entity_id=row[id_column],
                        message="possible secret pattern found in ledger text",
                        details={"field": field, "pattern_family": family, "snippet": _redacted_snippet(match.group(0))},
                        suggested_next_action="Move secrets out of Fieldbook text and rotate the secret if it was exposed.",
                    )
                )
    return issues


def _check_refresh_events(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    cutoff = datetime.now(timezone.utc).timestamp() - options.stale_refresh_snapshot_days * 24 * 60 * 60
    for row in conn.execute(
        "SELECT * FROM v_refresh_log_v1 ORDER BY finished_at DESC, refresh_event_id DESC"
    ).fetchall():
        if row["status"] == "failed":
            issues.append(
                DoctorIssue(
                    code="refresh.failed",
                    severity="warning",
                    entity_type="refresh_event",
                    entity_id=row["refresh_event_id"],
                    message="refresh event failed",
                    details={"source": row["source"], "stage": row["stage"], "error_message": row["error_message"]},
                    suggested_next_action="Inspect the refresh debug files and rerun the source after fixing the cause.",
                )
            )
        for column in ("snapshot_path", "manifest_path", "debug_path"):
            raw_path = row[column]
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.exists():
                issues.append(
                    DoctorIssue(
                        code="refresh.snapshot_missing",
                        severity="warning",
                        entity_type="refresh_event",
                        entity_id=row["refresh_event_id"],
                        message="refresh event references a missing snapshot/debug file",
                        details={"source": row["source"], "path": raw_path, "path_column": column},
                        suggested_next_action="Re-run the refresh source or archive/move stale local diagnostics deliberately.",
                    )
                )
                continue
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            if modified < cutoff:
                issues.append(
                    DoctorIssue(
                        code="refresh.snapshot_stale",
                        severity="warning",
                        entity_type="refresh_event",
                        entity_id=row["refresh_event_id"],
                        message="refresh snapshot/debug file is older than the configured threshold",
                        details={
                            "source": row["source"],
                            "path": raw_path,
                            "path_column": column,
                            "stale_refresh_snapshot_days": options.stale_refresh_snapshot_days,
                        },
                        suggested_next_action="Refresh the source again if this snapshot is still used for current decisions.",
                    )
                )
            issues.extend(_secret_file_issues(path, row=row, path_column=column))
        if row["status"] == "dry_run" and row["manifest_path"]:
            issues.append(
                DoctorIssue(
                    code="refresh.manifest_unapplied",
                    severity="warning",
                    entity_type="refresh_event",
                    entity_id=row["refresh_event_id"],
                    message="refresh dry-run manifest has not been applied",
                    details={"source": row["source"], "manifest_path": row["manifest_path"]},
                    suggested_next_action="Inspect the manifest and rerun refresh with --apply if the plan is correct.",
                )
            )
    return issues


def _secret_file_issues(path: Path, *, row: sqlite3.Row, path_column: str) -> list[DoctorIssue]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    issues: list[DoctorIssue] = []
    for family, pattern in SECRET_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        issues.append(
            DoctorIssue(
                code="privacy.secret_pattern",
                severity="warning",
                entity_type="refresh_event",
                entity_id=row["refresh_event_id"],
                message="possible secret pattern found in refresh snapshot/debug file",
                details={
                    "source": row["source"],
                    "path": str(path),
                    "path_column": path_column,
                    "pattern_family": family,
                    "snippet": _redacted_snippet(match.group(0)),
                },
                suggested_next_action="Treat refresh snapshots as local sensitive diagnostics; remove or sanitize if sharing.",
            )
        )
    return issues


def _attrs_secret_query(table: str) -> str:
    if table in {"reconcile_events", "sync_events", "sessions", "refresh_events"}:
        return f"SELECT id, attrs_json FROM {table} WHERE attrs_json IS NOT NULL"
    return f"SELECT id, attrs_json FROM {table} WHERE deleted_at IS NULL AND attrs_json IS NOT NULL"


def _retry_cycles(conn: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    rows = conn.execute("SELECT id, retry_of FROM jobs WHERE deleted_at IS NULL").fetchall()
    graph = {row["id"]: row["retry_of"] for row in rows if row["retry_of"] is not None}
    cycles: list[tuple[str, list[str]]] = []
    reported: set[str] = set()
    for start in graph:
        seen: list[str] = []
        current = start
        while current in graph:
            if current in seen:
                cycle = seen[seen.index(current) :] + [current]
                key = ",".join(sorted(set(cycle)))
                if key not in reported:
                    reported.add(key)
                    cycles.append((start, cycle))
                break
            seen.append(current)
            current = graph[current]
    return cycles


def _retry_loops(conn: sqlite3.Connection, *, threshold: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, retry_of, status FROM jobs WHERE deleted_at IS NULL").fetchall()
    children: dict[str, list[sqlite3.Row]] = {}
    status_by_id: dict[str, str] = {}
    for row in rows:
        status_by_id[row["id"]] = row["status"]
        if row["retry_of"] is not None:
            children.setdefault(row["retry_of"], []).append(row)
    loops: list[dict[str, Any]] = []
    for root_id, root_status in status_by_id.items():
        if root_status != "failed":
            continue
        stack: list[tuple[str, int, list[str]]] = [(root_id, 0, [root_id])]
        max_depth = 0
        has_success = False
        while stack:
            node_id, depth, path = stack.pop()
            max_depth = max(max_depth, depth)
            for child in children.get(node_id, []):
                child_path = [*path, child["id"]]
                if child["status"] == "succeeded":
                    has_success = True
                if child["id"] in path:
                    continue
                stack.append((child["id"], depth + 1, child_path))
        if max_depth > threshold and not has_success:
            loops.append({"root_id": root_id, "max_retry_depth": max_depth, "retry_loop_threshold": threshold})
    return loops


def _redacted_snippet(value: str) -> str:
    if len(value) <= 8:
        return "<redacted>"
    return f"{value[:4]}...{value[-4:]}"


def _check_ledger_locality(_conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    if options.resolved_via in {"--ledger", "FIELDBOOK_LEDGER", ".fieldbook"}:
        return []
    if options.ledger_path != options.cwd.resolve() / ".experiments" / "ledger.sqlite":
        return []
    siblings = []
    parent = options.cwd.resolve().parent
    cutoff = datetime.now(timezone.utc).timestamp() - options.locality_recent_days * 24 * 60 * 60
    for candidate in parent.glob("*/.experiments/ledger.sqlite"):
        if candidate.resolve() == options.ledger_path.resolve():
            continue
        try:
            modified = candidate.stat().st_mtime
        except OSError:
            continue
        if modified >= cutoff:
            siblings.append(str(candidate.resolve()))
    if not siblings:
        return []
    return [
        DoctorIssue(
            code="ledger.locality_split_possible",
            severity="warning",
            message="implicit cwd-walk resolved a local ledger while adjacent recent ledgers exist",
            details={
                "resolved_ledger": str(options.ledger_path),
                "adjacent_ledgers": sorted(siblings),
                "locality_recent_days": options.locality_recent_days,
            },
            suggested_next_action="Run `fieldbook db where --json`; use --ledger, FIELDBOOK_LEDGER, or .fieldbook if a shared ledger was intended.",
        )
    ]


def _local_artifact_path(uri: str, *, cwd: Path) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme in {"gs", "s3", "http", "https"}:
        return None
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).expanduser()
        return path if path.is_absolute() else cwd / path
    if parsed.scheme:
        return None
    path = Path(uri).expanduser()
    return path if path.is_absolute() else cwd / path


def _entity_type_for_table(table: str) -> str:
    if table.endswith("ies"):
        return table[:-3] + "y"
    if table.endswith("s"):
        return table[:-1]
    return table


def _check_expected_runs(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    rows = conn.execute(
        "SELECT id, name, attrs_json FROM experiments WHERE deleted_at IS NULL ORDER BY updated_at DESC, id"
    ).fetchall()
    for row in rows:
        attrs = json.loads(row["attrs_json"])
        expected = attrs.get("progress.expected_runs")
        if not isinstance(expected, int | float):
            continue
        actual = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE experiment_id = ? AND deleted_at IS NULL",
            (row["id"],),
        ).fetchone()[0]
        missing = max(int(expected) - int(actual), 0)
        if missing == 0:
            continue
        issues.append(
            DoctorIssue(
                code="runs.expected_missing",
                severity="warning",
                entity_type="experiment",
                entity_id=row["id"],
                message="experiment has fewer active runs than its progress.expected_runs target",
                details={"expected_runs": int(expected), "actual_runs": int(actual), "missing_runs": missing},
                suggested_next_action="Reconcile the launch manifest or correct progress.expected_runs.",
            )
        )
    return issues


def _check_unlinked_run_artifacts(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    rows = conn.execute(
        "SELECT id, experiment_id, type, uri FROM artifacts WHERE deleted_at IS NULL "
        "AND run_id IS NULL AND type IN ('checkpoint', 'eval-result') ORDER BY updated_at DESC, id"
    ).fetchall()
    return [
        DoctorIssue(
            code="artifact.unlinked_to_run",
            severity="warning",
            entity_type="artifact",
            entity_id=row["id"],
            message="run-scoped artifact type is not linked to a run",
            details={"experiment_id": row["experiment_id"], "type": row["type"], "uri": row["uri"]},
            suggested_next_action="Attach the artifact to its run or record it as a non-run artifact type.",
        )
        for row in rows
    ]


def _check_job_runs(conn: sqlite3.Connection, _options: DoctorOptions) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []
    stale_rows = conn.execute(
        "SELECT jr.job_id, jr.run_id, jr.role, jr.status AS edge_status, j.status AS job_status "
        "FROM job_runs jr JOIN jobs j ON j.id = jr.job_id JOIN runs r ON r.id = jr.run_id "
        "WHERE jr.deleted_at IS NULL AND j.deleted_at IS NULL AND r.deleted_at IS NULL "
        "AND jr.status IN ('planned', 'submitting', 'unknown_submit', 'queued', 'running', 'unknown') "
        "AND j.status IN ('succeeded', 'failed', 'killed', 'skipped') "
        "ORDER BY jr.updated_at DESC, jr.job_id, jr.run_id"
    ).fetchall()
    for row in stale_rows:
        issues.append(
            DoctorIssue(
                code="job_runs.stale_state",
                severity="warning",
                entity_type="job_run",
                entity_id=f"{row['job_id']}:{row['run_id']}",
                message="job/run edge has active or unknown status while parent job is terminal",
                details={
                    "job_id": row["job_id"],
                    "run_id": row["run_id"],
                    "role": row["role"],
                    "edge_status": row["edge_status"],
                    "job_status": row["job_status"],
                },
                suggested_next_action="Refresh child-run state or update the job/run edge status.",
            )
        )
    orphan_rows = conn.execute(
        "SELECT jr.job_id, jr.run_id FROM job_runs jr "
        "LEFT JOIN jobs j ON j.id = jr.job_id "
        "LEFT JOIN runs r ON r.id = jr.run_id "
        "WHERE jr.deleted_at IS NULL AND (j.id IS NULL OR r.id IS NULL OR j.deleted_at IS NOT NULL OR r.deleted_at IS NOT NULL) "
        "ORDER BY jr.updated_at DESC, jr.job_id, jr.run_id"
    ).fetchall()
    for row in orphan_rows:
        issues.append(
            DoctorIssue(
                code="job_runs.orphan",
                severity="error",
                entity_type="job_run",
                entity_id=f"{row['job_id']}:{row['run_id']}",
                message="job/run edge references a missing or archived job/run",
                details={"job_id": row["job_id"], "run_id": row["run_id"]},
                suggested_next_action="Archive the stale edge or restore the referenced entity.",
            )
        )
    return issues


def _check_job_run_stale_state(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    return [issue for issue in _check_job_runs(conn, options) if issue.code == "job_runs.stale_state"]


def _check_job_run_orphans(conn: sqlite3.Connection, options: DoctorOptions) -> list[DoctorIssue]:
    return [issue for issue in _check_job_runs(conn, options) if issue.code == "job_runs.orphan"]


DOCTOR_CHECKS: dict[str, DoctorCheck] = {
    "attrs-json": DoctorCheck(
        id="attrs-json",
        description="Validate attrs_json columns decode to JSON objects.",
        default_enabled=True,
        severity="error",
        runner=_check_attrs_json,
    ),
    "note-entity": DoctorCheck(
        id="note-entity",
        description="Detect notes pointing at missing or archived entities.",
        default_enabled=True,
        severity="error",
        runner=_check_note_entity,
    ),
    "local-artifacts": DoctorCheck(
        id="local-artifacts",
        description="Detect missing or unreadable local artifact paths.",
        default_enabled=True,
        severity="error",
        runner=_check_local_artifacts,
    ),
    "stale-jobs": DoctorCheck(
        id="stale-jobs",
        description="Detect queued/running jobs with stale updates and no recent sync event.",
        default_enabled=True,
        severity="warning",
        runner=_check_stale_jobs,
    ),
    "external-ids": DoctorCheck(
        id="external-ids",
        description="Detect duplicate or reused external identifiers.",
        default_enabled=True,
        severity="warning",
        runner=_check_external_ids,
    ),
    "sync-events": DoctorCheck(
        id="sync-events",
        description="Detect sync-event soft-delete and idempotency anomalies.",
        default_enabled=True,
        severity="warning",
        runner=_check_sync_events,
    ),
    "reconcile-log": DoctorCheck(
        id="reconcile-log",
        description="Detect reconcile audit JSON and parent-event anomalies.",
        default_enabled=True,
        severity="error",
        runner=_check_reconcile_log,
    ),
    "stale-sessions": DoctorCheck(
        id="stale-sessions",
        description="Detect advisory sessions that have not been touched recently.",
        default_enabled=True,
        severity="warning",
        runner=_check_stale_sessions,
    ),
    "leases": DoctorCheck(
        id="leases",
        description="Detect stale, expired, orphaned, and archived advisory leases.",
        default_enabled=True,
        severity="warning",
        runner=_check_leases,
    ),
    "ledger-locality": DoctorCheck(
        id="ledger-locality",
        description="Detect likely implicit local ledger splits across adjacent worktrees.",
        default_enabled=True,
        severity="warning",
        runner=_check_ledger_locality,
    ),
    "job-recovery": DoctorCheck(
        id="job-recovery",
        description="Detect retry lineage and submission lifecycle issues.",
        default_enabled=True,
        severity="warning",
        runner=_check_job_recovery,
    ),
    "validations": DoctorCheck(
        id="validations",
        description="Detect failed structured validations.",
        default_enabled=True,
        severity="warning",
        runner=_check_validations,
    ),
    "privacy": DoctorCheck(
        id="privacy",
        description="Detect suspected secrets in ledger text fields.",
        default_enabled=True,
        severity="warning",
        runner=_check_secret_patterns,
    ),
    "refresh": DoctorCheck(
        id="refresh",
        description="Detect failed refreshes, stale snapshots, and unapplied refresh manifests.",
        default_enabled=True,
        severity="warning",
        runner=_check_refresh_events,
    ),
    "artifact.local_drift": DoctorCheck(
        id="artifact.local_drift",
        description="Detect local artifact files whose captured metadata drifted.",
        default_enabled=True,
        severity="warning",
        runner=_check_artifact_local_drift,
    ),
    "validation.source_drift": DoctorCheck(
        id="validation.source_drift",
        description="Detect validations whose source artifacts changed.",
        default_enabled=True,
        severity="warning",
        runner=_check_validation_source_drift,
    ),
    "experiment.checkpoint_stale": DoctorCheck(
        id="experiment.checkpoint_stale",
        description="Detect active experiments without a current checkpoint.",
        default_enabled=True,
        severity="warning",
        runner=_check_experiment_checkpoint_stale,
    ),
    "runs.expected_missing": DoctorCheck(
        id="runs.expected_missing",
        description="Detect experiments with fewer recorded runs than progress.expected_runs.",
        default_enabled=True,
        severity="warning",
        runner=_check_expected_runs,
    ),
    "artifact.unlinked_to_run": DoctorCheck(
        id="artifact.unlinked_to_run",
        description="Detect checkpoint/eval-result artifacts that are not linked to a run.",
        default_enabled=True,
        severity="warning",
        runner=_check_unlinked_run_artifacts,
    ),
    "job_runs.stale_state": DoctorCheck(
        id="job_runs.stale_state",
        description="Detect job/run edges whose status is stale relative to the parent job.",
        default_enabled=True,
        severity="warning",
        runner=_check_job_run_stale_state,
    ),
    "job_runs.orphan": DoctorCheck(
        id="job_runs.orphan",
        description="Detect job/run edges pointing at missing or archived entities.",
        default_enabled=True,
        severity="error",
        runner=_check_job_run_orphans,
    ),
}
