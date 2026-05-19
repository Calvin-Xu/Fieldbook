import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fieldbook.db import CURRENT_SCHEMA_VERSION, connect
from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def run_plain(
    cwd: Path,
    *args: str,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", *args],
        cwd=cwd,
        text=True,
        input=input_text,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def test_doctor_clean_ledger_json_text_and_checks(tmp_path):
    ledger = init_ledger(tmp_path)
    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text("{}")
    payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(empty_manifest), "--source", "empty", "--apply"))

    result = payload(run_fieldbook(ledger, "doctor"))
    assert result["envelope_version"] == 1
    assert result["ok"] is True
    assert result["issue_count"] == 0
    assert result["schema_version"] == CURRENT_SCHEMA_VERSION

    text = run_plain(tmp_path, "doctor", "--ledger", str(ledger))
    assert "Fieldbook doctor: ok" in text.stdout

    checks = payload(run_fieldbook(ledger, "doctor", "--list-checks"))
    check_ids = {check["id"] for check in checks["checks"]}
    assert {"attrs-json", "note-entity", "local-artifacts", "stale-jobs", "external-ids", "sync-events", "reconcile-log"}.issubset(check_ids)

    unknown = run_fieldbook(ledger, "doctor", "--check", "missing-check", check=False)
    assert unknown.returncode == ExitCode.VALIDATION_ERROR


def test_doctor_detects_drift_and_strict_warnings(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    missing_local = tmp_path / "missing-result.json"
    remote_uri = "gs://bucket/result.json"
    now = "2026-05-18T00:00:00Z"
    old = "2026-05-16T00:00:00Z"

    conn = connect(ledger)
    try:
        conn.execute("UPDATE runs SET attrs_json = ? WHERE id = ?", ("[]", run_id))
        conn.execute(
            "INSERT INTO notes (id, entity_type, entity_id, note_type, status, body, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("note_missing", "run", "run_missing", "debug", "open", "bad ref", now, now),
        )
        conn.execute(
            "INSERT INTO artifacts (id, run_id, type, uri, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("art_missing", run_id, "eval-result", str(missing_local), now, now),
        )
        conn.execute(
            "INSERT INTO artifacts (id, run_id, type, uri, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("art_remote", run_id, "eval-result", remote_uri, now, now),
        )
        conn.execute(
            "INSERT INTO jobs (id, run_id, name, status, updated_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("job_stale", run_id, "train", "running", old, old),
        )
        conn.execute(
            "INSERT INTO runs (id, name, external_system, external_id, created_at, updated_at, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run_archived_dup", "old", "wandb", "abc123", old, old, old),
        )
        conn.execute(
            "INSERT INTO sync_events (id, target_system, status, run_id, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("sync_soft_deleted", "wandb", "synced", "run_archived_dup", "soft", now),
        )
        conn.execute(
            "INSERT INTO reconcile_events (id, source, inserts_json, updates_json, counts_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("rec_bad", "bad", "{not-json", "{}", "{}", now),
        )
        conn.commit()
    finally:
        conn.close()

    result = run_fieldbook(ledger, "doctor", "--stale-hours", "24", check=False)
    data = payload(result)
    codes = {issue["code"] for issue in data["issues"]}
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert {
        "attrs.invalid_json",
        "dangling.note_entity",
        "artifact.local_missing",
        "job.stale_active",
        "external_id.duplicate_archived",
        "sync_event.dangling_entity",
        "reconcile_log.anomaly",
    }.issubset(codes)
    assert "artifact.local_missing" not in {
        issue["code"]
        for issue in data["issues"]
        if issue.get("details", {}).get("uri") == remote_uri
    }

    selected = payload(run_fieldbook(ledger, "doctor", "--check", "note-entity", check=False))
    assert {issue["code"] for issue in selected["issues"]} == {"dangling.note_entity"}

    warning_only = run_fieldbook(ledger, "doctor", "--check", "stale-jobs", check=False)
    assert warning_only.returncode == 0
    strict = run_fieldbook(ledger, "doctor", "--check", "stale-jobs", "--strict", check=False)
    assert strict.returncode == ExitCode.VALIDATION_ERROR


def test_doctor_schema_mismatch(tmp_path):
    ledger = init_ledger(tmp_path)
    conn = sqlite3.connect(ledger)
    try:
        conn.execute("PRAGMA user_version = 1")
    finally:
        conn.close()

    result = run_fieldbook(ledger, "doctor", check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert payload(result)["issues"][0]["code"] == "schema.version_mismatch"


def test_snapshot_export_inspect_import_and_replace(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    snapshot = tmp_path / "snapshot.sqlite"

    exported = payload(run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot)))
    metadata = Path(exported["metadata_path"])
    assert snapshot.exists()
    assert metadata.exists()
    assert exported["schema_version"] == CURRENT_SCHEMA_VERSION
    assert not (tmp_path / "snapshot.sqlite-wal").exists()

    inspect_payload = payload(run_fieldbook(ledger, "snapshot", "inspect", "--input", str(snapshot)))
    assert inspect_payload["schema_version"] == CURRENT_SCHEMA_VERSION
    assert inspect_payload["metadata"]["schema_version"] == CURRENT_SCHEMA_VERSION
    assert inspect_payload["table_counts"]["experiments"] >= 1

    no_replace = run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot), check=False)
    assert no_replace.returncode == ExitCode.VALIDATION_ERROR
    payload(run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot), "--replace"))

    imported = tmp_path / "imported.sqlite"
    imported_payload = payload(
        run_plain(
            tmp_path,
            "snapshot",
            "import",
            "--input",
            str(snapshot),
            "--output",
            str(imported),
            "--json",
        )
    )
    assert imported_payload["schema_version"] == CURRENT_SCHEMA_VERSION
    assert imported.exists()
    imported_conn = connect(imported)
    try:
        assert imported_conn.execute("SELECT name FROM experiments WHERE id = ?", (experiment_id,)).fetchone()[0] == "benchmark-proxies"
        assert imported_conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        imported_conn.close()

    no_import_replace = run_plain(
        tmp_path,
        "snapshot",
        "import",
        "--input",
        str(snapshot),
        "--output",
        str(imported),
        "--json",
        check=False,
    )
    assert no_import_replace.returncode == ExitCode.VALIDATION_ERROR


