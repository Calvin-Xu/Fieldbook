import fnmatch
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from fieldbook.errors import ValidationError
from fieldbook.ids import new_id
from fieldbook.time_utils import utc_now


DEFAULT_WANDB_KEY_PREFIX = "fieldbook"
ERROR_REDACTIONS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "<redacted bearer>"),
    (re.compile(r"api[_-]?key[=:]\s*[^,\s]+", re.IGNORECASE), "api_key=<redacted>"),
    (re.compile(r"password[=:]\s*[^,\s]+", re.IGNORECASE), "password=<redacted>"),
    (re.compile(r"secret[=:]\s*[^,\s]+", re.IGNORECASE), "secret=<redacted>"),
    (re.compile(r"ghp_[A-Za-z0-9_]+"), "ghp_<redacted>"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA<redacted>"),
]


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    error_message: str | None = None


class WandbSummaryWriter(Protocol):
    def write_summary(self, *, target_identifier: str, target_field: str, value: float) -> WriteResult:
        """Write one W&B summary value."""


class FakeWandbSummaryWriter:
    def __init__(self, *, fail_fields: set[str] | None = None):
        self.fail_fields = fail_fields or set()

    def write_summary(self, *, target_identifier: str, target_field: str, value: float) -> WriteResult:
        if target_field in self.fail_fields:
            return WriteResult(
                ok=False,
                error_message=f"fake W&B failure for {target_identifier}:{target_field} Bearer fake-token",
            )
        return WriteResult(ok=True)


class RealWandbSummaryWriter:
    def __init__(self) -> None:
        try:
            import wandb
        except ImportError as exc:
            raise ValidationError("install Fieldbook with the W&B extra to use --writer real") from exc
        self._wandb = wandb

    def write_summary(self, *, target_identifier: str, target_field: str, value: float) -> WriteResult:
        try:
            run = self._wandb.Api().run(target_identifier)
            run.summary[target_field] = value
            run.summary.update()
        except Exception as exc:
            return WriteResult(ok=False, error_message=str(exc))
        return WriteResult(ok=True)


def writer_from_name(name: str, *, fake_fail_fields: list[str] | None = None) -> WandbSummaryWriter:
    if name == "fake":
        return FakeWandbSummaryWriter(fail_fields=set(fake_fail_fields or []))
    if name == "real":
        return RealWandbSummaryWriter()
    raise ValidationError(f"unknown W&B writer: {name}")


def plan_wandb_writeback(
    conn: sqlite3.Connection,
    *,
    run_ref: str,
    metric_patterns: list[str],
    target_run: str | None,
    key_prefix: str | None,
    raw_keys: bool,
    force_target: bool,
    enforce_target_guard: bool,
    allow_rewrite: bool,
) -> dict[str, Any]:
    if not metric_patterns:
        raise ValidationError("writeback requires at least one --metric pattern")
    source_run = _resolve_run(conn, run_ref)
    if source_run["deleted_at"] is not None:
        raise ValidationError(f"source run is archived/deleted: {source_run['id']}")
    default_target = _default_wandb_target(conn, source_run)
    if target_run:
        if default_target and target_run != default_target and enforce_target_guard and not force_target:
            raise ValidationError("--target-run differs from the resolved W&B target; pass --force-target to override")
        target_identifier = target_run
    else:
        if not default_target:
            raise ValidationError("could not resolve target W&B run; pass --target-run")
        target_identifier = default_target

    selected = _select_metrics(conn, source_run["id"], metric_patterns)
    if not selected:
        raise ValidationError("no metrics matched the supplied --metric patterns")
    prefix = _target_prefix(key_prefix=key_prefix, raw_keys=raw_keys)
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    field_to_metric_ids: dict[str, list[str]] = {}
    for metric in selected:
        target_field = _target_field(metric["metric_name"], prefix=prefix, raw_keys=raw_keys)
        field_to_metric_ids.setdefault(target_field, []).append(metric["id"])
    collisions = {field: ids for field, ids in field_to_metric_ids.items() if len(ids) > 1}
    if collisions:
        details = "; ".join(f"{field}: {', '.join(ids)}" for field, ids in sorted(collisions.items()))
        raise ValidationError(f"target field collision: {details}")

    for metric in selected:
        target_field = _target_field(metric["metric_name"], prefix=prefix, raw_keys=raw_keys)
        idempotency_key = _idempotency_key(
            source_metric_id=metric["id"],
            target_identifier=target_identifier,
            target_field=target_field,
        )
        latest = _latest_sync_event(conn, target_identifier=target_identifier, idempotency_key=idempotency_key)
        row = _planned_row(metric, target_identifier=target_identifier, target_field=target_field, idempotency_key=idempotency_key)
        if latest is not None and latest["status"] == "synced" and not allow_rewrite:
            skipped.append({**row, "reason": "already_synced", "latest_sync_event_id": latest["id"]})
            continue
        planned.append(row)

    first_write_requires_ack = not _has_prior_writeback(conn, target_identifier=target_identifier)
    return {
        "envelope_version": 1,
        "dry_run": True,
        "target_system": "wandb",
        "source_run_id": source_run["id"],
        "target_identifier": target_identifier,
        "planned": planned,
        "skipped": skipped,
        "errors": [],
        "results": [],
        "summary": _summary(
            planned_count=len(planned),
            skipped_count=len(skipped),
            first_write_requires_ack=first_write_requires_ack,
        ),
    }


