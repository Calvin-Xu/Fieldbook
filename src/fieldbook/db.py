import os
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Mapping

from fieldbook.errors import LedgerBusyError, NotFoundError, ValidationError


DEFAULT_LEDGER_RELATIVE_PATH = Path(".experiments") / "ledger.sqlite"
CURRENT_SCHEMA_VERSION = 5


def _parents_inclusive(path: Path) -> list[Path]:
    resolved = path.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    return [resolved, *resolved.parents]


def find_git_root(start: Path) -> Path | None:
    for candidate in _parents_inclusive(start):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_init_path(
    start: Path | None = None,
    ledger: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the ledger path for `fieldbook init`."""
    env = os.environ if env is None else env
    if ledger is not None:
        return Path(ledger).expanduser().resolve()
    env_ledger = env.get("FIELDBOOK_LEDGER")
    if env_ledger:
        return Path(env_ledger).expanduser().resolve()

    start = Path.cwd() if start is None else start
    root = find_git_root(start) or Path(start).resolve()
    return root / DEFAULT_LEDGER_RELATIVE_PATH


def discover_ledger(
    start: Path | None = None,
    ledger: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Find an existing ledger for non-init commands."""
    env = os.environ if env is None else env
    if ledger is not None:
        ledger_path = Path(ledger).expanduser().resolve()
        if not ledger_path.exists():
            raise NotFoundError(f"Fieldbook ledger not found: {ledger_path}")
        return ledger_path
    env_ledger = env.get("FIELDBOOK_LEDGER")
    if env_ledger:
        ledger_path = Path(env_ledger).expanduser().resolve()
        if not ledger_path.exists():
            raise NotFoundError(f"Fieldbook ledger not found: {ledger_path}")
        return ledger_path

    start = Path.cwd() if start is None else start
    for candidate in _parents_inclusive(start):
        ledger_path = candidate / DEFAULT_LEDGER_RELATIVE_PATH
        if ledger_path.exists():
            return ledger_path
    raise NotFoundError("no Fieldbook ledger found; run `fieldbook init` first")


def connect(path: Path, *, migrate: bool = True, allow_newer_readonly: bool = False) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise LedgerBusyError(str(exc)) from exc
        raise
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if migrate:
        apply_migrations(conn, allow_newer_readonly=allow_newer_readonly)
    return conn


def _migration_sql(version: int) -> str:
    prefix = f"{version:03d}_"
    migration_files = [
        path
        for path in resources.files("fieldbook.migrations").iterdir()
        if path.name.startswith(prefix) and path.name.endswith(".sql")
    ]
    if len(migration_files) != 1:
        names = ", ".join(sorted(path.name for path in migration_files)) or "none"
        raise RuntimeError(f"expected one migration for version {version}, found {names}")
    return migration_files[0].read_text()


def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        sql = statement.strip()
        if sql:
            conn.execute(sql)


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def apply_migrations(conn: sqlite3.Connection, *, allow_newer_readonly: bool = False) -> None:
    current = schema_version(conn)
    if current > CURRENT_SCHEMA_VERSION:
        if allow_newer_readonly:
            return
        raise ValidationError(
            f"ledger schema version {current} is newer than supported version {CURRENT_SCHEMA_VERSION}"
        )
    conn.execute("BEGIN")
    try:
        current = schema_version(conn)
        if current > CURRENT_SCHEMA_VERSION:
            if allow_newer_readonly:
                conn.rollback()
                return
            raise ValidationError(
                f"ledger schema version {current} is newer than supported version {CURRENT_SCHEMA_VERSION}"
            )
        for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
            _preflight_migration(conn, version)
            _execute_sql_script(conn, _migration_sql(version))
            conn.execute("PRAGMA user_version = %d" % version)
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata (key, value, updated_at) "
                "VALUES ('schema_version', ?, datetime('now'))",
                (str(version),),
            )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _preflight_migration(conn: sqlite3.Connection, version: int) -> None:
    if version != 5:
        return
    conflicts: list[str] = []
    for table in ("runs", "jobs"):
        rows = conn.execute(
            f"SELECT external_system, external_id, GROUP_CONCAT(id, ', ') AS ids "
            f"FROM {table} WHERE deleted_at IS NULL AND external_system IS NOT NULL "
            f"AND external_id IS NOT NULL GROUP BY external_system, external_id HAVING COUNT(*) > 1"
        ).fetchall()
        for row in rows:
            conflicts.append(f"{table} {row['external_system']}:{row['external_id']} -> {row['ids']}")
    if conflicts:
        details = "; ".join(conflicts)
        raise ValidationError(f"duplicate active external identifiers block schema migration 5: {details}")


def init_ledger(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path, migrate=False)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        apply_migrations(conn)
    finally:
        conn.close()
    return path
