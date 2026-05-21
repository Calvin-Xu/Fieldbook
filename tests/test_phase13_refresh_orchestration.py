import json
import os
import sqlite3
import sys
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _write_refresh_config(root: Path, body: str) -> Path:
    config_dir = root / ".fieldbook"
    config_dir.mkdir()
    config = config_dir / "refresh.toml"
    config.write_text(body, encoding="utf-8")
    return config


def _job_json_command(job_id: str, status: str, external_id: str) -> list[str]:
    script = (
        "import json; "
        f"print(json.dumps({{'jobs': [{{'id': {job_id!r}, 'status': {status!r}, "
        f"'external_id': {external_id!r}, 'name': 'iris refresh'}}]}}))"
    )
    return [sys.executable, "-c", script]


def _touch_future(path: Path) -> None:
    future = path.stat().st_mtime + 10.0
    os.utime(path, (future, future))


def test_refresh_config_listing_and_source_validation(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    snapshot = tmp_path / "jobs.json"
    snapshot.write_text('{"jobs": []}\n', encoding="utf-8")
    _write_refresh_config(
        tmp_path,
        f"""
        [sources.iris_jobs]
        kind = "file"
        adapter = "iris-jobs-json"
        path = {_toml_string(str(snapshot))}
        description = "Refresh Iris job summaries."
        """,
    )

    listed = payload(run_fieldbook(ledger, "refresh", "list-sources"))
    assert listed["config_path"].endswith(".fieldbook/refresh.toml")
    assert listed["sources"] == [
        {
            "name": "iris_jobs",
            "kind": "file",
            "adapter": "iris-jobs-json",
            "description": "Refresh Iris job summaries.",
            "runnable": True,
        }
    ]

    missing_selection = run_fieldbook(ledger, "refresh", "run", check=False)
    assert missing_selection.returncode == ExitCode.VALIDATION_ERROR
    unknown = run_fieldbook(ledger, "refresh", "run", "--source", "missing", check=False)
    assert unknown.returncode == ExitCode.VALIDATION_ERROR


def test_refresh_command_dry_run_apply_and_submission_resolution(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    job = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "eval submit",
            "--status",
            "unknown_submit",
        )
    )
    _write_refresh_config(
        tmp_path,
        f"""
        [sources.iris_jobs]
        kind = "command"
        adapter = "iris-jobs-json"
        command = {_toml_array(_job_json_command(job["id"], "running", "/iris/ack"))}
        description = "Refresh Iris job summaries."
        """,
    )
    session = payload(
        run_fieldbook(ledger, "session", "start", "--experiment", experiment_id, "--agent", "codex")
    )["session"]

    dry_run = payload(run_fieldbook(ledger, "refresh", "run", "--source", "iris_jobs", "--experiment", experiment_id))
    assert dry_run["status"] == "dry_run"
    assert dry_run["stage"] == "reconcile"
    assert dry_run["session_id"] == session["id"]
    assert dry_run["reconcile_event_id"] is None
    assert dry_run["counts"]["update"]["jobs"] == 1
    assert dry_run["counts"]["sync_event"] == 1
    assert Path(dry_run["snapshot_path"]).exists()
    assert Path(dry_run["manifest_path"]).exists()
    assert Path(dry_run["debug_path"]).exists()
    assert dry_run["submission_resolutions"] == [
        {
            "job_id": job["id"],
            "previous_status": "unknown_submit",
            "resolved_status": "running",
            "external_system": "iris",
            "external_id": "/iris/ack",
            "suggested_action": "none",
        }
    ]
    assert payload(run_fieldbook(ledger, "job", "show", job["id"]))["status"] == "unknown_submit"

    applied = payload(
        run_fieldbook(ledger, "refresh", "run", "--source", "iris_jobs", "--experiment", experiment_id, "--apply")
    )
    assert applied["status"] == "applied"
    assert applied["reconcile_event_id"].startswith("rec_")
    refreshed = payload(run_fieldbook(ledger, "job", "show", job["id"]))
    assert refreshed["status"] == "running"
    assert refreshed["external_id"] == "/iris/ack"
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["ready"]["active_job_count"] == 1