def test_snapshot_rejects_invalid_input_and_newer_schema(tmp_path):
    ledger = init_ledger(tmp_path)
    bad = tmp_path / "bad.sqlite"
    bad.write_text("not sqlite", encoding="utf-8")

    inspect_bad = run_fieldbook(ledger, "snapshot", "inspect", "--input", str(bad), check=False)
    assert inspect_bad.returncode == ExitCode.VALIDATION_ERROR

    empty_sqlite = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_sqlite).close()
    inspect_empty = run_fieldbook(ledger, "snapshot", "inspect", "--input", str(empty_sqlite), check=False)
    assert inspect_empty.returncode == ExitCode.VALIDATION_ERROR

    snapshot = tmp_path / "snapshot.sqlite"
    payload(run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot)))
    conn = sqlite3.connect(snapshot)
    try:
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    finally:
        conn.close()
    newer = run_plain(
        tmp_path,
        "snapshot",
        "import",
        "--input",
        str(snapshot),
        "--output",
        str(tmp_path / "newer.sqlite"),
        "--json",
        check=False,
    )
    assert newer.returncode == ExitCode.VALIDATION_ERROR


def test_snapshot_inspect_without_metadata(tmp_path):
    ledger = init_ledger(tmp_path)
    snapshot = tmp_path / "snapshot.sqlite"
    payload(run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot)))
    os.remove(f"{snapshot}.metadata.json")

    inspected = payload(run_fieldbook(ledger, "snapshot", "inspect", "--input", str(snapshot)))
    assert inspected["metadata"] is None
