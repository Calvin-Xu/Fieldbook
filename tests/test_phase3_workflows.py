import json
import sqlite3
import csv
import subprocess
import sys
from pathlib import Path

from fieldbook.db import CURRENT_SCHEMA_VERSION, _execute_sql_script, _migration_sql
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def test_status_reports_stale_failed_artifacts_and_next_actions(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    running = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "running", "--status", "running"))
    failed = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "failed", "--status", "failed"))
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
            "report.md",
        )
    )
    run_artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_id,
            "--type",
            "checkpoint",
            "--uri",
            "gs://bucket/checkpoint",
        )
    )
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
            "next-action",
            "--body",
            "Analyze results",
        )
    )

    conn = sqlite3.connect(ledger)
    try:
        conn.execute("UPDATE jobs SET updated_at = '2026-01-01T00:00:00Z' WHERE id = ?", (running["id"],))
        conn.commit()
    finally:
        conn.close()

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id, "--stale-hours", "1"))
    assert [job["id"] for job in status["stale_jobs"]] == [running["id"]]
    assert [job["id"] for job in status["failed_jobs"]] == [failed["id"]]
    assert {item["id"] for item in status["key_artifacts"]} == {artifact["id"], run_artifact["id"]}
    assert [item["id"] for item in status["notes"]["open_next_actions"]] == [note["id"]]


def test_status_and_context_categorize_notes_without_shredding_markdown(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    handoff = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "handoff",
            "--title",
            "Blocked",
            "--body",
            "Blocked on data.\n\n- Need token counts",
        )
    )
    next_action = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "next-action",
            "--body",
            "Run the next step.\n\nDetails should not appear in status.",
        )
    )
    debug = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "debug",
            "--body",
            "Investigate failure",
        )
    )
    research = payload(
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
            "Long-lived finding",
        )
    )
    decision = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "decision",
            "--body",
            "Use Markdown notes",
        )
    )
    run_fieldbook(ledger, "note", "resolve", research["id"])

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert [row["id"] for row in status["notes"]["open_handoffs"]] == [handoff["id"]]
    assert [row["id"] for row in status["notes"]["open_next_actions"]] == [next_action["id"]]
    assert [row["id"] for row in status["notes"]["open_debug"]] == [debug["id"]]
    assert [row["id"] for row in status["notes"]["recent_research"]] == [research["id"]]
    assert [row["id"] for row in status["notes"]["recent_decisions"]] == [decision["id"]]
    assert status["notes"]["open_handoffs"][0]["body_preview"] == "Blocked on data."
    assert "body" not in status["notes"]["open_handoffs"][0]
    assert status["note_counts"]["handoff"]["open"] == 1
    assert status["note_counts"]["research"]["resolved"] == 1

    context = payload(run_fieldbook(ledger, "experiment", "context", experiment_id))
    assert context["notes"]["open_handoffs"][0]["body"] == handoff["body"]
    assert context["notes"]["open_next_actions"][0]["body"] == next_action["body"]
    assert context["notes"]["recent_research"][0]["body"] == research["body"]

    text_context = subprocess.run(
        [sys.executable, "-m", "fieldbook", "experiment", "context", experiment_id, "--ledger", str(ledger)],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "# Fieldbook Context:" in text_context.stdout
    assert "## Open Handoffs" in text_context.stdout
    assert "Blocked on data.\n\n- Need token counts" in text_context.stdout


def test_reconcile_file_dry_run_apply_and_atomic_failure(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "run_manifest",
                        "name": "manifest-run",
                        "external_system": "wandb",
                        "external_id": "manifest-run",
                    }
                ],
                "jobs": [
                    {
                        "id": "job_manifest",
                        "run_id": "run_manifest",
                        "name": "eval",
                        "status": "succeeded",
                        "external_system": "iris",
                        "external_id": "/calvinxu/eval",
                    }
                ],
                "artifacts": [
                    {
                        "id": "art_manifest",
                        "run_id": "run_manifest",
                        "type": "eval-result",
                        "uri": "gs://bucket/results.json",
                    }
                ],
                "metrics": [{"run_id": "run_manifest", "metric_name": "eval/loss", "value": 1.2}],
                "notes": [
                    {
                        "id": "note_manifest",
                        "entity_type": "run",
                        "entity_id": "run_manifest",
                        "note_type": "research",
                        "title": "Manifest note",
                        "body_format": "plain",
                        "body": "Imported from manifest",
                    }
                ],
                "custom_attributes": [
                    {
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "attrs": {"marin.issue": 5416},
                    }
                ],
            }
        )
    )

    dry_run = payload(
        run_fieldbook(
            ledger,
            "reconcile",
            "file",
            "--path",
            str(manifest_path),
            "--source",
            "fixture",
            "--experiment",
            experiment_id,
        )
    )
    assert dry_run["apply"] is False
    assert dry_run["counts"]["insert"] == {
        "artifacts": 1,
        "jobs": 1,
        "metrics": 1,
        "notes": 1,
        "runs": 1,
    }

    assert payload(run_fieldbook(ledger, "run", "list", "--experiment", experiment_id)) == []

    applied = payload(
        run_fieldbook(
            ledger,
            "reconcile",
            "file",
            "--path",
            str(manifest_path),
            "--source",
            "fixture",
            "--experiment",
            experiment_id,
            "--apply",
        )
    )
    assert applied["apply"] is True
    assert payload(run_fieldbook(ledger, "run", "show", "run_manifest"))["name"] == "manifest-run"
    assert payload(run_fieldbook(ledger, "experiment", "show", experiment_id))["attrs"]["marin.issue"] == 5416
    manifest_note = payload(run_fieldbook(ledger, "note", "show", "note_manifest"))
    assert manifest_note["title"] == "Manifest note"
    assert manifest_note["body_format"] == "plain"

    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text(
        json.dumps(
            {
                "runs": [{"id": "run_bad", "name": "bad"}],
                "artifacts": [{"run_id": "run_bad", "type": "not-a-type", "uri": "gs://bad"}],
            }
        )
    )
    failed = run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(bad_manifest),
        "--experiment",
        experiment_id,
        "--apply",
        check=False,
    )
    assert failed.returncode != 0
    missing = run_fieldbook(ledger, "run", "show", "run_bad", check=False)
    assert missing.returncode != 0


