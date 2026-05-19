import csv
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from fieldbook.errors import NotFoundError, ValidationError
from fieldbook.ids import new_id
from fieldbook.repository import Repository
from fieldbook.time_utils import utc_now
from fieldbook.validation import (
    ARTIFACT_TYPES,
    ENTITY_TYPES,
    JOB_STATUSES,
    NOTE_BODY_FORMATS,
    NOTE_STATUSES,
    NOTE_TYPES,
    RUN_STATUSES,
    SYNC_EVENT_STATUSES,
    attrs_json,
    load_attrs,
    require_choice,
    validate_attrs_dict,
    validate_content_hash,
    validate_metric_value,
    validate_note_body,
    validate_note_title,
    validate_utc_z,
)


ARCHIVABLE_ENTITIES = {"runs", "jobs", "artifacts", "metrics", "notes"}
UPSERT_ONLY_ENTITIES = {"custom_attributes"}
ENTITY_ORDER = {
    "runs": 0,
    "jobs": 1,
    "artifacts": 2,
    "metrics": 3,
    "notes": 4,
    "custom_attributes": 5,
    "sync_events": 6,
}
ACTION_ORDER = {"insert": 0, "update": 1, "sync_event": 2, "noop": 3, "archive": 4}
NOTE_AUDIT_PREVIEW_CHARS = 200

ENTITY_KEYS = {
    "run": "runs",
    "runs": "runs",
    "job": "jobs",
    "jobs": "jobs",
    "artifact": "artifacts",
    "artifacts": "artifacts",
    "metric": "metrics",
    "metrics": "metrics",
    "note": "notes",
    "notes": "notes",
    "custom_attribute": "custom_attributes",
    "custom_attributes": "custom_attributes",
    "sync_event": "sync_events",
    "sync_events": "sync_events",
}


def load_manifest(path: Path) -> dict[str, list[dict[str, Any]]]:
    if path.suffix.lower() == ".json":
        with path.open() as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValidationError("JSON reconcile manifest must be an object")
        return {key: _as_list(data.get(key, []), key) for key in _manifest_keys()}
    return _load_csv_manifest(path)


def reconcile_manifest(
    repo: Repository,
    *,
    manifest: dict[str, list[dict[str, Any]]],
    source: str,
    experiment_ref: str | None,
    apply: bool,
) -> dict[str, Any]:
    experiment_id = repo.get_experiment(experiment_ref)["id"] if experiment_ref else None
    if experiment_id and repo.get_experiment(experiment_id)["deleted_at"] is not None:
        raise ValidationError(f"experiment is archived/deleted and cannot be reconciled: {experiment_id}")

    if not apply:
        repo.conn.execute("BEGIN")
        try:
            plan = _plan(repo.conn, manifest, experiment_id)
        finally:
            repo.conn.rollback()
        return {
            "source": source,
            "apply": False,
            "counts": plan["counts"],
            "operations": [_public_operation(operation) for operation in plan["operations"]],
        }

    repo.conn.execute("BEGIN IMMEDIATE")
    try:
        plan = _plan(repo.conn, manifest, experiment_id)
        event_id = new_id("rec")
        now = utc_now()
        repo.conn.execute(
            "INSERT INTO reconcile_events (id, experiment_id, source, inserts_json, updates_json, counts_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                experiment_id,
                source,
                json.dumps(plan["counts"]["insert"], sort_keys=True),
                json.dumps(plan["counts"]["update"], sort_keys=True),
                json.dumps(plan["counts"], sort_keys=True),
                now,
            ),
        )
        _apply_plan(repo.conn, plan, reconcile_event_id=event_id)
        _record_operations(repo.conn, event_id, plan["operations"])
    except Exception:
        repo.conn.rollback()
        raise
    else:
        repo.conn.commit()
    return {
        "source": source,
        "apply": True,
        "reconcile_event": _get_reconcile_event(repo.conn, event_id, include_operations=False),
        "counts": plan["counts"],
        "operations": [_public_operation(operation) for operation in plan["operations"]],
    }


