import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fieldbook.db import CURRENT_SCHEMA_VERSION, schema_version
from fieldbook.time_utils import utc_now


STALE_JOB_STATUSES = ("queued", "running")
ATTR_TABLES = ("experiments", "runs", "jobs", "artifacts", "notes", "reconcile_events", "sync_events")
ENTITY_TABLES = {
    "experiment": "experiments",
    "run": "runs",
    "job": "jobs",
    "artifact": "artifacts",
    "metric": "metrics",
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
    cwd: Path


def list_doctor_checks() -> dict[str, Any]:
    return {"checks": [check.to_dict() for check in DOCTOR_CHECKS.values()]}


def run_doctor(
    ledger_path: Path,
    *,
    check_ids: list[str] | None,
    stale_hours: float,
    cwd: Path,
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
        options = DoctorOptions(stale_hours=stale_hours, cwd=cwd)
        issues: list[DoctorIssue] = []
        for check in selected_checks:
            issues.extend(check.runner(conn, options))
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
        "SELECT id, entity_type, entity_id FROM notes WHERE deleted_at IS NULL ORDER BY updated_at, id"
    ).fetchall()
    for row in rows:
        table = ENTITY_TABLES.get(row["entity_type"])
        if table is None:
            missing = True
            deleted = False
        else:
            target = conn.execute(f"SELECT deleted_at FROM {table} WHERE id = ?", (row["entity_id"],)).fetchone()
            missing = target is None
            deleted = bool(target and target["deleted_at"] is not None)
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
}
