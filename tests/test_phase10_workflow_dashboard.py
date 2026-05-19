import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


PRIVATE_PATTERNS = [
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"/private/"),
    re.compile(r"wandb\.ai/", re.IGNORECASE),
    re.compile(r"gs://", re.IGNORECASE),
    re.compile(r"s3://", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"Bearer\s+", re.IGNORECASE),
    re.compile(r"ghp_"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def test_experiment_triage_readonly_json_and_markdown(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    failed = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "eval", "--status", "failed"))
    stale = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "running"))
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
            "--title",
            "Investigate eval",
            "--body",
            "Need to inspect logs",
        )
    )
    run_fieldbook(
        ledger,
        "artifact",
        "add",
        "--experiment",
        experiment_id,
        "--type",
        "report",
        "--uri",
        str(tmp_path / "private" / "report.md"),
    )
    conn = sqlite3.connect(ledger)
    try:
        conn.execute("UPDATE jobs SET updated_at = '2026-01-01T00:00:00Z' WHERE id = ?", (stale["id"],))
        before = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    triage = payload(run_fieldbook(ledger, "experiment", "triage", experiment_id, "--stale-hours", "1"))
    assert triage["experiment"]["id"] == experiment_id
    assert [job["id"] for job in triage["failed_jobs"]] == [failed["id"]]
    assert [job["id"] for job in triage["stale_jobs"]] == [stale["id"]]
    assert [note["id"] for note in triage["unresolved_debug_notes"]] == [debug["id"]]
    assert triage["doctor_issue_count"] >= 1
    assert triage["key_artifacts"][0]["display_uri"].startswith("local:")
    assert str(tmp_path) not in triage["key_artifacts"][0]["display_uri"]
    assert triage["suggested_next_actions"]

    text = subprocess.run(
        [sys.executable, "-m", "fieldbook", "experiment", "triage", experiment_id, "--ledger", str(ledger)],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "# Fieldbook Triage:" in text.stdout
    assert "Failed Jobs" in text.stdout
    assert str(tmp_path) not in text.stdout

    conn = sqlite3.connect(ledger)
    try:
        after = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        conn.close()
    assert after == before


def test_experiment_closeout_checklist_readonly(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    run_fieldbook(
        ledger,
        "artifact",
        "add",
        "--experiment",
        experiment_id,
        "--type",
        "metric-table",
        "--uri",
        "coverage.csv",
    )
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
        "--title",
        "Closeout",
        "--body",
        "Experiment is complete",
    )
    run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "succeeded")
    conn = sqlite3.connect(ledger)
    try:
        before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notes", "artifacts", "reconcile_events")
        }
    finally:
        conn.close()

    checklist = payload(run_fieldbook(ledger, "experiment", "closeout-checklist", experiment_id))
    by_id = {item["id"]: item for item in checklist["items"]}
    assert by_id["metric_table_export"]["ok"] is True
    assert by_id["decision_note"]["ok"] is True
    assert by_id["failed_jobs"]["ok"] is True
    assert by_id["stale_jobs"]["ok"] is True

    text = subprocess.run(
        [sys.executable, "-m", "fieldbook", "experiment", "closeout-checklist", experiment_id, "--ledger", str(ledger)],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "# Fieldbook Closeout Checklist:" in text.stdout
    assert "- [x] Metric-table export present" in text.stdout

    conn = sqlite3.connect(ledger)
    try:
        after = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notes", "artifacts", "reconcile_events")
        }
    finally:
        conn.close()
    assert after == before


