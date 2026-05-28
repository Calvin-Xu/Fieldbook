import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fieldbook.validation import load_attrs


LOCAL_MTIME_ATTR = "fieldbook.local_mtime_at_capture"
LOCAL_SIZE_ATTR = "fieldbook.local_size_at_capture"
LOCAL_PATH_ATTR = "fieldbook.local_path_at_capture"
DRIFT_LIMIT = 20


def local_artifact_path(uri: str, *, cwd: Path) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme in {"gs", "s3", "http", "https", "wandb"}:
        return None
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).expanduser()
        return path if path.is_absolute() else cwd / path
    if parsed.scheme:
        return None
    path = Path(uri).expanduser()
    return path if path.is_absolute() else cwd / path


def local_artifact_metadata(uri: str, *, cwd: Path) -> dict[str, Any] | None:
    path = local_artifact_path(uri, cwd=cwd)
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return {
        LOCAL_MTIME_ATTR: float(stat.st_mtime),
        LOCAL_SIZE_ATTR: int(stat.st_size),
        LOCAL_PATH_ATTR: str(path.resolve()),
    }


def attrs_with_local_capture(attrs: dict[str, Any], *, uri: str, cwd: Path) -> dict[str, Any]:
    metadata = local_artifact_metadata(uri, cwd=cwd)
    if metadata is None:
        return attrs
    return {**attrs, **metadata}


def drifted_artifacts(
    conn: sqlite3.Connection,
    *,
    experiment_id: str | None = None,
    cwd: Path,
    limit: int = DRIFT_LIMIT,
) -> list[dict[str, Any]]:
    rows = _artifact_rows(conn, experiment_id=experiment_id)
    drifted: list[dict[str, Any]] = []
    for row in rows:
        attrs = load_attrs(row["attrs_json"])
        if LOCAL_MTIME_ATTR not in attrs and LOCAL_SIZE_ATTR not in attrs:
            continue
        captured_path = attrs.get(LOCAL_PATH_ATTR)
        path = Path(captured_path) if isinstance(captured_path, str) and captured_path else local_artifact_path(row["uri"], cwd=cwd)
        if path is None or not path.exists():
            drifted.append(_drift_row(row, attrs, drift_kind="missing_file", observed={}))
            continue
        stat = path.stat()
        observed = {
            LOCAL_MTIME_ATTR: float(stat.st_mtime),
            LOCAL_SIZE_ATTR: int(stat.st_size),
            LOCAL_PATH_ATTR: str(path.resolve()),
        }
        mtime_changed = attrs.get(LOCAL_MTIME_ATTR) != observed[LOCAL_MTIME_ATTR]
        size_changed = attrs.get(LOCAL_SIZE_ATTR) != observed[LOCAL_SIZE_ATTR]
        if not (mtime_changed or size_changed):
            continue
        if mtime_changed and size_changed:
            drift_kind = "mtime_size"
        elif mtime_changed:
            drift_kind = "mtime"
        else:
            drift_kind = "size"
        drifted.append(_drift_row(row, attrs, drift_kind=drift_kind, observed=observed))
    return drifted[:limit]


