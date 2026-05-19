import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, init_ledger, payload, run_fieldbook


def run_fieldbook_cwd(
    cwd: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def ledger_id(ledger: Path) -> str:
    conn = sqlite3.connect(ledger)
    try:
        row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'ledger_id'").fetchone()
    finally:
        conn.close()
    assert row is not None
    return str(row[0])


def test_ledger_id_db_where_and_snapshot_preserve_identity(tmp_path):
    ledger = init_ledger(tmp_path)
    first_id = ledger_id(ledger)
    assert first_id

    run_fieldbook(ledger, "init")
    assert ledger_id(ledger) == first_id

    where = payload(run_fieldbook(ledger, "db", "where"))
    assert where["envelope_version"] == 1
    assert where["ledger_path"] == str(ledger)
    assert where["ledger_id"] == first_id
    assert where["resolved_via"] == "--ledger"

    snapshot = tmp_path / "snapshot.sqlite"
    exported = payload(run_fieldbook(ledger, "snapshot", "export", "--output", str(snapshot)))
    metadata = json.loads(Path(exported["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["ledger_id"] == first_id

    imported = tmp_path / "imported.sqlite"
    run_fieldbook(ledger, "snapshot", "import", "--input", str(snapshot), "--output", str(imported))
    assert ledger_id(imported) == first_id


def test_db_where_reports_missing_ledger_and_fieldbook_config_resolution(tmp_path):
    missing = payload(run_fieldbook_cwd(tmp_path, "db", "where", "--json"))
    assert missing["ledger_path"] is None
    assert missing["ledger_id"] is None
    assert missing["resolved_via"] is None
    assert missing["would_init_at"] == str(tmp_path / ".experiments" / "ledger.sqlite")

    shared = tmp_path / "shared" / "ledger.sqlite"
    run_fieldbook_cwd(tmp_path, "init", "--ledger", str(shared), "--json")
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / ".fieldbook").write_text("ledger: ../shared/ledger.sqlite\n", encoding="utf-8")

    resolved = payload(run_fieldbook_cwd(nested, "db", "where", "--json"))
    assert resolved["ledger_path"] == str(shared)
    assert resolved["ledger_id"] == ledger_id(shared)
    assert resolved["resolved_via"] == ".fieldbook"

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / ".fieldbook").write_text("not_ledger: nope\n", encoding="utf-8")
    result = run_fieldbook_cwd(bad, "experiment", "list", "--json", check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "ledger" in result.stderr


def test_experiment_idempotency_key_returns_existing_without_updates(tmp_path):
    ledger = init_ledger(tmp_path)
    created = payload(
        run_fieldbook(
            ledger,
            "experiment",
            "create",
            "--name",
            "Original",
            "--description",
            "First description",
            "--tag",
            "first",
            "--idempotency-key",
            "phase11.session-test",
        )
    )
    assert created["idempotency_key"] == "phase11.session-test"
    assert created["existed"] is False

    reused = payload(
        run_fieldbook(
            ledger,
            "experiment",
            "create",
            "--name",
            "Replacement",
            "--description",
            "Second description",
            "--tag",
            "second",
            "--idempotency-key",
            "phase11.session-test",
        )
    )
    assert reused["id"] == created["id"]
    assert reused["name"] == "Original"
    assert reused["description"] == "First description"
    assert reused["tags"] == ["first"]
    assert reused["existed"] is True

    invalid = run_fieldbook(
        ledger,
        "experiment",
        "create",
        "--name",
        "Invalid",
        "--idempotency-key",
        "Bad Key",
        check=False,
    )
    assert invalid.returncode == ExitCode.VALIDATION_ERROR


def test_session_start_current_note_stamp_and_end(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)

    session = payload(
        run_fieldbook(
            ledger,
            "session",
            "start",
            "--experiment",
            experiment_id,
            "--agent",
            "codex",
            "--intent",
            "implement phase 11",
        )
    )
    assert session["session"]["id"].startswith("ses_")
    assert session["marker_status"] == "ok"
    marker = Path(session["marker_path"])
    assert marker.read_text(encoding="utf-8") == f"id: {session['session']['id']}\n"

    current = payload(run_fieldbook(ledger, "session", "current"))
    assert current["session"]["id"] == session["session"]["id"]
    assert current["marker_status"] == "ok"

    note = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "research",
            "--body",
            "Session stamped note",
        )
    )
    assert note["attrs"]["session_id"] == session["session"]["id"]

    ended = payload(run_fieldbook(ledger, "session", "end"))
    assert ended["closed"] is True
    assert ended["session"]["id"] == session["session"]["id"]
    assert not marker.exists()

    none = payload(run_fieldbook(ledger, "session", "end"))
    assert none["closed"] is False
    assert none["reason"] == "no_current_session"


def test_session_env_override_does_not_delete_unrelated_marker(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    first = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id))["session"]
    second = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id))["session"]
    marker = tmp_path / ".fieldbook.session"
    marker.write_text(f"id: {first['id']}\n", encoding="utf-8")
    env = {**os.environ, "FIELDBOOK_SESSION_ID": second["id"]}

    current = payload(
        run_fieldbook_cwd(
            tmp_path,
            "session",
            "current",
            "--ledger",
            str(ledger),
            "--json",
            env=env,
        )
    )
    assert current["session"]["id"] == second["id"]
    assert current["resolution_source"] == "FIELDBOOK_SESSION_ID"
    assert current["marker_status"] == "ok"
    assert current["session_status"] == "ok"

    ended = payload(
        run_fieldbook_cwd(
            tmp_path,
            "session",
            "end",
            "--ledger",
            str(ledger),
            "--json",
            env=env,
        )
    )
    assert ended["session"]["id"] == second["id"]
    assert ended["env_hint"]
    assert ended["marker_status"] == "unchanged"
    assert marker.read_text(encoding="utf-8") == f"id: {first['id']}\n"


