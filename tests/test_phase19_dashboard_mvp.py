import http.client
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from fieldbook.dashboard import (
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
    dashboard_queries,
    dashboard_routes,
    make_dashboard_server,
    render_experiment_detail,
    render_experiment_index,
    server_config,
)
from fieldbook.errors import ExitCode, ValidationError
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def test_dashboard_default_localhost_and_get_only_routes() -> None:
    config = server_config(host=None, port=None, allow_non_localhost=False)
    assert config == {"host": DEFAULT_DASHBOARD_HOST, "port": DEFAULT_DASHBOARD_PORT}

    with pytest.raises(ValidationError):
        server_config(host="0.0.0.0", port=None, allow_non_localhost=False)
    assert server_config(host="0.0.0.0", port=9000, allow_non_localhost=True) == {"host": "0.0.0.0", "port": 9000}
    assert server_config(host=None, port=0, allow_non_localhost=False) == {"host": DEFAULT_DASHBOARD_HOST, "port": 0}
    with pytest.raises(ValidationError):
        server_config(host=None, port=70000, allow_non_localhost=False)
    assert {route["method"] for route in dashboard_routes()} == {"GET"}


def test_dashboard_handlers_query_only_stable_views() -> None:
    for name, query in dashboard_queries().items():
        lowered = " ".join(query.lower().split())
        assert "_v1" in lowered, name
        assert " from v_" in lowered, name
        assert " from experiments" not in lowered, name
        assert " from runs" not in lowered, name
        assert " from jobs" not in lowered, name
        assert " from artifacts" not in lowered, name
        assert " from notes" not in lowered, name


def test_dashboard_missing_ledger_exits_like_other_non_init_commands(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fieldbook",
            "dashboard",
            "serve",
            "--ledger",
            str(missing),
            "--dry-run",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == ExitCode.NOT_FOUND


def test_dashboard_empty_active_and_archived_rendering(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    empty = render_experiment_index(ledger)
    assert "No experiments recorded yet" in empty

    active_id = create_experiment(ledger)
    archived_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "archived"))["id"]
    payload(run_fieldbook(ledger, "experiment", "archive", archived_id))

    index = render_experiment_index(ledger)
    assert "Open" in index
    assert "Archived" in index
    assert active_id in index
    assert archived_id in index


def test_dashboard_experiment_summary_deduplicates_two_path_jobs(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    first_experiment = create_experiment(ledger)
    second_experiment = payload(run_fieldbook(ledger, "experiment", "create", "--name", "second"))["id"]
    run_id = create_run(ledger, first_experiment)
    job = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "failed"))

    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        created_at = conn.execute("SELECT created_at FROM experiment_runs WHERE experiment_id = ?", (first_experiment,)).fetchone()[0]
        conn.execute("UPDATE jobs SET experiment_id = ? WHERE id = ?", (first_experiment, job["id"]))
        conn.execute(
            "INSERT INTO experiment_runs (experiment_id, run_id, created_at) VALUES (?, ?, ?)",
            (second_experiment, run_id, created_at),
        )
        rows = {
            row["experiment_id"]: dict(row)
            for row in conn.execute(
                "SELECT experiment_id, job_count, failed_job_count FROM v_dashboard_experiments_v1 "
                "WHERE experiment_id IN (?, ?)",
                (first_experiment, second_experiment),
            )
        }

    assert rows[first_experiment]["job_count"] == 1
    assert rows[first_experiment]["failed_job_count"] == 1
    assert rows[second_experiment]["job_count"] == 1
    assert rows[second_experiment]["failed_job_count"] == 1


def test_dashboard_experiment_summary_avoids_join_explosion_plan(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "failed"))
    payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--type",
            "checkpoint",
            "--body",
            "checkpoint",
        )
    )

    with sqlite3.connect(ledger) as conn:
        plan = "\n".join(
            row[3]
            for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM v_dashboard_experiments_v1 ORDER BY updated_at DESC, experiment_id"
            )
        )

    assert "SCAN j LEFT-JOIN" not in plan