def reconcile_log(
    conn: sqlite3.Connection,
    *,
    event_id: str | None = None,
    source: str | None = None,
    since: str | None = None,
    before: str | None = None,
    limit: int = 20,
    include_operations: bool = False,
) -> dict[str, Any]:
    if event_id:
        return _get_reconcile_event(conn, event_id, include_operations=True)
    params: list[Any] = []
    query = "SELECT * FROM reconcile_events WHERE 1=1"
    if source:
        query += " AND source = ?"
        params.append(source)
    if since:
        validate_utc_z(since, "since")
        query += " AND created_at >= ?"
        params.append(since)
    if before:
        validate_utc_z(before, "before")
        query += " AND created_at < ?"
        params.append(before)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return {
        "events": [
            _event_dict(conn, row, include_operations=include_operations)
            for row in rows
        ]
    }


def _manifest_keys() -> list[str]:
    return ["runs", "jobs", "artifacts", "metrics", "notes", "custom_attributes", "sync_events"]


def _as_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise ValidationError(f"{label} entries must be objects")
    return value


def _load_csv_manifest(path: Path) -> dict[str, list[dict[str, Any]]]:
    result = {key: [] for key in _manifest_keys()}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if "entity_type" not in (reader.fieldnames or []):
            raise ValidationError("CSV reconcile manifest requires entity_type column")
        for row in reader:
            entity_key = ENTITY_KEYS.get((row.pop("entity_type") or "").strip())
            if entity_key is None:
                raise ValidationError("unsupported CSV entity_type")
            cleaned = {key: value for key, value in row.items() if value not in {None, ""}}
            if "attrs_json" in cleaned:
                cleaned["attrs"] = json.loads(cleaned.pop("attrs_json"))
            result[entity_key].append(cleaned)
    return result


def _plan(conn: sqlite3.Connection, manifest: dict[str, list[dict[str, Any]]], experiment_id: str | None) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    normalized_manifest = {
        **manifest,
        "runs": _dedupe_external_rows(manifest.get("runs", [])),
        "jobs": _dedupe_external_rows(manifest.get("jobs", [])),
    }
    order = 0
    for run in normalized_manifest.get("runs", []):
        operations.append(_plan_run(conn, run, experiment_id, order=order))
        order += 1
    for job in normalized_manifest.get("jobs", []):
        operations.append(_plan_job(conn, job, experiment_id, order=order))
        order += 1
    for artifact in normalized_manifest.get("artifacts", []):
        operations.append(_plan_artifact(conn, artifact, experiment_id, order=order))
        order += 1
    for metric in normalized_manifest.get("metrics", []):
        operations.append(_plan_metric(conn, metric, order=order))
        order += 1
    for note in normalized_manifest.get("notes", []):
        operations.append(_plan_note(conn, note, order=order))
        order += 1
    for custom_attr in normalized_manifest.get("custom_attributes", []):
        operations.append(_plan_custom_attrs(conn, custom_attr, order=order))
        order += 1
    for sync_event in normalized_manifest.get("sync_events", []):
        operations.append(_plan_sync_event(conn, sync_event, order=order))
        order += 1
    ordered = sorted(
        operations,
        key=lambda operation: (
            ACTION_ORDER[operation["action"]],
            ENTITY_ORDER[operation["entity"]],
            operation["order"],
        ),
    )
    counts = _counts(ordered)
    return {"operations": ordered, "counts": counts}


def _dedupe_external_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for row in rows:
        key = None
        if not row.get("id") and row.get("external_system") and row.get("external_id"):
            key = (row["external_system"], row["external_id"])
        if key is None or key not in index_by_key:
            if key is not None:
                index_by_key[key] = len(result)
            result.append(dict(row))
            continue
        result[index_by_key[key]].update(row)
    return result


def _counts(operations: list[dict[str, Any]]) -> dict[str, Any]:
    counters = {
        "insert": Counter(),
        "update": Counter(),
        "archive": Counter(),
        "noop": Counter(),
    }
    sync_event_count = 0
    for operation in operations:
        action = operation["action"]
        if action == "sync_event":
            sync_event_count += 1
        elif action in counters:
            counters[action][operation["entity"]] += 1
    return {
        "insert": dict(counters["insert"]),
        "update": dict(counters["update"]),
        "archive": dict(counters["archive"]),
        "sync_event": sync_event_count,
        "noop": dict(counters["noop"]),
        "total": len(operations),
    }


