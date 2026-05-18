import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from fieldbook.errors import ValidationError
from fieldbook.ids import new_id
from fieldbook.repository import Repository
from fieldbook.time_utils import utc_now
from fieldbook.validation import (
    ARTIFACT_TYPES,
    ENTITY_TYPES,
    JOB_STATUSES,
    NOTE_STATUSES,
    NOTE_TYPES,
    RUN_STATUSES,
    attrs_json,
    load_attrs,
    require_choice,
    validate_content_hash,
    validate_metric_value,
    validate_utc_z,
)


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
    plan = _plan(repo.conn, manifest, experiment_id)
    if not apply:
        return {"source": source, "apply": False, "counts": plan["counts"], "operations": plan["operations"]}
    with repo.conn:
        _apply_plan(repo.conn, plan)
        repo.conn.execute(
            "INSERT INTO reconcile_events (id, experiment_id, source, inserts_json, updates_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id("rec"),
                experiment_id,
                source,
                json.dumps(plan["inserts"], sort_keys=True),
                json.dumps(plan["updates"], sort_keys=True),
                utc_now(),
            ),
        )
    return {"source": source, "apply": True, "counts": plan["counts"], "operations": plan["operations"]}


def _manifest_keys() -> list[str]:
    return ["runs", "jobs", "artifacts", "metrics", "notes", "custom_attributes"]


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
    inserts: Counter[str] = Counter()
    updates: Counter[str] = Counter()
    for run in manifest.get("runs", []):
        operation = _plan_run(conn, run, experiment_id)
        operations.append(operation)
        _increment(inserts, updates, operation)
    for job in manifest.get("jobs", []):
        operation = _plan_job(conn, job, experiment_id)
        operations.append(operation)
        _increment(inserts, updates, operation)
    for artifact in manifest.get("artifacts", []):
        operation = _plan_artifact(conn, artifact, experiment_id)
        operations.append(operation)
        _increment(inserts, updates, operation)
    for metric in manifest.get("metrics", []):
        operation = _plan_metric(conn, metric)
        operations.append(operation)
        _increment(inserts, updates, operation)
    for note in manifest.get("notes", []):
        operation = _plan_note(conn, note)
        operations.append(operation)
        _increment(inserts, updates, operation)
    for custom_attr in manifest.get("custom_attributes", []):
        operation = _plan_custom_attrs(conn, custom_attr)
        operations.append(operation)
        _increment(inserts, updates, operation)
    return {
        "operations": operations,
        "inserts": dict(inserts),
        "updates": dict(updates),
        "counts": {"insert": dict(inserts), "update": dict(updates), "total": len(operations)},
    }


def _increment(inserts: Counter[str], updates: Counter[str], operation: dict[str, Any]) -> None:
    if operation["action"] == "insert":
        inserts[operation["entity"]] += 1
    else:
        updates[operation["entity"]] += 1


def _plan_run(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None) -> dict[str, Any]:
    require_choice(row.get("status", "active"), RUN_STATUSES, "run status")
    existing = _find_entity(conn, "runs", row)
    run_id = existing["id"] if existing else row.get("id", new_id("run"))
    return {"entity": "runs", "action": "update" if existing else "insert", "id": run_id, "row": {**row, "id": run_id, "experiment_id": row.get("experiment_id", experiment_id)}}


def _plan_job(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None) -> dict[str, Any]:
    require_choice(row.get("status", "planned"), JOB_STATUSES, "job status")
    validate_utc_z(row.get("started_at"), "started_at")
    validate_utc_z(row.get("finished_at"), "finished_at")
    existing = _find_entity(conn, "jobs", row)
    job_id = existing["id"] if existing else row.get("id", new_id("job"))
    return {"entity": "jobs", "action": "update" if existing else "insert", "id": job_id, "row": {**row, "id": job_id, "experiment_id": row.get("experiment_id", experiment_id)}}


def _plan_artifact(conn: sqlite3.Connection, row: dict[str, Any], experiment_id: str | None) -> dict[str, Any]:
    require_choice(row["type"], ARTIFACT_TYPES, "artifact type")
    validate_content_hash(row.get("content_hash"))
    existing = _find_entity(conn, "artifacts", row)
    artifact_id = existing["id"] if existing else row.get("id", new_id("art"))
    return {"entity": "artifacts", "action": "update" if existing else "insert", "id": artifact_id, "row": {**row, "id": artifact_id, "experiment_id": row.get("experiment_id", experiment_id)}}


