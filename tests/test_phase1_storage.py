import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from fieldbook.db import CURRENT_SCHEMA_VERSION, connect, discover_ledger, init_ledger, resolve_init_path, schema_version
from fieldbook.errors import NotFoundError
from fieldbook.ids import new_id


def test_new_id_has_type_prefix_and_sorts_by_time(monkeypatch):
    times = iter([1.0, 2.0])
    monkeypatch.setattr("fieldbook.ids.time.time", lambda: next(times))

    first = new_id("exp")
    second = new_id("exp")

    assert first.startswith("exp_")
    assert second.startswith("exp_")
    assert first < second


def test_resolve_init_path_uses_git_root(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert resolve_init_path(start=nested, env={}) == tmp_path / ".experiments" / "ledger.sqlite"


def test_resolve_init_path_uses_cwd_outside_git(tmp_path):
    assert resolve_init_path(start=tmp_path, env={}) == tmp_path / ".experiments" / "ledger.sqlite"


def test_discover_ledger_walks_up_from_subdirectory(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    init_ledger(ledger)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert discover_ledger(start=nested, env={}) == ledger


def test_discover_explicit_missing_ledger_does_not_create(tmp_path):
    missing = tmp_path / "missing.sqlite"

    try:
        discover_ledger(ledger=missing, env={})
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected missing explicit ledger to raise")

    assert not missing.exists()


def test_init_ledger_creates_schema_and_pragmas(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"

    init_ledger(ledger)
    conn = connect(ledger)
    try:
        assert schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0] == str(
            CURRENT_SCHEMA_VERSION
        )

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "experiments",
            "experiment_tags",
            "runs",
            "experiment_runs",
            "jobs",
            "artifacts",
            "metrics",
            "notes",
            "reconcile_events",
            "sync_events",
        }.issubset(tables)
    finally:
        conn.close()


def test_repeated_init_preserves_existing_data(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    init_ledger(ledger)
    conn = connect(ledger)
    try:
        conn.execute(
            "INSERT INTO experiments (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("exp_test", "Test", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.execute("INSERT INTO experiment_tags (experiment_id, tag) VALUES (?, ?)", ("exp_test", "marin"))
        conn.commit()
    finally:
        conn.close()

    init_ledger(ledger)
    conn = connect(ledger)
    try:
        assert conn.execute("SELECT name FROM experiments WHERE id = 'exp_test'").fetchone()[0] == "Test"
        assert conn.execute("SELECT tag FROM experiment_tags WHERE experiment_id = 'exp_test'").fetchone()[0] == "marin"
    finally:
        conn.close()


def test_cli_init_json_creates_ledger(tmp_path):
    ledger = tmp_path / "custom.sqlite"
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", "init", "--ledger", str(ledger), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload == {"existed": False, "ledger": str(ledger)}
    assert ledger.exists()


def test_metric_idempotency_treats_missing_optional_fields_as_equal(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    init_ledger(ledger)
    conn = connect(ledger)
    try:
        conn.execute(
            "INSERT INTO runs (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("run_test", "Run", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO metrics (id, run_id, metric_name, value, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("met_1", "run_test", "eval/loss", 1.0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

        try:
            conn.execute(
                "INSERT INTO metrics (id, run_id, metric_name, value, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("met_2", "run_test", "eval/loss", 2.0, "2026-01-01T00:00:01Z", "2026-01-01T00:00:01Z"),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected duplicate metric to violate idempotency index")
    finally:
        conn.close()