def _operation(
    *,
    entity: str,
    action: str,
    entity_id: str | None,
    row: dict[str, Any],
    order: int,
    existing: sqlite3.Row | None = None,
    diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "entity": entity,
        "action": action,
        "id": entity_id,
        "row": row,
        "existing": dict(existing) if existing is not None else None,
        "input": _audit_value(row),
        "diff": _audit_value(diff or {}),
        "order": order,
    }


def _public_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity": operation["entity"],
        "action": operation["action"],
        "entity_id": operation["id"],
        "input": operation["input"],
        "diff": operation["diff"],
    }


def _row_op(row: dict[str, Any], *, entity: str) -> str:
    op = row.get("_op", "upsert")
    if op == "delete":
        raise ValidationError("reconcile _op='delete' is not supported; use archive")
    if entity in UPSERT_ONLY_ENTITIES and op != "upsert":
        raise ValidationError(f"{entity} only supports _op='upsert'")
    if entity == "sync_events" and "_op" in row:
        raise ValidationError("sync_events do not support _op")
    allowed = {"upsert", "archive"} if entity in ARCHIVABLE_ENTITIES else {"upsert"}
    if op not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValidationError(f"invalid reconcile _op {op!r} for {entity}; expected one of: {allowed_text}")
    return op


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_op"}


def _plan_run(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None, *, order: int) -> dict[str, Any]:
    op = _row_op(row, entity="runs")
    clean = _clean_row(row)
    existing = _find_entity(conn, "runs", clean)
    if op == "archive":
        return _archive_operation("runs", clean, existing, order=order)
    require_choice(clean.get("status", "active"), RUN_STATUSES, "run status")
    run_id = existing["id"] if existing else clean.get("id", new_id("run"))
    parent_run_id = clean.get("parent_run_id")
    _validate_parent_run(conn, run_id, parent_run_id)
    target_experiment_id = clean.get("experiment_id", experiment_id)
    _require_active_experiment(conn, target_experiment_id)
    if not existing and not clean.get("name"):
        raise ValidationError("run reconcile rows require name for inserts")
    planned = {**clean, "id": run_id, "experiment_id": target_experiment_id}
    if existing:
        if "attrs" not in planned:
            planned["attrs"] = load_attrs(existing["attrs_json"])
        diff = _row_diff(
            existing,
            planned,
            fields=["name", "description", "status", "external_system", "external_id", "parent_run_id", "attrs"],
        )
        if target_experiment_id and not _run_link_exists(conn, target_experiment_id, run_id):
            diff["experiment_id"] = [None, target_experiment_id]
        action = "update" if diff else "noop"
        return _operation(entity="runs", action=action, entity_id=run_id, row=planned, order=order, existing=existing, diff=diff)
    return _operation(entity="runs", action="insert", entity_id=run_id, row=planned, order=order)


def _plan_job(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None, *, order: int) -> dict[str, Any]:
    op = _row_op(row, entity="jobs")
    clean = _clean_row(row)
    existing = _find_entity(conn, "jobs", clean)
    if op == "archive":
        return _archive_operation("jobs", clean, existing, order=order)
    require_choice(clean.get("status", "planned"), JOB_STATUSES, "job status")
    validate_utc_z(clean.get("started_at"), "started_at")
    validate_utc_z(clean.get("finished_at"), "finished_at")
    job_id = existing["id"] if existing else clean.get("id", new_id("job"))
    target_experiment_id = clean.get("experiment_id", experiment_id)
    _require_active_experiment(conn, target_experiment_id)
    planned = {**clean, "id": job_id, "experiment_id": target_experiment_id}
    if existing:
        if "attrs" not in planned:
            planned["attrs"] = load_attrs(existing["attrs_json"])
        diff = _row_diff(
            existing,
            planned,
            fields=[
                "experiment_id",
                "run_id",
                "name",
                "status",
                "command",
                "launcher",
                "external_system",
                "external_id",
                "failure_reason",
                "started_at",
                "finished_at",
                "attrs",
            ],
        )
        action = "update" if diff else "noop"
        return _operation(entity="jobs", action=action, entity_id=job_id, row=planned, order=order, existing=existing, diff=diff)
    return _operation(entity="jobs", action="insert", entity_id=job_id, row=planned, order=order)