def test_dashboard_attention_uses_agent_actionability_not_historical_failures(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    recovered_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "recovered-history"))["id"]
    recovered_run = create_run(ledger, recovered_id)
    recovered_failed = payload(
        run_fieldbook(ledger, "job", "add", "--run", recovered_run, "--name", "old-failure", "--status", "failed")
    )
    payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            recovered_run,
            "--name",
            "successful-retry",
            "--status",
            "succeeded",
            "--retry-of",
            recovered_failed["id"],
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            recovered_id,
            "--type",
            "checkpoint",
            "--body",
            "Recovered and ready.",
        )
    )

    blocking_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "blocking-failure"))["id"]
    blocking_run = payload(
        run_fieldbook(
            ledger,
            "run",
            "add",
            "--name",
            "blocking-run",
            "--experiment",
            blocking_id,
            "--external-system",
            "wandb",
            "--external-id",
            "blocking-run",
        )
    )["id"]
    payload(run_fieldbook(ledger, "job", "add", "--run", blocking_run, "--name", "needs-retry", "--status", "failed"))

    html = render_experiment_index(ledger)
    needs_attention = html.split("id='needs-attention'", 1)[1].split("</section>", 1)[0]
    review = html.split("id='review'", 1)[1].split("</section>", 1)[0]

    assert "blocking-failure" in needs_attention
    assert "recovered-history" not in needs_attention
    assert "recovered-history" in review
    assert "blocking failed" in html.lower()


def test_dashboard_detail_sections_commands_and_external_links(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            run_id,
            "--name",
            "train",
            "--status",
            "running",
            "--external-system",
            "iris",
            "--external-id",
            "https://iris.local/jobs/123",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "report",
            "--uri",
            "https://example.com/report",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "lease",
            "claim",
            "--entity-type",
            "job",
            "--entity-id",
            job["id"],
            "--owner",
            "babysitter",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "metrics.coverage",
            "--status",
            "pass",
        )
    )

    detail = render_experiment_detail(ledger, experiment_id, tab="overview")
    for section in (
        "Run Progress",
        "Job Recovery",
        "Advisory Leases",
        "Validations",
        "Freshness",
        "Notes",
        "Artifacts",
        "External Links",
    ):
        assert section in detail
    assert "tab=runs" in detail
    assert "tab=jobs" in detail
    assert "Agent Instructions" in detail
    assert "Preview agent instruction" in detail
    assert "fieldbook experiment workloop" in detail
    assert "fieldbook refresh run" not in detail
    external_links = render_experiment_detail(ledger, experiment_id, tab="external-links")
    artifacts = render_experiment_detail(ledger, experiment_id, tab="artifacts")
    assert "https://iris.local/jobs/123" in external_links
    assert "https://example.com/report" in artifacts


def test_dashboard_http_roundtrip_get_only_contract(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    server = make_dashboard_server(ledger, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        response = conn.getresponse()
        assert response.status == 200
        assert b"Fieldbook Dashboard" in response.read()
        conn.close()

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", f"/experiment?id={experiment_id}")
        response = conn.getresponse()
        assert response.status == 200
        assert experiment_id.encode() in response.read()
        conn.close()

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/experiment?id=exp_missing")
        response = conn.getresponse()
        assert response.status == 404
        conn.close()

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request(method, "/")
            response = conn.getresponse()
            assert response.status == 405
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_docs_and_skill_describe_read_only_dashboard() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / ".codex" / "skills" / "fieldbook" / "SKILL.md").read_text(encoding="utf-8")

    assert "uv run fieldbook dashboard serve --json" in readme
    assert "reads only stable `_v1`" in readme
    assert "Use the dashboard only as a read-only human scan surface" in skill
    assert "does not send prompts" in skill
