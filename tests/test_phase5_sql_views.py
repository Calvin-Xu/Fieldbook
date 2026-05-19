import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from fieldbook.errors import ValidationError
from fieldbook.sql_query import _normalize_value
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


EXPECTED_VIEWS = {
    "v_experiments_v1",
    "v_runs_v1",
    "v_jobs_v1",
    "v_artifacts_v1",
    "v_metrics_long_v1",
    "v_experiment_summary_v1",
    "v_run_summary_v1",
    "v_jobs_needing_attention_v1",
    "v_artifact_latest_per_type_v1",
    "v_metric_coverage_v1",
    "v_wandb_sync_coverage_v1",
    "v_wandb_writeback_coverage_v1",
    "v_reconcile_log_v1",
}


def test_stable_views_exist_and_filter_deleted_rows(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    run_fieldbook(ledger, "run", "archive", run_id)

    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        views = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()
        }
        assert EXPECTED_VIEWS.issubset(views)
        assert conn.execute("SELECT COUNT(*) FROM v_runs_v1 WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
        run_columns = [row["name"] for row in conn.execute("PRAGMA table_info(v_runs_v1)").fetchall()]
        assert run_columns == [
            "run_id",
            "name",
            "description",
            "status",
            "external_system",
            "external_id",
            "parent_run_id",
            "created_at",
            "updated_at",
            "attrs_json",
            "experiment_ids",
        ]
    finally:
        conn.close()


def test_db_path_uses_normal_ledger_discovery(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "fieldbook", "init", "--json"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    ledger = tmp_path / ".experiments" / "ledger.sqlite"
    nested = tmp_path / "analysis" / "notebooks"
    nested.mkdir(parents=True)

    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", "db", "path", "--json"],
        cwd=nested,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {"path": str(ledger)}

    missing_dir = tmp_path.parent / f"{tmp_path.name}_missing"
    missing_dir.mkdir()
    missing = subprocess.run(
        [sys.executable, "-m", "fieldbook", "db", "path", "--json"],
        cwd=missing_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0


def test_sql_json_output_limit_truncation_and_empty_metadata(tmp_path):
    ledger = init_ledger(tmp_path)
    envelope = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "WITH RECURSIVE seq(x) AS (VALUES(1) UNION ALL SELECT x + 1 FROM seq WHERE x < 3) SELECT x FROM seq",
            "--limit",
            "2",
        )
    )

    assert envelope["envelope_version"] == 1
    assert envelope["rows"] == [{"x": 1}, {"x": 2}]
    assert envelope["row_count"] == 2
    assert envelope["truncated"] is True
    assert envelope["columns"] == [{"name": "x", "decltype": None, "first_row_type": "integer"}]

    empty = payload(run_fieldbook(ledger, "sql", "--query", "SELECT 1 AS x WHERE 0"))
    assert empty["rows"] == []
    assert empty["columns"] == [{"name": "x", "decltype": None, "first_row_type": None}]
    assert empty["truncated"] is False

    no_limit = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "WITH RECURSIVE seq(x) AS (VALUES(1) UNION ALL SELECT x + 1 FROM seq WHERE x < 1005) SELECT x FROM seq",
            "--no-limit",
        )
    )
    assert no_limit["row_count"] == 1005
    assert no_limit["truncated"] is False


