import base64
import csv
import io
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from fieldbook.errors import ValidationError


DEFAULT_SQL_LIMIT = 1_000
DEFAULT_SQL_TIMEOUT = 15.0
DEFAULT_MAX_OUTPUT_BYTES = 10 * 1024 * 1024
SAFE_INTEGER_ABS = 2**53

DENIED_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
}


def resolve_sql_text(*, query: str | None, file: str | None, stdin: bool, stdin_text: str | None = None) -> str:
    sources = [query is not None, file is not None, stdin]
    if sum(sources) != 1:
        raise ValidationError("fieldbook sql requires exactly one of --query, --file, or --stdin")
    if query is not None:
        sql = query
    elif file is not None:
        sql = Path(file).read_text()
    else:
        sql = stdin_text or ""
    if not sql.strip():
        raise ValidationError("SQL query is empty")
    return sql


def execute_readonly_sql(
    *,
    ledger_path: Path,
    sql: str,
    limit: int,
    no_limit: bool,
    timeout: float,
    max_output_bytes: int,
    allow_blobs: bool,
    output_format: str,
) -> tuple[str, str]:
    if limit < 0:
        raise ValidationError("--limit must be non-negative")
    if timeout <= 0:
        raise ValidationError("--timeout must be positive")
    if max_output_bytes <= 0:
        raise ValidationError("--max-output-bytes must be positive")

    conn = _connect_readonly(ledger_path, timeout=timeout)
    try:
        rows, columns, truncated = _execute(conn, sql=sql, limit=limit, no_limit=no_limit, timeout=timeout)
    finally:
        conn.close()

    envelope = _envelope(columns=columns, rows=rows, truncated=truncated, allow_blobs=allow_blobs)
    stdout, stderr = _render(envelope, output_format=output_format)
    output_bytes = len(stdout.encode()) + len(stderr.encode())
    if output_bytes > max_output_bytes:
        raise ValidationError(f"SQL output exceeds --max-output-bytes ({output_bytes} > {max_output_bytes})")
    return stdout, stderr


def _connect_readonly(path: Path, *, timeout: float) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.set_authorizer(_authorizer)
    return conn


def _authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None, _source: str | None) -> int:
    if action in DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (arg1 or arg2 or "").lower()
        if function_name == "load_extension":
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _execute(
    conn: sqlite3.Connection,
    *,
    sql: str,
    limit: int,
    no_limit: bool,
    timeout: float,
) -> tuple[list[tuple[Any, ...]], list[str], bool]:
    deadline = time.monotonic() + timeout

    def progress_handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(progress_handler, 1_000)
    try:
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise ValidationError("SQL query must produce result columns")
        columns = [description[0] for description in cursor.description or []]
        if len(set(columns)) != len(columns):
            raise ValidationError("SQL query result column names must be unique")
        if no_limit:
            rows = cursor.fetchall()
            truncated = False
        else:
            fetched = cursor.fetchmany(limit + 1)
            truncated = len(fetched) > limit
            rows = fetched[:limit]
    except sqlite3.ProgrammingError as exc:
        raise ValidationError(str(exc)) from exc
    except sqlite3.OperationalError as exc:
        message = str(exc)
        if "interrupted" in message.lower():
            raise ValidationError(f"SQL query timeout/interrupted after {timeout} seconds") from exc
        raise ValidationError(f"SQL query rejected: {message}") from exc
    except sqlite3.DatabaseError as exc:
        raise ValidationError(f"SQL query rejected: {exc}") from exc
    finally:
        conn.set_progress_handler(None, 0)
    return rows, columns, truncated


def _envelope(
    *,
    columns: list[str],
    rows: list[tuple[Any, ...]],
    truncated: bool,
    allow_blobs: bool,
) -> dict[str, Any]:
    normalized_rows = [_normalize_row(row, allow_blobs=allow_blobs) for row in rows]
    first_row = normalized_rows[0] if normalized_rows else None
    first_raw_row = rows[0] if rows else None
    column_metadata = [
        {
            "name": name,
            "decltype": None,
            "first_row_type": _value_type(first_row[index], raw_value=first_raw_row[index])
            if first_row is not None and first_raw_row is not None
            else None,
        }
        for index, name in enumerate(columns)
    ]
    row_dicts = [
        {columns[index]: value for index, value in enumerate(row)}
        for row in normalized_rows
    ]
    return {
        "envelope_version": 1,
        "columns": column_metadata,
        "rows": row_dicts,
        "row_count": len(row_dicts),
        "truncated": truncated,
    }


def _normalize_row(row: tuple[Any, ...], *, allow_blobs: bool) -> list[Any]:
    return [_normalize_value(value, allow_blobs=allow_blobs) for value in row]


def _normalize_value(value: Any, *, allow_blobs: bool) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER_ABS:
            return str(value)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("SQL query produced non-finite REAL value")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        if not allow_blobs:
            raise ValidationError("SQL query produced BLOB data; rerun with --allow-blobs to encode as base64")
        return base64.b64encode(value).decode("ascii")
    return str(value)


def _value_type(value: Any, *, raw_value: Any | None = None) -> str:
    if isinstance(raw_value, bytes):
        return "blob_base64"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "integer"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "real"
    if isinstance(value, str):
        return "text"
    return "blob_base64"


def _render(envelope: dict[str, Any], *, output_format: str) -> tuple[str, str]:
    if output_format == "json":
        return json.dumps(envelope, sort_keys=True, allow_nan=False) + "\n", ""
    if output_format == "ndjson":
        return _render_ndjson(envelope), ""
    if output_format == "csv":
        return _render_csv(envelope)
    raise ValidationError(f"unsupported SQL output format: {output_format}")


def _render_ndjson(envelope: dict[str, Any]) -> str:
    lines = [
        json.dumps(
            {
                "type": "meta",
                "envelope_version": envelope["envelope_version"],
                "columns": envelope["columns"],
                "truncated": envelope["truncated"],
            },
            sort_keys=True,
            allow_nan=False,
        )
    ]
    column_names = [column["name"] for column in envelope["columns"]]
    for row in envelope["rows"]:
        lines.append(json.dumps({"type": "row", "values": [row[name] for name in column_names]}, sort_keys=True, allow_nan=False))
    lines.append(json.dumps({"type": "end", "row_count": envelope["row_count"], "truncated": envelope["truncated"]}, sort_keys=True))
    return "\n".join(lines) + "\n"


def _render_csv(envelope: dict[str, Any]) -> tuple[str, str]:
    column_names = [column["name"] for column in envelope["columns"]]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=column_names)
    writer.writeheader()
    for row in envelope["rows"]:
        writer.writerow({key: _csv_value(row[key]) for key in column_names})
    metadata = {
        "envelope_version": envelope["envelope_version"],
        "columns": envelope["columns"],
        "row_count": envelope["row_count"],
        "truncated": envelope["truncated"],
    }
    return handle.getvalue(), json.dumps(metadata, sort_keys=True) + "\n"


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