def test_reconcile_note_defaults_and_body_validation(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    manifest_path = tmp_path / "legacy_notes.json"
    manifest_path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note_legacy",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "Legacy note",
                    }
                ]
            }
        )
    )
    run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(manifest_path),
        "--experiment",
        experiment_id,
        "--apply",
    )
    legacy_note = payload(run_fieldbook(ledger, "note", "show", "note_legacy"))
    assert legacy_note["title"] is None
    assert legacy_note["body_format"] == "markdown"

    plain_manifest = tmp_path / "plain_note.json"
    plain_manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note_plain",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body_format": "plain",
                        "body": "Initial plain note",
                    }
                ]
            }
        )
    )
    run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(plain_manifest),
        "--experiment",
        experiment_id,
        "--apply",
    )
    assert payload(run_fieldbook(ledger, "note", "show", "note_plain"))["body_format"] == "plain"

    update_manifest = tmp_path / "plain_note_update.json"
    update_manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note_plain",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "Updated plain note",
                    }
                ]
            }
        )
    )
    run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(update_manifest),
        "--experiment",
        experiment_id,
        "--apply",
    )
    updated_plain = payload(run_fieldbook(ledger, "note", "show", "note_plain"))
    assert updated_plain["body"] == "Updated plain note"
    assert updated_plain["body_format"] == "plain"

    bad_manifest = tmp_path / "bad_note.json"
    bad_manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note_bad",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "",
                    }
                ]
            }
        )
    )
    failed = run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(bad_manifest),
        "--experiment",
        experiment_id,
        "--apply",
        check=False,
    )
    assert failed.returncode != 0