def test_dashboard_artifact_redaction_and_stable_views(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job_id = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "succeeded"))["id"]
    uris = {
        "local_abs": str(tmp_path / "private" / "report.md"),
        "local_rel": "reports/result.json",
        "file_uri": "file:///tmp/private/eval.json",
        "gcs": "gs://example-bucket/result.json",
        "s3": "s3://example-bucket/result.json",
        "wandb": "wandb:entity/project/artifact:latest",
        "http": "https://example.invalid/result.json",
        "other": "ftp://example.invalid/result.json",
    }
    conn = sqlite3.connect(ledger)
    try:
        for key, uri in uris.items():
            conn.execute(
                "INSERT INTO artifacts (id, experiment_id, run_id, job_id, type, uri, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'report', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (f"art_{key}", experiment_id, run_id, job_id, uri),
            )
        conn.execute(
            "INSERT INTO artifacts (id, run_id, type, uri, created_at, updated_at) "
            "VALUES ('art_run_only', ?, 'report', 'run-only.txt', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO jobs (id, experiment_id, name, status, created_at, updated_at) "
            "VALUES ('job_direct_exp', ?, 'direct', 'succeeded', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (experiment_id,),
        )
        conn.execute(
            "INSERT INTO artifacts (id, job_id, type, uri, created_at, updated_at) "
            "VALUES ('art_job_direct', 'job_direct_exp', 'report', 'job-direct.txt', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO jobs (id, run_id, name, status, created_at, updated_at) "
            "VALUES ('job_run_exp', ?, 'run-linked', 'succeeded', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO artifacts (id, job_id, type, uri, created_at, updated_at) "
            "VALUES ('art_job_run', 'job_run_exp', 'report', 'job-run.txt', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO artifacts (id, experiment_id, type, uri, created_at, updated_at) "
            "VALUES ('art_windows', ?, 'report', 'C:\\Users\\name\\report.txt', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (experiment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    rows = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT artifact_id, experiment_id, uri_locality, display_uri FROM v_artifacts_redacted_v1 ORDER BY artifact_id",
            "--no-limit",
        )
    )["rows"]
    by_id = {row["artifact_id"]: row for row in rows}
    assert by_id["art_local_abs"]["uri_locality"] == "local-fs"
    assert by_id["art_local_abs"]["display_uri"] == "local:art_local_abs/report.md"
    assert str(tmp_path) not in by_id["art_local_abs"]["display_uri"]
    assert by_id["art_file_uri"]["display_uri"] == "local:art_file_uri/eval.json"
    assert by_id["art_windows"]["display_uri"] == "local:art_windows/report.txt"
    assert by_id["art_gcs"]["uri_locality"] == "gcs"
    assert by_id["art_s3"]["uri_locality"] == "s3"
    assert by_id["art_wandb"]["uri_locality"] == "wandb"
    assert by_id["art_http"]["uri_locality"] == "http"
    assert by_id["art_other"]["uri_locality"] == "other"
    assert by_id["art_local_rel"]["experiment_id"] == experiment_id
    assert by_id["art_run_only"]["experiment_id"] == experiment_id
    assert by_id["art_job_direct"]["experiment_id"] == experiment_id
    assert by_id["art_job_run"]["experiment_id"] == experiment_id

    columns = payload(
        run_fieldbook(ledger, "sql", "--query", "SELECT * FROM v_artifacts_redacted_v1 LIMIT 0")
    )["columns"]
    assert [column["name"] for column in columns] == [
        "artifact_id",
        "experiment_id",
        "run_id",
        "job_id",
        "type",
        "uri_locality",
        "display_uri",
        "content_hash",
        "created_at",
        "updated_at",
        "attrs_json",
    ]

    views = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name IN ('v_notes_v1', 'v_sync_events_v1') ORDER BY name",
        )
    )["rows"]
    assert views == [{"name": "v_notes_v1"}, {"name": "v_sync_events_v1"}]


def test_workflow_templates_and_dashboard_queries_validate(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job_id = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "succeeded"))["id"]

    manifest_template = Path(".codex/skills/fieldbook/templates/reconcile-eval-refresh.json").read_text()
    manifest = (
        manifest_template.replace("<EXPERIMENT_ID>", experiment_id)
        .replace("<RUN_ID>", run_id)
        .replace("<JOB_ID>", job_id)
        .replace("<ARTIFACT_URI>", "artifact/result.json")
        .replace("<METRIC_NAME>", "eval/loss")
        .replace("<NOTE_BODY>", "Refresh completed")
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest)
    dry_run = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest_path), "--source", "template"))
    assert dry_run["apply"] is False

    note_template = Path(".codex/skills/fieldbook/templates/handoff-note.md").read_text()
    note_body = note_template.replace("<EXPERIMENT_ID>", experiment_id).replace("<NEXT_ACTION>", "Review the export")
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
            "handoff",
            "--body",
            note_body,
        )
    )
    assert note["body"] == note_body

    expected_columns = {
        "portfolio.sql": [
            "experiment_id",
            "name",
            "status",
            "run_count",
            "failed_job_count",
            "open_note_count",
            "updated_at",
        ],
        "drilldown-artifacts.sql": ["artifact_id", "type", "uri_locality", "display_uri", "updated_at"],
    }
    for query_file in sorted(Path("docs/dashboard-readiness/queries").glob("*.sql")):
        query = query_file.read_text().replace("<EXPERIMENT_ID>", experiment_id)
        assert "LIMIT" in query.upper(), query_file
        assert "v_artifacts_v1" not in query, query_file
        result = payload(run_fieldbook(ledger, "sql", "--query", query))
        assert [column["name"] for column in result["columns"]] == expected_columns[query_file.name]


def test_committed_workflow_and_dashboard_examples_do_not_leak_private_values():
    roots = [
        Path(".codex/skills/fieldbook/references/workflows"),
        Path(".codex/skills/fieldbook/templates"),
        Path("docs/dashboard-readiness"),
    ]
    raw = "\n".join(
        path.read_text()
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    )
    stripped_placeholders = re.sub(r"<[^>]+>", "", raw)
    for pattern in PRIVATE_PATTERNS:
        assert not pattern.search(stripped_placeholders), pattern.pattern