def test_sql_ndjson_and_csv_outputs(tmp_path):
    ledger = init_ledger(tmp_path)
    ndjson = run_fieldbook(
        ledger,
        "sql",
        "--query",
        "SELECT 1 AS x UNION ALL SELECT 2 AS x",
        "--format",
        "ndjson",
    )
    lines = [json.loads(line) for line in ndjson.stdout.splitlines()]
    assert lines[0]["type"] == "meta"
    assert lines[0]["columns"][0]["name"] == "x"
    assert lines[1] == {"type": "row", "values": [1]}
    assert lines[2] == {"type": "row", "values": [2]}
    assert lines[3]["type"] == "end"
    assert lines[3]["row_count"] == 2

    csv_result = run_fieldbook(
        ledger,
        "sql",
        "--query",
        "SELECT 'a,b' AS text, 'line\nbreak' AS multiline",
        "--format",
        "csv",
    )
    rows = list(csv.DictReader(csv_result.stdout.splitlines()))
    assert rows == [{"text": "a,b", "multiline": "linebreak"}] or rows == [{"text": "a,b", "multiline": "line\nbreak"}]
    metadata = json.loads(csv_result.stderr)
    assert metadata["envelope_version"] == 1
    assert metadata["columns"][0]["name"] == "text"
    assert metadata["row_count"] == 1


def test_sql_rejects_unsafe_statements(tmp_path):
    ledger = init_ledger(tmp_path)
    unsafe_queries = [
        "CREATE TABLE bad(id TEXT)",
        "INSERT INTO experiments(id, name, created_at, updated_at) VALUES ('x', 'x', 'x', 'x')",
        "DELETE FROM experiments",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA journal_mode=DELETE",
        "SELECT load_extension('x')",
        "SELECT 1; SELECT 2",
        "-- comment only",
    ]

    for query in unsafe_queries:
        result = run_fieldbook(ledger, "sql", "--query", query, check=False)
        assert result.returncode != 0, query


def test_sql_type_mapping_blob_and_output_caps(tmp_path):
    ledger = init_ledger(tmp_path)
    values = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT NULL AS n, 42 AS safe, 9007199254740993 AS big, 'hello' AS text",
        )
    )
    assert values["rows"] == [{"n": None, "safe": 42, "big": "9007199254740993", "text": "hello"}]

    blob = run_fieldbook(ledger, "sql", "--query", "SELECT x'6162' AS blob_value", check=False)
    assert blob.returncode != 0
    assert "BLOB" in blob.stderr

    blob_allowed = payload(
        run_fieldbook(ledger, "sql", "--query", "SELECT x'6162' AS blob_value", "--allow-blobs")
    )
    assert blob_allowed["rows"] == [{"blob_value": "YWI="}]
    assert blob_allowed["columns"][0]["first_row_type"] == "blob_base64"

    too_large = run_fieldbook(
        ledger,
        "sql",
        "--query",
        "SELECT 'abcdef' AS text",
        "--max-output-bytes",
        "10",
        check=False,
    )
    assert too_large.returncode != 0
    assert "output" in too_large.stderr

    mixed_blob = run_fieldbook(
        ledger,
        "sql",
        "--query",
        "SELECT NULL AS maybe_blob UNION ALL SELECT x'6162' AS maybe_blob",
        check=False,
    )
    assert mixed_blob.returncode != 0
    assert "BLOB" in mixed_blob.stderr

    mixed_blob_allowed = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT NULL AS maybe_blob UNION ALL SELECT x'6162' AS maybe_blob",
            "--allow-blobs",
        )
    )
    assert mixed_blob_allowed["rows"] == [{"maybe_blob": None}, {"maybe_blob": "YWI="}]


def test_sql_rejects_non_finite_real_values():
    for value in [float("nan"), float("inf"), float("-inf")]:
        try:
            _normalize_value(value, allow_blobs=False)
        except ValidationError:
            pass
        else:
            raise AssertionError("expected non-finite float to raise ValidationError")


def test_sql_timeout_interrupts_runaway_query(tmp_path):
    ledger = init_ledger(tmp_path)
    result = run_fieldbook(
        ledger,
        "sql",
        "--query",
        "WITH RECURSIVE seq(x) AS (VALUES(1) UNION ALL SELECT x + 1 FROM seq WHERE x < 100000000) SELECT max(x) FROM seq",
        "--timeout",
        "0.001",
        check=False,
    )

    assert result.returncode != 0
    assert "timeout" in result.stderr.lower() or "interrupted" in result.stderr.lower()
