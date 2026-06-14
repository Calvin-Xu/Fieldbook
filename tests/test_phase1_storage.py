import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from fieldbook.db import (
    CURRENT_SCHEMA_VERSION,
    connect,
    discover_ledger,
    init_ledger,
    resolve_init_path,
    schema_version,
)
from fieldbook.errors import NotFoundError, ValidationError
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


def test_note_schema_has_markdown_metadata_defaults_and_constraints(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    init_ledger(ledger)
    conn = connect(ledger)
    try:
        conn.execute(
            "INSERT INTO experiments (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("exp_test", "Test", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO notes (id, entity_type, entity_id, note_type, status, body, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "note_default",
                "experiment",
                "exp_test",
                "research",
                "open",
                "Markdown body",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        default_row = conn.execute(
            "SELECT title, body_format FROM notes WHERE id = 'note_default'"
        ).fetchone()
        assert default_row["title"] is None
        assert default_row["body_format"] == "markdown"

        try:
            conn.execute(
                "INSERT INTO notes (id, entity_type, entity_id, note_type, status, body, body_format, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "note_invalid_format",
                    "experiment",
                    "exp_test",
                    "research",
                    "open",
                    "Body",
                    "html",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected invalid body_format to violate note schema constraint")

        try:
            conn.execute(
                "INSERT INTO notes (id, entity_type, entity_id, note_type, status, title, body, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "note_long_title",
                    "experiment",
                    "exp_test",
                    "research",
                    "open",
                    "x" * 121,
                    "Body",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected overlong title to violate note schema constraint")
    finally:
        conn.close()


def test_reconcile_hardening_schema_and_external_uniqueness(tmp_path):
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    init_ledger(ledger)
    conn = connect(ledger)
    try:
        run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        sync_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_events)").fetchall()}
        reconcile_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reconcile_events)").fetchall()}
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}

        assert "parent_run_id" in run_columns
        assert {"reconcile_event_id", "idempotency_key"}.issubset(sync_columns)
        assert "counts_json" in reconcile_columns
        assert "reconcile_operations" in tables
        assert {"idx_runs_external_unique", "idx_jobs_external_unique"}.issubset(indexes)

        conn.execute(
            "INSERT INTO runs (id, name, external_system, external_id, created_at, updated_at) "
            "VALUES ('run_a', 'A', 'wandb', 'same', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        try:
            conn.execute(
                "INSERT INTO runs (id, name, external_system, external_id, created_at, updated_at) "
                "VALUES ('run_b', 'B', 'wandb', 'same', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected duplicate active external run identifier to fail")

        conn.execute("UPDATE runs SET deleted_at = '2026-01-02T00:00:00Z' WHERE id = 'run_a'")
        conn.execute(
            "INSERT INTO runs (id, name, external_system, external_id, created_at, updated_at) "
            "VALUES ('run_b', 'B', 'wandb', 'same', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
    finally:
        conn.close()


def test_pre_coalesced_partial_ledger_requires_old_upgrade(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(ledger)
    try:
        conn.execute("PRAGMA user_version = 4")
    finally:
        conn.close()

    try:
        connect(ledger)
    except ValidationError as exc:
        message = str(exc)
        assert "predates Fieldbook's coalesced migration baseline" in message
        assert "pre-coalescing Fieldbook version" in message
    else:
        raise AssertionError("expected pre-coalesced ledger to be rejected")