def test_refresh_file_source_apply_all_and_log_view(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    metrics = tmp_path / "metrics.csv"
    metrics.write_text(f"run_id,metric_name,value,step\n{run_id},eval/uncheatable_eval/bpb,0.91,100\n", encoding="utf-8")
    _write_refresh_config(
        tmp_path,
        f"""
        [sources.metrics]
        kind = "file"
        adapter = "metrics-csv"
        path = {_toml_string(str(metrics))}
        description = "Refresh metric CSV."
        """,
    )

    result = payload(run_fieldbook(ledger, "refresh", "run", "--all", "--experiment", experiment_id, "--apply"))
    assert result["all"] is True
    assert len(result["results"]) == 1
    applied = result["results"][0]
    assert applied["source"] == "metrics"
    assert applied["status"] == "applied"
    assert applied["counts"]["insert"]["metrics"] == 1
    assert payload(run_fieldbook(ledger, "metric", "list", "--run", run_id))[0]["metric_name"] == "eval/uncheatable_eval/bpb"

    log = payload(run_fieldbook(ledger, "refresh", "log"))
    assert log["events"][0]["source"] == "metrics"
    assert log["events"][0]["status"] == "applied"
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        view_row = conn.execute("SELECT source, status, manifest_path FROM v_refresh_log_v1").fetchone()
    finally:
        conn.close()
    assert view_row["source"] == "metrics"
    assert view_row["status"] == "applied"
    assert view_row["manifest_path"].endswith(".manifest.json")


def test_refresh_failure_stages_and_doctor_checks(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not-json\n", encoding="utf-8")
    bad_artifact = tmp_path / "bad-artifact.json"
    bad_artifact.write_text(
        json.dumps({"artifacts": [{"experiment_id": "exp_missing", "type": "checkpoint", "uri": "gs://bucket/path"}]}),
        encoding="utf-8",
    )
    secret_snapshot = tmp_path / "secret.json"
    secret_snapshot.write_text('{"jobs": [], "token": "OPENAI_API_KEY=sk-example12345678901234567890"}\n', encoding="utf-8")
    _write_refresh_config(
        tmp_path,
        f"""
        [sources.helper_fail]
        kind = "command"
        adapter = "iris-jobs-json"
        command = {_toml_array([sys.executable, "-c", "import sys; print('{\"jobs\": []}'); sys.exit(7)"])}
        description = "Failing helper."

        [sources.adapter_fail]
        kind = "file"
        adapter = "iris-jobs-json"
        path = {_toml_string(str(bad_json))}
        description = "Bad adapter input."

        [sources.reconcile_fail]
        kind = "file"
        adapter = "artifacts-json"
        path = {_toml_string(str(bad_artifact))}
        description = "Bad reconcile input."

        [sources.secret_snapshot]
        kind = "file"
        adapter = "iris-jobs-json"
        path = {_toml_string(str(secret_snapshot))}
        description = "Snapshot with suspected secret."
        """,
    )

    helper = payload(run_fieldbook(ledger, "refresh", "run", "--source", "helper_fail", "--experiment", experiment_id, check=False))
    assert helper["status"] == "failed"
    assert helper["stage"] == "helper"
    assert helper["command_argv"][0] == sys.executable
    adapter = payload(run_fieldbook(ledger, "refresh", "run", "--source", "adapter_fail", "--experiment", experiment_id, check=False))
    assert adapter["status"] == "failed"
    assert adapter["stage"] == "adapter"
    reconcile = payload(
        run_fieldbook(ledger, "refresh", "run", "--source", "reconcile_fail", "--experiment", experiment_id, check=False)
    )
    assert reconcile["status"] == "failed"
    assert reconcile["stage"] == "reconcile"
    secret = payload(
        run_fieldbook(ledger, "refresh", "run", "--source", "secret_snapshot", "--experiment", experiment_id, check=False)
    )
    assert secret["status"] == "dry_run"
    assert secret["stage"] == "reconcile"

    doctor = payload(run_fieldbook(ledger, "doctor", "--stale-refresh-snapshot-days", "0", check=False))
    codes = {issue["code"] for issue in doctor["issues"]}
    assert "refresh.failed" in codes
    assert "refresh.snapshot_stale" in codes
    assert "refresh.manifest_unapplied" in codes
    assert "privacy.secret_pattern" in codes

    conn = sqlite3.connect(ledger)
    try:
        event = conn.execute("SELECT id FROM refresh_events WHERE source = 'secret_snapshot'").fetchone()
        assert event is not None
        conn.execute("UPDATE refresh_events SET snapshot_path = ? WHERE id = ?", (str(tmp_path / "missing.json"), event[0]))
        conn.commit()
    finally:
        conn.close()
    doctor = payload(run_fieldbook(ledger, "doctor", check=False))
    assert "refresh.snapshot_missing" in {issue["code"] for issue in doctor["issues"]}


def test_refresh_output_includes_drifted_artifacts(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    local_report = tmp_path / "report.md"
    local_report.write_text("initial\n", encoding="utf-8")
    artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "report",
            "--uri",
            str(local_report),
        )
    )
    local_report.write_text("changed\n", encoding="utf-8")
    _touch_future(local_report)
    snapshot = tmp_path / "jobs.json"
    snapshot.write_text('{"jobs": []}\n', encoding="utf-8")
    _write_refresh_config(
        tmp_path,
        f"""
        [sources.iris_jobs]
        kind = "file"
        adapter = "iris-jobs-json"
        path = {_toml_string(str(snapshot))}
        description = "Refresh Iris job summaries."
        """,
    )

    result = payload(run_fieldbook(ledger, "refresh", "run", "--source", "iris_jobs", "--experiment", experiment_id))
    assert result["drifted_artifacts"][0]["id"] == artifact["id"]
    assert result["drifted_artifacts"][0]["uri"] == str(local_report)