def _plan_artifact(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None, *, order: int) -> dict[str, Any]:
    op = _row_op(row, entity="artifacts")
    clean = _clean_row(row)
    existing = _find_entity(conn, "artifacts", clean)
    if op == "archive":
        return _archive_operation("artifacts", clean, existing, order=order)
    require_choice(clean["type"], ARTIFACT_TYPES, "artifact type")
    validate_content_hash(clean.get("content_hash"))
    artifact_id = existing["id"] if existing else clean.get("id", new_id("art"))
    target_experiment_id = clean.get("experiment_id", experiment_id)
    _require_active_experiment(conn, target_experiment_id)
    planned = {**clean, "id": artifact_id, "experiment_id": target_experiment_id}
    if existing:
        if "attrs" not in planned:
            planned["attrs"] = load_attrs(existing["attrs_json"])
        diff = _row_diff(
            existing,
            planned,
            fields=["experiment_id", "run_id", "job_id", "type", "uri", "content_hash", "attrs"],
        )
        action = "update" if diff else "noop"
        return _operation(
            entity="artifacts",
            action=action,
            entity_id=artifact_id,
            row=planned,
            existing=existing,
            order=order,
            diff=diff,
        )
    return _operation(entity="artifacts", action="insert", entity_id=artifact_id, row=planned, order=order)


def _plan_metric(conn: sqlite3.Connection, row: dict[str, Any], *, order: int) -> dict[str, Any]:
    op = _row_op(row, entity="metrics")
    clean = _clean_row(row)
    existing = _find_entity(conn, "metrics", clean)
    if op == "archive":
        return _archive_operation("metrics", clean, existing, order=order)
    metric_name = clean.get("metric_name") or clean.get("name")
    if not clean.get("run_id") or not metric_name or clean.get("value") is None:
        raise ValidationError("metric reconcile rows require run_id, metric_name/name, and value")
    metric_id = existing["id"] if existing else clean.get("id", new_id("met"))
    planned = {
        **clean,
        "id": metric_id,
        "metric_name": metric_name,
        "value": validate_metric_value(str(clean["value"])),
    }
    if existing:
        diff = _row_diff(existing, planned, fields=["value"])
        action = "update" if diff else "noop"
        return _operation(entity="metrics", action=action, entity_id=metric_id, row=planned, order=order, existing=existing, diff=diff)
    return _operation(entity="metrics", action="insert", entity_id=metric_id, row=planned, order=order)


def _plan_note(conn: sqlite3.Connection, row: dict[str, Any], *, order: int) -> dict[str, Any]:
    op = _row_op(row, entity="notes")
    clean = _clean_row(row)
    existing = _find_entity(conn, "notes", clean)
    if op == "archive":
        return _archive_operation("notes", clean, existing, order=order)
    if not clean.get("entity_type") or not clean.get("note_type"):
        raise ValidationError("note reconcile rows require entity_type and note_type")
    require_choice(clean["entity_type"], ENTITY_TYPES, "entity type")
    require_choice(clean["note_type"], NOTE_TYPES, "note type")
    require_choice(clean.get("status", "open"), NOTE_STATUSES, "note status")
    title = validate_note_title(clean.get("title"))
    body = validate_note_body(clean["body"]) if "body" in clean else None
    if existing is None and body is None:
        raise ValidationError("note reconcile rows require body")
    note_id = existing["id"] if existing else clean.get("id", new_id("note"))
    planned = {**clean, "id": note_id, "title": title}
    if body is not None:
        planned["body"] = body
    if "body_format" in clean:
        planned["body_format"] = require_choice(clean["body_format"], NOTE_BODY_FORMATS, "note body format")
    elif existing is None:
        planned["body_format"] = "markdown"
    if existing:
        if "attrs" not in planned:
            planned["attrs"] = load_attrs(existing["attrs_json"])
        diff = _row_diff(
            existing,
            planned,
            fields=["status", "title", "body", "body_format", "author", "attrs"],
        )
        action = "update" if diff else "noop"
        return _operation(entity="notes", action=action, entity_id=note_id, row=planned, order=order, existing=existing, diff=diff)
    return _operation(entity="notes", action="insert", entity_id=note_id, row=planned, order=order)