def apply_wandb_writeback(
    conn: sqlite3.Connection,
    *,
    plan: dict[str, Any],
    writer: WandbSummaryWriter,
    first_write_ok: bool,
) -> dict[str, Any]:
    if plan["summary"]["first_write_requires_ack"] and plan["planned"] and not first_write_ok:
        raise ValidationError("first Fieldbook writeback to this W&B target requires --first-write-ok")
    results: list[dict[str, Any]] = []
    synced_count = 0
    failed_count = 0
    for row in plan["planned"]:
        result = writer.write_summary(
            target_identifier=row["target_identifier"],
            target_field=row["target_field"],
            value=float(row["value"]),
        )
        status = "synced" if result.ok else "failed"
        if result.ok:
            synced_count += 1
        else:
            failed_count += 1
        error_message = sanitize_error(result.error_message) if result.error_message else None
        event_id = new_id("sync")
        now = utc_now()
        payload_summary = json.dumps({"value": float(row["value"])}, sort_keys=True)
        with conn:
            conn.execute(
                "INSERT INTO sync_events (id, target_system, target_identifier, status, run_id, "
                "error_message, idempotency_key, origin, source_entity_type, source_entity_id, "
                "target_field, payload_summary_json, created_at, attrs_json) "
                "VALUES (?, 'wandb', ?, ?, ?, ?, ?, 'writeback', 'metric', ?, ?, ?, ?, '{}')",
                (
                    event_id,
                    row["target_identifier"],
                    status,
                    row["source_run_id"],
                    error_message,
                    row["idempotency_key"],
                    row["source_metric_id"],
                    row["target_field"],
                    payload_summary,
                    now,
                ),
            )
        results.append({**row, "status": status, "sync_event_id": event_id, "error_message": error_message})
    return {
        **plan,
        "dry_run": False,
        "results": results,
        "summary": {
            **plan["summary"],
            "synced_count": synced_count,
            "failed_count": failed_count,
        },
    }


def wandb_writeback_log(
    conn: sqlite3.Connection,
    *,
    target_system: str | None,
    status: str | None,
    run_id: str | None,
    target_identifier: str | None,
    origin: str | None,
    source_entity_id: str | None,
    limit: int,
) -> dict[str, Any]:
    params: list[Any] = []
    query = "SELECT * FROM sync_events WHERE 1=1"
    if target_system:
        query += " AND target_system = ?"
        params.append(target_system)
    if status:
        query += " AND status = ?"
        params.append(status)
    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    if target_identifier:
        query += " AND target_identifier = ?"
        params.append(target_identifier)
    if origin:
        query += " AND origin = ?"
        params.append(origin)
    else:
        query += " AND origin = 'writeback'"
    if source_entity_id:
        query += " AND source_entity_id = ?"
        params.append(source_entity_id)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return {"events": [_sync_event_dict(row) for row in conn.execute(query, params).fetchall()]}