def test_metric_exports_and_coverage_record_artifacts(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "eval", "--status", "succeeded"))
    source_artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_id,
            "--job",
            job["id"],
            "--type",
            "eval-result",
            "--uri",
            "gs://bucket/eval.json",
        )
    )
    run_fieldbook(
        ledger,
        "metric",
        "add",
        "--run",
        run_id,
        "--name",
        "eval/loss",
        "--value",
        "1.0",
        "--source-job",
        job["id"],
        "--source-artifact",
        source_artifact["id"],
    )
    run_fieldbook(ledger, "metric", "add", "--run", run_id, "--name", "eval/acc", "--value", "0.25")

    long_path = tmp_path / "long.csv"
    wide_path = tmp_path / "wide.csv"
    coverage_path = tmp_path / "coverage.csv"

    long_result = payload(
        run_fieldbook(
            ledger,
            "export",
            "metrics-long",
            "--experiment",
            experiment_id,
            "--output",
            str(long_path),
        )
    )
    assert long_result["row_count"] == 2
    assert long_path.read_text().splitlines()[0].startswith("experiment_id,run_id,run_name")

    wide_result = payload(
        run_fieldbook(
            ledger,
            "export",
            "runs-wide",
            "--experiment",
            experiment_id,
            "--output",
            str(wide_path),
            "--metric",
            "eval/loss",
        )
    )
    assert wide_result["metric_columns"] == ["eval/loss"]
    wide_lines = wide_path.read_text().splitlines()
    assert "eval/loss" in wide_lines[0]
    assert "eval/loss__source_job_id" in wide_lines[0]
    assert "eval/loss__source_artifact_uri" in wide_lines[0]
    assert "gs://bucket/eval.json" in wide_lines[1]

    coverage = payload(
        run_fieldbook(
            ledger,
            "export",
            "coverage",
            "--experiment",
            experiment_id,
            "--output",
            str(coverage_path),
            "--metric",
            "eval/loss",
            "--metric",
            "missing",
        )
    )
    rows_by_metric = {row["metric_name"]: row for row in coverage["rows"]}
    assert rows_by_metric["eval/loss"]["coverage"] == 1.0
    assert rows_by_metric["missing"]["coverage"] == 0.0

    artifacts = payload(run_fieldbook(ledger, "artifact", "list", "--experiment", experiment_id))
    assert {artifact["type"] for artifact in artifacts} == {"eval-result", "metric-table"}


def test_deleted_experiment_rejects_new_writes(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    active_experiment = payload(run_fieldbook(ledger, "experiment", "create", "--name", "active"))["id"]
    run_id = payload(run_fieldbook(ledger, "run", "add", "--experiment", active_experiment, "--name", "run"))["id"]
    run_fieldbook(ledger, "experiment", "archive", experiment_id)

    result = run_fieldbook(
        ledger,
        "run",
        "add",
        "--experiment",
        experiment_id,
        "--name",
        "should-not-write",
        check=False,
    )

    assert result.returncode != 0
    assert "cannot be mutated" in result.stderr

    link_result = run_fieldbook(
        ledger,
        "run",
        "link",
        run_id,
        "--experiment",
        experiment_id,
        check=False,
    )
    assert link_result.returncode != 0
    assert "cannot be mutated" in link_result.stderr


def test_note_decision_and_superseded_are_valid(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)

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
            "decision",
            "--status",
            "superseded",
            "--body",
            "Do not optimize this obsolete metric.",
        )
    )

    assert note["note_type"] == "decision"
    assert note["status"] == "superseded"


def test_artifact_uri_collision_requires_update_existing(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)

    first = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_id,
            "--type",
            "checkpoint",
            "--uri",
            "gs://bucket/same",
        )
    )
    duplicate = run_fieldbook(
        ledger,
        "artifact",
        "add",
        "--run",
        run_id,
        "--type",
        "checkpoint",
        "--uri",
        "gs://bucket/same",
        check=False,
    )
    assert duplicate.returncode != 0
    assert "already exists" in duplicate.stderr

    updated = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_id,
            "--type",
            "checkpoint",
            "--uri",
            "gs://bucket/same",
            "--content-hash",
            "sha256:" + "b" * 64,
            "--update-existing",
        )
    )
    assert updated["id"] == first["id"]
    assert updated["content_hash"] == "sha256:" + "b" * 64


def test_non_init_commands_apply_pending_migrations(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ledger)
    try:
        conn.execute("BEGIN")
        for version in range(1, CURRENT_SCHEMA_VERSION):
            _execute_sql_script(conn, _migration_sql(version))
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata (key, value, updated_at) "
                "VALUES ('schema_version', ?, datetime('now'))",
                (str(version),),
            )
        conn.commit()
    finally:
        conn.close()

    result = payload(run_fieldbook(ledger, "experiment", "list"))
    assert result == []

    conn = sqlite3.connect(ledger)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


def test_metric_import_csv_is_atomic_on_partial_failure(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    csv_path = tmp_path / "bad_metrics.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_id", "metric_name", "value"])
        writer.writeheader()
        writer.writerow({"run_id": run_id, "metric_name": "eval/loss", "value": "1.0"})
        writer.writerow({"run_id": "missing_run", "metric_name": "eval/acc", "value": "0.2"})

    result = run_fieldbook(ledger, "metric", "import-csv", "--path", str(csv_path), check=False)
    assert result.returncode != 0

    assert payload(run_fieldbook(ledger, "metric", "list", "--run", run_id)) == []