def _plan_custom_attrs(conn: sqlite3.Connection, row: dict[str, Any], *, order: int) -> dict[str, Any]:
    _row_op(row, entity="custom_attributes")
    clean = _clean_row(row)
    entity_type = clean["entity_type"]
    require_choice(entity_type, ENTITY_TYPES, "entity type")
    entity_id = clean["entity_id"]
    table = _table_for_entity_type(entity_type)
    existing = conn.execute(f"SELECT id, attrs_json FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if not existing:
        raise ValidationError(f"custom attribute target not found: {entity_type}:{entity_id}")
    attrs = clean.get("attrs")
    if not isinstance(attrs, dict):
        raise ValidationError("custom attribute rows require attrs object")
    validate_attrs_dict(attrs)
    current = load_attrs(existing["attrs_json"])
    merged = {**current, **attrs}
    diff = {"attrs": [current, merged]} if merged != current else {}
    action = "update" if diff else "noop"
    return _operation(entity="custom_attributes", action=action, entity_id=entity_id, row=clean, order=order, existing=existing, diff=diff)


def _plan_sync_event(conn: sqlite3.Connection, row: dict[str, Any], *, order: int) -> dict[str, Any]:
    _row_op(row, entity="sync_events")
    clean = _clean_row(row)
    if not clean.get("target_system") or not clean.get("status"):
        raise ValidationError("sync_events require target_system and status")
    require_choice(clean["status"], SYNC_EVENT_STATUSES, "sync event status")
    attrs = clean.get("attrs", {})
    if not isinstance(attrs, dict):
        raise ValidationError("sync event attrs must be an object")
    validate_attrs_dict(attrs)
    idempotency_key = clean.get("idempotency_key")
    existing = None
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM sync_events WHERE target_system = ? AND COALESCE(target_identifier, '') = COALESCE(?, '') "
            "AND idempotency_key = ?",
            (clean["target_system"], clean.get("target_identifier"), idempotency_key),
        ).fetchone()
    if existing:
        planned = {**clean, "id": existing["id"]}
        return _operation(entity="sync_events", action="noop", entity_id=existing["id"], row=planned, order=order, existing=existing)
    event_id = clean.get("id", new_id("sync"))
    return _operation(entity="sync_events", action="sync_event", entity_id=event_id, row={**clean, "id": event_id}, order=order)


def _archive_operation(entity: str, row: dict[str, Any], existing: sqlite3.Row | None, *, order: int) -> dict[str, Any]:
    if existing is None:
        raise NotFoundError(f"{entity} row not found for archive")
    action = "noop" if existing["deleted_at"] is not None else "archive"
    return _operation(entity=entity, action=action, entity_id=existing["id"], row={**row, "id": existing["id"]}, order=order, existing=existing)


def _find_entity(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> sqlite3.Row | None:
    if row.get("id"):
        existing = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row["id"],)).fetchone()
        if existing:
            return existing
    if table in {"runs", "jobs"} and row.get("external_system") and row.get("external_id"):
        return conn.execute(
            f"SELECT * FROM {table} WHERE external_system = ? AND external_id = ? AND deleted_at IS NULL",
            (row["external_system"], row["external_id"]),
        ).fetchone()
    if table == "artifacts" and row.get("uri"):
        return conn.execute(
            "SELECT * FROM artifacts WHERE uri = ? AND deleted_at IS NULL",
            (row["uri"],),
        ).fetchone()
    if table == "metrics":
        metric_name = row.get("metric_name") or row.get("name")
        if row.get("run_id") and metric_name:
            return conn.execute(
                "SELECT * FROM metrics WHERE run_id = ? AND metric_name = ? "
                "AND COALESCE(step, '') = COALESCE(?, '') AND COALESCE(split, '') = COALESCE(?, '') "
                "AND COALESCE(source_job_id, '') = COALESCE(?, '') "
                "AND COALESCE(source_artifact_id, '') = COALESCE(?, '') AND deleted_at IS NULL",
                (
                    row["run_id"],
                    metric_name,
                    row.get("step"),
                    row.get("split"),
                    row.get("source_job_id"),
                    row.get("source_artifact_id"),
                ),
            ).fetchone()
    return None