def stale_validations(
    conn: sqlite3.Connection,
    *,
    experiment_id: str | None = None,
    cwd: Path,
    limit: int = DRIFT_LIMIT,
) -> list[dict[str, Any]]:
    drifted_by_id = {row["id"]: row for row in drifted_artifacts(conn, experiment_id=experiment_id, cwd=cwd, limit=1_000_000)}
    params: list[Any] = []
    query = (
        "SELECT v.*, a.updated_at AS source_updated_at FROM validations v "
        "JOIN artifacts a ON a.id = v.source_artifact_id "
        "WHERE v.deleted_at IS NULL AND a.deleted_at IS NULL"
    )
    if experiment_id:
        query += " AND v.entity_type = 'experiment' AND v.entity_id = ?"
        params.append(experiment_id)
    query += " ORDER BY v.updated_at DESC, v.id"
    stale: list[dict[str, Any]] = []
    for row in conn.execute(query, params).fetchall():
        source_drifted = row["source_artifact_id"] in drifted_by_id
        source_updated = row["source_updated_at"] > row["updated_at"]
        if not (source_drifted or source_updated):
            continue
        stale.append(
            {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "check_name": row["check_name"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "source_artifact_id": row["source_artifact_id"],
                "source_updated_at": row["source_updated_at"],
                "source_drifted": source_drifted,
            }
        )
    return stale[:limit]


def experiment_freshness(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    cwd: Path,
    stale_checkpoint_hours: float = 24.0,
    example_limit: int = DRIFT_LIMIT,
) -> dict[str, Any]:
    drifted = drifted_artifacts(conn, experiment_id=experiment_id, cwd=cwd, limit=example_limit)
    stale = stale_validations(conn, experiment_id=experiment_id, cwd=cwd, limit=example_limit)
    checkpoint = conn.execute(
        "SELECT * FROM notes WHERE entity_type = 'experiment' AND entity_id = ? AND note_type = 'checkpoint' "
        "AND deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    activity_count = _experiment_activity_count(conn, experiment_id)
    last_checkpoint_at = checkpoint["created_at"] if checkpoint else None
    since_hours = _hours_since(last_checkpoint_at) if last_checkpoint_at else None
    if checkpoint is None and activity_count == 0:
        checkpoint_status = "idle"
    elif checkpoint is None:
        checkpoint_status = "missing"
    elif since_hours is not None and since_hours > stale_checkpoint_hours:
        checkpoint_status = "stale"
    else:
        checkpoint_status = "current"
    return {
        "drifted_artifact_count": len(drifted_artifacts(conn, experiment_id=experiment_id, cwd=cwd, limit=1_000_000)),
        "stale_validation_count": len(stale_validations(conn, experiment_id=experiment_id, cwd=cwd, limit=1_000_000)),
        "last_checkpoint_at": last_checkpoint_at,
        "last_handoff_at": last_checkpoint_at,
        "since_last_checkpoint_hours": since_hours,
        "since_last_handoff_hours": since_hours,
        "checkpoint_status": checkpoint_status,
        "handoff_status": checkpoint_status,
        "drifted_artifacts": drifted,
        "stale_validations": stale,
    }


def _artifact_rows(conn: sqlite3.Connection, *, experiment_id: str | None) -> list[sqlite3.Row]:
    if experiment_id is None:
        return conn.execute("SELECT * FROM artifacts WHERE deleted_at IS NULL ORDER BY updated_at DESC, id").fetchall()
    return conn.execute(
        "SELECT DISTINCT a.* FROM artifacts a "
        "LEFT JOIN experiment_runs er ON er.run_id = a.run_id AND er.experiment_id = ? "
        "LEFT JOIN jobs j ON j.id = a.job_id "
        "LEFT JOIN experiment_runs jer ON jer.run_id = j.run_id AND jer.experiment_id = ? "
        "WHERE a.deleted_at IS NULL AND (a.experiment_id = ? OR er.experiment_id IS NOT NULL "
        "OR j.experiment_id = ? OR jer.experiment_id IS NOT NULL) "
        "ORDER BY a.updated_at DESC, a.id",
        (experiment_id, experiment_id, experiment_id, experiment_id),
    ).fetchall()


def _drift_row(row: sqlite3.Row, attrs: dict[str, Any], *, drift_kind: str, observed: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "uri": row["uri"],
        "type": row["type"],
        "drift_kind": drift_kind,
        "captured": {
            LOCAL_MTIME_ATTR: attrs.get(LOCAL_MTIME_ATTR),
            LOCAL_SIZE_ATTR: attrs.get(LOCAL_SIZE_ATTR),
            LOCAL_PATH_ATTR: attrs.get(LOCAL_PATH_ATTR),
        },
        "observed": observed,
        "suggested_action": "Run `fieldbook artifact refresh-local` or regenerate the artifact.",
    }


def _experiment_activity_count(conn: sqlite3.Connection, experiment_id: str) -> int:
    artifact_count = len(_artifact_rows(conn, experiment_id=experiment_id))
    validation_count = conn.execute(
        "SELECT COUNT(*) FROM validations WHERE entity_type = 'experiment' AND entity_id = ? AND deleted_at IS NULL",
        (experiment_id,),
    ).fetchone()[0]
    job_count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE experiment_id = ? AND deleted_at IS NULL",
        (experiment_id,),
    ).fetchone()[0]
    run_count = conn.execute(
        "SELECT COUNT(*) FROM experiment_runs er JOIN runs r ON r.id = er.run_id "
        "WHERE er.experiment_id = ? AND r.deleted_at IS NULL",
        (experiment_id,),
    ).fetchone()[0]
    non_checkpoint_note_count = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
        "AND note_type != 'checkpoint' AND deleted_at IS NULL",
        (experiment_id,),
    ).fetchone()[0]
    return int(artifact_count + validation_count + job_count + run_count + non_checkpoint_note_count)


def _hours_since(timestamp: str) -> float:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