def test_session_switch_writes_handoff_and_rejects_archived_targets(tmp_path):
    ledger = init_ledger(tmp_path)
    old_experiment = create_experiment(ledger)
    new_experiment = payload(run_fieldbook(ledger, "experiment", "create", "--name", "new experiment"))["id"]
    archived = payload(run_fieldbook(ledger, "experiment", "create", "--name", "archived experiment"))["id"]
    run_fieldbook(ledger, "experiment", "archive", archived)

    run_fieldbook(
        ledger,
        "note",
        "add",
        "--entity-type",
        "experiment",
        "--entity-id",
        old_experiment,
        "--type",
        "next-action",
        "--title",
        "Continue work",
        "--body",
        "Continue the implementation",
    )
    old_session = payload(run_fieldbook(ledger, "session", "start", "--experiment", old_experiment))["session"]

    archived_result = run_fieldbook(ledger, "session", "switch", "--to", archived, check=False)
    assert archived_result.returncode == ExitCode.VALIDATION_ERROR

    switched = payload(run_fieldbook(ledger, "session", "switch", "--to", new_experiment))
    assert switched["closed_session"]["id"] == old_session["id"]
    assert switched["session"]["experiment_id"] == new_experiment
    assert switched["handoff_note"]["attrs"]["session_id"] == old_session["id"]
    assert "Continue work" in switched["handoff_note"]["body"]
    assert "Open Next Actions" in switched["handoff_note"]["body"]
    assert switched["context"]["experiment"]["id"] == new_experiment

    sessions = payload(run_fieldbook(ledger, "session", "list", "--experiment", old_experiment))
    assert [row["id"] for row in sessions["sessions"]] == [old_session["id"]]
    assert sessions["sessions"][0]["ended_at"] is not None


def test_reconcile_and_sync_events_stamp_session_lineage(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    session_id = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id))["session"]["id"]

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "runs": [{"id": "run_session", "name": "session-run"}],
                "sync_events": [
                    {
                        "target_system": "iris",
                        "target_identifier": "/example/job",
                        "status": "synced",
                        "idempotency_key": "phase11-sync",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = payload(
        run_fieldbook(
            ledger,
            "reconcile",
            "file",
            "--path",
            str(manifest),
            "--source",
            "phase11",
            "--experiment",
            experiment_id,
            "--apply",
        )
    )
    assert result["reconcile_event"]["session_id"] == session_id

    log = payload(run_fieldbook(ledger, "reconcile", "log", "--event", result["reconcile_event"]["id"]))
    assert log["session_id"] == session_id

    conn = sqlite3.connect(ledger)
    try:
        row = conn.execute("SELECT attrs_json FROM sync_events WHERE idempotency_key = 'phase11-sync'").fetchone()
    finally:
        conn.close()
    assert json.loads(row[0])["session_id"] == session_id


def test_doctor_reports_stale_sessions(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    session_id = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id))["session"]["id"]

    conn = sqlite3.connect(ledger)
    try:
        conn.execute(
            "UPDATE sessions SET last_touch_at = '2026-01-01T00:00:00Z', started_at = '2026-01-01T00:00:00Z' "
            "WHERE id = ?",
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()

    doctor = payload(run_fieldbook(ledger, "doctor", "--check", "stale-sessions", "--strict", check=False))
    assert doctor["issue_count"] == 1
    assert doctor["issues"][0]["code"] == "session.stale_open"
    assert doctor["issues"][0]["entity_id"] == session_id