def _validate_parent_run(conn: sqlite3.Connection, run_id: str, parent_run_id: str | None) -> None:
    if parent_run_id is None:
        return
    if parent_run_id == run_id:
        raise ValidationError("parent_run_id cannot reference the run itself")
    if not conn.execute("SELECT 1 FROM runs WHERE id = ?", (parent_run_id,)).fetchone():
        raise ValidationError(f"parent_run_id does not reference an existing run: {parent_run_id}")


def _require_active_experiment(conn: sqlite3.Connection, experiment_id: str | None) -> None:
    if experiment_id is None:
        return
    row = conn.execute("SELECT deleted_at FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
    if row is None:
        raise ValidationError(f"experiment not found: {experiment_id}")
    if row["deleted_at"] is not None:
        raise ValidationError(f"experiment is archived/deleted and cannot be reconciled: {experiment_id}")


def _run_link_exists(conn: sqlite3.Connection, experiment_id: str, run_id: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM experiment_runs WHERE experiment_id = ? AND run_id = ?",
            (experiment_id, run_id),
        ).fetchone()
    )


def _row_diff(existing: sqlite3.Row, row: dict[str, Any], *, fields: list[str]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    existing_dict = dict(existing)
    for field in fields:
        if field not in row:
            continue
        if field == "attrs":
            old_value = load_attrs(existing_dict.get("attrs_json", "{}"))
        else:
            old_value = existing_dict.get(field)
        new_value = row[field]
        if old_value != new_value:
            diff[field] = [old_value, new_value]
    return diff


def _apply_plan(conn: sqlite3.Connection, plan: dict[str, Any], *, reconcile_event_id: str) -> None:
    for operation in plan["operations"]:
        if operation["action"] == "noop":
            continue
        entity = operation["entity"]
        if operation["action"] == "archive":
            _apply_archive(conn, operation)
        elif entity == "runs":
            _apply_run(conn, operation)
        elif entity == "jobs":
            _apply_job(conn, operation)
        elif entity == "artifacts":
            _apply_artifact(conn, operation)
        elif entity == "metrics":
            _apply_metric(conn, operation)
        elif entity == "notes":
            _apply_note(conn, operation)
        elif entity == "custom_attributes":
            _apply_custom_attrs(conn, operation)
        elif entity == "sync_events":
            _apply_sync_event(conn, operation, reconcile_event_id=reconcile_event_id)


def _apply_run(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO runs (id, name, description, status, external_system, external_id, parent_run_id, "
            "created_at, updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["name"],
                row.get("description"),
                row.get("status", "active"),
                row.get("external_system"),
                row.get("external_id"),
                row.get("parent_run_id"),
                now,
                now,
                attrs_json(row.get("attrs", {})),
            ),
        )
    elif operation["action"] == "update":
        conn.execute(
            "UPDATE runs SET name = COALESCE(?, name), description = COALESCE(?, description), "
            "status = COALESCE(?, status), external_system = COALESCE(?, external_system), "
            "external_id = COALESCE(?, external_id), parent_run_id = COALESCE(?, parent_run_id), "
            "updated_at = ?, attrs_json = ? WHERE id = ?",
            (
                row.get("name"),
                row.get("description"),
                row.get("status"),
                row.get("external_system"),
                row.get("external_id"),
                row.get("parent_run_id"),
                now,
                attrs_json(row.get("attrs", {})),
                row["id"],
            ),
        )
    if row.get("experiment_id"):
        conn.execute(
            "INSERT OR IGNORE INTO experiment_runs (experiment_id, run_id, created_at) VALUES (?, ?, ?)",
            (row["experiment_id"], row["id"], now),
        )


def _apply_job(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO jobs (id, experiment_id, run_id, name, status, command, launcher, external_system, "
            "external_id, failure_reason, created_at, updated_at, started_at, finished_at, attrs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("experiment_id"),
                row.get("run_id"),
                row.get("name"),
                row.get("status", "planned"),
                row.get("command"),
                row.get("launcher"),
                row.get("external_system"),
                row.get("external_id"),
                row.get("failure_reason"),
                now,
                now,
                row.get("started_at"),
                row.get("finished_at"),
                attrs_json(row.get("attrs", {})),
            ),
        )
    elif operation["action"] == "update":
        conn.execute(
            "UPDATE jobs SET experiment_id = COALESCE(?, experiment_id), run_id = COALESCE(?, run_id), "
            "name = COALESCE(?, name), status = COALESCE(?, status), command = COALESCE(?, command), "
            "launcher = COALESCE(?, launcher), external_system = COALESCE(?, external_system), "
            "external_id = COALESCE(?, external_id), failure_reason = COALESCE(?, failure_reason), "
            "started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at), attrs_json = ?, "
            "updated_at = ? WHERE id = ?",
            (
                row.get("experiment_id"),
                row.get("run_id"),
                row.get("name"),
                row.get("status"),
                row.get("command"),
                row.get("launcher"),
                row.get("external_system"),
                row.get("external_id"),
                row.get("failure_reason"),
                row.get("started_at"),
                row.get("finished_at"),
                attrs_json(row.get("attrs", {})),
                now,
                row["id"],
            ),
        )


def _apply_artifact(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO artifacts (id, experiment_id, run_id, job_id, type, uri, content_hash, created_at, "
            "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("experiment_id"),
                row.get("run_id"),
                row.get("job_id"),
                row["type"],
                row["uri"],
                row.get("content_hash"),
                now,
                now,
                attrs_json(row.get("attrs", {})),
            ),
        )
    elif operation["action"] == "update":
        conn.execute(
            "UPDATE artifacts SET experiment_id = COALESCE(?, experiment_id), run_id = COALESCE(?, run_id), "
            "job_id = COALESCE(?, job_id), type = COALESCE(?, type), uri = COALESCE(?, uri), "
            "content_hash = COALESCE(?, content_hash), attrs_json = ?, updated_at = ? WHERE id = ?",
            (
                row.get("experiment_id"),
                row.get("run_id"),
                row.get("job_id"),
                row.get("type"),
                row.get("uri"),
                row.get("content_hash"),
                attrs_json(row.get("attrs", {})),
                now,
                row["id"],
            ),
        )


def _apply_metric(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO metrics (id, run_id, metric_name, value, step, split, source_job_id, source_artifact_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["run_id"],
                row["metric_name"],
                row["value"],
                row.get("step"),
                row.get("split"),
                row.get("source_job_id"),
                row.get("source_artifact_id"),
                now,
                now,
            ),
        )
    elif operation["action"] == "update":
        conn.execute("UPDATE metrics SET value = ?, updated_at = ? WHERE id = ?", (row["value"], now, row["id"]))


def _apply_note(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO notes (id, entity_type, entity_id, note_type, status, title, body, body_format, author, "
            "created_at, updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["entity_type"],
                row["entity_id"],
                row["note_type"],
                row.get("status", "open"),
                row.get("title"),
                row["body"],
                row.get("body_format", "markdown"),
                row.get("author"),
                now,
                now,
                attrs_json(row.get("attrs", {})),
            ),
        )
    elif operation["action"] == "update":
        conn.execute(
            "UPDATE notes SET status = COALESCE(?, status), title = COALESCE(?, title), "
            "body = COALESCE(?, body), body_format = COALESCE(?, body_format), author = COALESCE(?, author), "
            "attrs_json = ?, updated_at = ? WHERE id = ?",
            (
                row.get("status"),
                row.get("title"),
                row.get("body"),
                row.get("body_format"),
                row.get("author"),
                attrs_json(row.get("attrs", {})),
                now,
                row["id"],
            ),
        )


def _apply_custom_attrs(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    table = _table_for_entity_type(row["entity_type"])
    existing = conn.execute(f"SELECT attrs_json FROM {table} WHERE id = ?", (row["entity_id"],)).fetchone()
    current = load_attrs(existing["attrs_json"])
    current.update(row["attrs"])
    now = utc_now()
    conn.execute(
        f"UPDATE {table} SET attrs_json = ?, updated_at = ? WHERE id = ?",
        (attrs_json(current), now, row["entity_id"]),
    )


def _apply_sync_event(conn: sqlite3.Connection, operation: dict[str, Any], *, reconcile_event_id: str) -> None:
    row = operation["row"]
    conn.execute(
        "INSERT INTO sync_events (id, target_system, target_identifier, status, run_id, job_id, error_message, "
        "reconcile_event_id, idempotency_key, created_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row["target_system"],
            row.get("target_identifier"),
            row["status"],
            row.get("run_id"),
            row.get("job_id"),
            row.get("error_message"),
            reconcile_event_id,
            row.get("idempotency_key"),
            utc_now(),
            attrs_json(row.get("attrs", {})),
        ),
    )


def _apply_archive(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    now = utc_now()
    entity = operation["entity"]
    table = entity
    if entity == "runs":
        conn.execute(
            "UPDATE runs SET status = 'archived', deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
            (now, now, operation["id"]),
        )
        return
    conn.execute(
        f"UPDATE {table} SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
        (now, now, operation["id"]),
    )


def _record_operations(conn: sqlite3.Connection, reconcile_event_id: str, operations: list[dict[str, Any]]) -> None:
    for index, operation in enumerate(operations):
        conn.execute(
            "INSERT INTO reconcile_operations (id, reconcile_event_id, op_index, entity, action, entity_id, "
            "input_json, diff_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("recop"),
                reconcile_event_id,
                index,
                operation["entity"],
                operation["action"],
                operation["id"],
                json.dumps(operation["input"], sort_keys=True),
                json.dumps(operation["diff"], sort_keys=True),
            ),
        )


def _audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _audit_note_body(key, _audit_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_audit_value(item) for item in value]
    return value


def _audit_note_body(key: str, value: Any) -> Any:
    if key != "body" or not isinstance(value, str) or len(value) <= NOTE_AUDIT_PREVIEW_CHARS:
        return value
    return {
        "byte_count": len(value.encode("utf-8")),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "preview": value[:NOTE_AUDIT_PREVIEW_CHARS],
    }


def _get_reconcile_event(conn: sqlite3.Connection, event_id: str, *, include_operations: bool) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM reconcile_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"reconcile event not found: {event_id}")
    return _event_dict(conn, row, include_operations=include_operations)


