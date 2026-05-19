import json
import os
import shutil
import sqlite3
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from fieldbook import __version__
from fieldbook.db import CURRENT_SCHEMA_VERSION, connect, schema_version
from fieldbook.errors import ValidationError
from fieldbook.time_utils import utc_now


METADATA_VERSION = 1
CORE_TABLES = {"schema_metadata", "experiments", "runs", "jobs", "artifacts", "metrics", "notes"}


def export_snapshot(
    *,
    ledger_path: Path,
    output_path: Path,
    replace: bool,
    metadata: bool = True,
) -> dict[str, Any]:
    _check_output(output_path, replace=replace)
    metadata_path = _metadata_path(output_path)
    if metadata:
        _check_output(metadata_path, replace=replace)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = _temp_path(output_path)
    temp_metadata = _temp_path(metadata_path) if metadata else None
    _unlink_if_exists(temp_output)
    if temp_metadata:
        _unlink_if_exists(temp_metadata)
    try:
        source = _connect_readonly(ledger_path)
        try:
            _validate_fieldbook_db(source, allow_older=True, allow_newer=True)
            dest = sqlite3.connect(temp_output)
            try:
                source.backup(dest)
            finally:
                dest.close()
            counts = table_counts(source)
            source_schema = schema_version(source)
        finally:
            source.close()

        payload = {
            "metadata_version": METADATA_VERSION,
            "exported_at": utc_now(),
            "source_ledger": str(ledger_path),
            "schema_version": source_schema,
            "fieldbook_version": _fieldbook_version(),
            "table_counts": counts,
        }
        if temp_metadata:
            temp_metadata.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_output, output_path)
        if temp_metadata:
            os.replace(temp_metadata, metadata_path)
        return {
            "output": str(output_path),
            "metadata_path": str(metadata_path) if metadata else None,
            "schema_version": source_schema,
            "table_counts": counts,
        }
    except Exception:
        _unlink_if_exists(temp_output)
        if temp_metadata:
            _unlink_if_exists(temp_metadata)
        raise


def inspect_snapshot(input_path: Path) -> dict[str, Any]:
    conn = _connect_readonly(input_path)
    try:
        _validate_fieldbook_db(conn, allow_older=True, allow_newer=True)
        source_schema = schema_version(conn)
        counts = table_counts(conn)
    finally:
        conn.close()
    metadata_path = _metadata_path(input_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
    return {
        "input": str(input_path),
        "metadata_path": str(metadata_path),
        "metadata": metadata,
        "schema_version": source_schema,
        "table_counts": counts,
    }


def import_snapshot(*, input_path: Path, output_path: Path, replace: bool) -> dict[str, Any]:
    source = _connect_readonly(input_path)
    try:
        _validate_fieldbook_db(source, allow_older=True, allow_newer=False)
    finally:
        source.close()
    _check_output(output_path, replace=replace)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = _temp_path(output_path)
    _unlink_if_exists(temp_output)
    try:
        shutil.copy2(input_path, temp_output)
        conn = connect(temp_output)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            output_schema = schema_version(conn)
            counts = table_counts(conn)
        finally:
            conn.close()
        os.replace(temp_output, output_path)
        return {
            "input": str(input_path),
            "output": str(output_path),
            "schema_version": output_schema,
            "table_counts": counts,
        }
    except Exception:
        _unlink_if_exists(temp_output)
        raise


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise ValidationError(f"snapshot input not found: {path}")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("SELECT 1").fetchone()
        return conn
    except sqlite3.DatabaseError as exc:
        raise ValidationError(f"not a readable SQLite database: {path}") from exc


def _validate_fieldbook_db(conn: sqlite3.Connection, *, allow_older: bool, allow_newer: bool) -> None:
    try:
        db_schema = schema_version(conn)
    except sqlite3.DatabaseError as exc:
        raise ValidationError("snapshot is not a readable SQLite database") from exc
    if db_schema <= 0:
        raise ValidationError("snapshot is not a Fieldbook ledger: missing schema version")
    if db_schema < CURRENT_SCHEMA_VERSION and not allow_older:
        raise ValidationError(
            f"snapshot schema version {db_schema} is older than supported version {CURRENT_SCHEMA_VERSION}"
        )
    if db_schema > CURRENT_SCHEMA_VERSION and not allow_newer:
        raise ValidationError(
            f"snapshot schema version {db_schema} is newer than supported version {CURRENT_SCHEMA_VERSION}"
        )
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    except sqlite3.DatabaseError as exc:
        raise ValidationError("snapshot is not a readable SQLite database") from exc
    missing = sorted(CORE_TABLES - tables)
    if missing:
        raise ValidationError(f"snapshot is not a Fieldbook ledger; missing tables: {', '.join(missing)}")


def _check_output(path: Path, *, replace: bool) -> None:
    if path.exists() and not replace:
        raise ValidationError(f"output already exists: {path}")


def _metadata_path(path: Path) -> Path:
    return Path(f"{path}.metadata.json")


def _temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp")


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _fieldbook_version() -> str:
    try:
        return version("fieldbook")
    except PackageNotFoundError:
        return __version__