def sanitize_error(value: str) -> str:
    redacted = value
    for pattern, replacement in ERROR_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _resolve_run(conn: sqlite3.Connection, ref: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (ref,)).fetchone()
    if row:
        return row
    rows = conn.execute("SELECT * FROM runs WHERE name = ? AND deleted_at IS NULL ORDER BY id", (ref,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise ValidationError(f"run reference {ref!r} matches multiple rows")
    raise ValidationError(f"run row not found: {ref}")


def _default_wandb_target(conn: sqlite3.Connection, source_run: sqlite3.Row) -> str | None:
    if source_run["external_system"] == "wandb" and source_run["external_id"]:
        return source_run["external_id"]
    if source_run["parent_run_id"]:
        parent = conn.execute("SELECT * FROM runs WHERE id = ?", (source_run["parent_run_id"],)).fetchone()
        if parent and parent["external_system"] == "wandb" and parent["external_id"]:
            return parent["external_id"]
    return None


def _select_metrics(conn: sqlite3.Connection, run_id: str, patterns: list[str]) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE run_id = ? AND deleted_at IS NULL ORDER BY metric_name, step, split, id",
        (run_id,),
    ).fetchall()
    return [row for row in rows if any(fnmatch.fnmatchcase(row["metric_name"], pattern) for pattern in patterns)]


def _target_prefix(*, key_prefix: str | None, raw_keys: bool) -> str:
    if raw_keys:
        if key_prefix is not None:
            raise ValidationError("--raw-keys cannot be combined with --key-prefix")
        return ""
    prefix = DEFAULT_WANDB_KEY_PREFIX if key_prefix is None else key_prefix.strip()
    if not prefix:
        raise ValidationError("--key-prefix must not be empty; use --raw-keys for raw metric names")
    return prefix.rstrip("/")


def _target_field(metric_name: str, *, prefix: str, raw_keys: bool) -> str:
    if raw_keys:
        return metric_name
    return f"{prefix}/{metric_name}"


def _idempotency_key(*, source_metric_id: str, target_identifier: str, target_field: str) -> str:
    return f"wandb-summary:{source_metric_id}:{target_identifier}:{target_field}"


def _latest_sync_event(
    conn: sqlite3.Connection,
    *,
    target_identifier: str,
    idempotency_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sync_events WHERE target_system = 'wandb' AND target_identifier = ? "
        "AND idempotency_key = ? AND origin = 'writeback' ORDER BY created_at DESC, id DESC LIMIT 1",
        (target_identifier, idempotency_key),
    ).fetchone()


def _has_prior_writeback(conn: sqlite3.Connection, *, target_identifier: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sync_events WHERE target_system = 'wandb' AND target_identifier = ? "
            "AND origin = 'writeback' LIMIT 1",
            (target_identifier,),
        ).fetchone()
        is not None
    )


def _planned_row(
    metric: sqlite3.Row,
    *,
    target_identifier: str,
    target_field: str,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "source_run_id": metric["run_id"],
        "source_metric_id": metric["id"],
        "metric_name": metric["metric_name"],
        "step": metric["step"],
        "split": metric["split"],
        "value": metric["value"],
        "target_identifier": target_identifier,
        "target_field": target_field,
        "idempotency_key": idempotency_key,
    }


def _summary(
    *,
    planned_count: int,
    skipped_count: int,
    first_write_requires_ack: bool,
) -> dict[str, Any]:
    return {
        "planned_count": planned_count,
        "skipped_count": skipped_count,
        "error_count": 0,
        "synced_count": 0,
        "failed_count": 0,
        "first_write_requires_ack": first_write_requires_ack,
    }


def _sync_event_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["attrs"] = json.loads(data.pop("attrs_json", "{}"))
    if data.get("payload_summary_json"):
        data["payload_summary"] = json.loads(data["payload_summary_json"])
    else:
        data["payload_summary"] = None
    return data