def _event_dict(conn: sqlite3.Connection, row: sqlite3.Row, *, include_operations: bool) -> dict[str, Any]:
    data = dict(row)
    event = {
        "id": data["id"],
        "experiment_id": data["experiment_id"],
        "source": data["source"],
        "created_at": data["created_at"],
        "counts": _event_counts(data),
        "attrs": load_attrs(data.get("attrs_json", "{}")),
    }
    if include_operations:
        rows = conn.execute(
            "SELECT * FROM reconcile_operations WHERE reconcile_event_id = ? ORDER BY op_index",
            (data["id"],),
        ).fetchall()
        event["operations"] = [_operation_row_dict(op_row) for op_row in rows]
    return event


def _event_counts(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("counts_json"):
        return json.loads(data["counts_json"])
    return {
        "insert": json.loads(data.get("inserts_json") or "{}"),
        "update": json.loads(data.get("updates_json") or "{}"),
        "archive": {},
        "sync_event": 0,
        "noop": {},
        "total": 0,
    }


def _operation_row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "reconcile_event_id": row["reconcile_event_id"],
        "op_index": row["op_index"],
        "entity": row["entity"],
        "action": row["action"],
        "entity_id": row["entity_id"],
        "input": json.loads(row["input_json"]),
        "diff": json.loads(row["diff_json"]),
    }


def _table_for_entity_type(entity_type: str) -> str:
    return {
        "experiment": "experiments",
        "run": "runs",
        "job": "jobs",
        "artifact": "artifacts",
        "metric": "metrics",
    }[entity_type]