def _plan_metric(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    metric_name = row.get("metric_name") or row.get("name")
    if not row.get("run_id") or not metric_name or row.get("value") is None:
        raise ValidationError("metric reconcile rows require run_id, metric_name/name, and value")
    existing = conn.execute(
        "SELECT id FROM metrics WHERE run_id = ? AND metric_name = ? AND COALESCE(step, '') = COALESCE(?, '') "
        "AND COALESCE(split, '') = COALESCE(?, '') AND COALESCE(source_job_id, '') = COALESCE(?, '') "
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
    metric_id = existing["id"] if existing else row.get("id", new_id("met"))
    return {
        "entity": "metrics",
        "action": "update" if existing else "insert",
        "id": metric_id,
        "row": {**row, "id": metric_id, "metric_name": metric_name, "value": validate_metric_value(str(row["value"]))},
    }


def _plan_note(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    require_choice(row["entity_type"], ENTITY_TYPES, "entity type")
    require_choice(row["note_type"], NOTE_TYPES, "note type")
    require_choice(row.get("status", "open"), NOTE_STATUSES, "note status")
    existing = _find_entity(conn, "notes", row)
    note_id = existing["id"] if existing else row.get("id", new_id("note"))
    return {"entity": "notes", "action": "update" if existing else "insert", "id": note_id, "row": {**row, "id": note_id}}


def _plan_custom_attrs(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    entity_type = row["entity_type"]
    require_choice(entity_type, ENTITY_TYPES, "entity type")
    entity_id = row["entity_id"]
    table = _table_for_entity_type(entity_type)
    existing = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if not existing:
        raise ValidationError(f"custom attribute target not found: {entity_type}:{entity_id}")
    attrs = row.get("attrs")
    if not isinstance(attrs, dict):
        raise ValidationError("custom attribute rows require attrs object")
    return {"entity": "custom_attributes", "action": "update", "id": entity_id, "row": row}


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
    return None


def _apply_plan(conn: sqlite3.Connection, plan: dict[str, Any]) -> None:
    for operation in plan["operations"]:
        entity = operation["entity"]
        if entity == "runs":
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


def _apply_run(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO runs (id, name, description, status, external_system, external_id, created_at, updated_at, attrs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["name"],
                row.get("description"),
                row.get("status", "active"),
                row.get("external_system"),
                row.get("external_id"),
                now,
                now,
                attrs_json(row.get("attrs", {})),
            ),
        )
    else:
        conn.execute(
            "UPDATE runs SET name = COALESCE(?, name), description = COALESCE(?, description), "
            "status = COALESCE(?, status), updated_at = ?, attrs_json = ? WHERE id = ?",
            (
                row.get("name"),
                row.get("description"),
                row.get("status"),
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
    values = (
        row.get("experiment_id"),
        row.get("run_id"),
        row.get("name"),
        row.get("status", "planned"),
        row.get("command"),
        row.get("launcher"),
        row.get("external_system"),
        row.get("external_id"),
        row.get("failure_reason"),
        row.get("started_at"),
        row.get("finished_at"),
        attrs_json(row.get("attrs", {})),
    )
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
    else:
        conn.execute(
            "UPDATE jobs SET experiment_id = COALESCE(?, experiment_id), run_id = COALESCE(?, run_id), "
            "name = COALESCE(?, name), status = COALESCE(?, status), command = COALESCE(?, command), "
            "launcher = COALESCE(?, launcher), external_system = COALESCE(?, external_system), "
            "external_id = COALESCE(?, external_id), failure_reason = COALESCE(?, failure_reason), "
            "started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at), attrs_json = ?, "
            "updated_at = ? WHERE id = ?",
            (*values, now, row["id"]),
        )


def _apply_artifact(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO artifacts (id, experiment_id, run_id, job_id, type, uri, content_hash, created_at, updated_at, attrs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    else:
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
            "INSERT INTO metrics (id, run_id, metric_name, value, step, split, source_job_id, source_artifact_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    else:
        conn.execute("UPDATE metrics SET value = ?, updated_at = ? WHERE id = ?", (row["value"], now, row["id"]))


def _apply_note(conn: sqlite3.Connection, operation: dict[str, Any]) -> None:
    row = operation["row"]
    now = utc_now()
    if operation["action"] == "insert":
        conn.execute(
            "INSERT INTO notes (id, entity_type, entity_id, note_type, status, body, author, created_at, updated_at, attrs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["entity_type"],
                row["entity_id"],
                row["note_type"],
                row.get("status", "open"),
                row["body"],
                row.get("author"),
                now,
                now,
                attrs_json(row.get("attrs", {})),
            ),
        )
    else:
        conn.execute(
            "UPDATE notes SET status = COALESCE(?, status), body = COALESCE(?, body), author = COALESCE(?, author), "
            "attrs_json = ?, updated_at = ? WHERE id = ?",
            (row.get("status"), row.get("body"), row.get("author"), attrs_json(row.get("attrs", {})), now, row["id"]),
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


def _table_for_entity_type(entity_type: str) -> str:
    return {
        "experiment": "experiments",
        "run": "runs",
        "job": "jobs",
        "artifact": "artifacts",
        "metric": "metrics",
    }[entity_type]
