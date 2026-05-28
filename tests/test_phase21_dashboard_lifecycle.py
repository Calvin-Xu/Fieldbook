import sqlite3
from pathlib import Path

from fieldbook.dashboard import render_experiment_detail, render_experiment_index
from tests.test_phase2_cli import create_run, init_ledger, payload, run_fieldbook


def test_dashboard_lifecycle_groups_are_agent_actionable(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    attention_id = _experiment(ledger, "attention")
    attention_run = _run(ledger, attention_id, "attention-run")
    payload(run_fieldbook(ledger, "job", "add", "--run", attention_run, "--name", "failed", "--status", "failed"))

    progress_id = _experiment(ledger, "progress")
    progress_run = _run(ledger, progress_id, "progress-run")
    payload(run_fieldbook(ledger, "job", "add", "--run", progress_run, "--name", "train", "--status", "running"))

    review_id = _experiment(ledger, "review")
    review_run = _run(ledger, review_id, "review-run")
    payload(run_fieldbook(ledger, "job", "add", "--run", review_run, "--name", "train", "--status", "succeeded"))

    open_id = _experiment(ledger, "open")
    payload(run_fieldbook(ledger, "experiment", "mark-reviewed", open_id, "--body", "Nothing pending."))

    archived_id = _experiment(ledger, "archived")
    payload(run_fieldbook(ledger, "experiment", "archive", archived_id))

    html = render_experiment_index(ledger)
    assert "Stale" not in html
    assert "Needs attention" in html
    assert "In progress" in html
    assert "Review" in html
    assert "Open" in html
    assert "Archived" in html

    assert "attention" in _section(html, "needs-attention")
    assert "progress" in _section(html, "in-progress")
    assert "review" in _section(html, "review")
    assert "open" in _section(html, "open")
    assert "archived" in _section(html, "archived")


def test_review_marker_consumes_reviewable_activity_until_new_output(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _experiment(ledger, "review-flow")
    run_id = _run(ledger, experiment_id, "review-flow-run")
    payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "succeeded"))

    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        row = _dashboard_row(conn, experiment_id)
        assert row["lifecycle_state"] == "review"
        assert row["has_pending_review"] == 1
        assert row["last_reviewed_at"] is None
        first_activity = row["last_reviewable_activity_at"]

    marker = payload(run_fieldbook(ledger, "experiment", "mark-reviewed", experiment_id, "--body", "Reviewed train output."))
    assert marker["note"]["note_type"] == "review"
    assert marker["note"]["title"] == "Experiment reviewed"
    assert marker["note"]["attrs"]["fieldbook.review"] is True
    assert marker["note"]["attrs"]["fieldbook.reviewed_at"]

    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        row = _dashboard_row(conn, experiment_id)
        assert row["lifecycle_state"] == "open"
        assert row["has_pending_review"] == 0
        assert row["last_reviewed_at"] >= first_activity

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
            "file:///tmp/new-report.html",
        )
    )
    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        assert _dashboard_row(conn, experiment_id)["lifecycle_state"] == "review"


def test_handoff_freshness_is_badge_not_lifecycle_group(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _experiment(ledger, "handoff-missing")
    payload(run_fieldbook(ledger, "experiment", "mark-reviewed", experiment_id, "--body", "Reviewed empty experiment."))

    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        row = _dashboard_row(conn, experiment_id)
        assert row["handoff_status"] == "idle"
        assert row["lifecycle_state"] == "open"

    html = render_experiment_detail(ledger, experiment_id, tab="freshness")
    assert "Handoff status" in html
    assert "Last handoff" in html


def test_active_work_has_precedence_over_pending_review(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _experiment(ledger, "active-review")
    run_id = _run(ledger, experiment_id, "active-review-run")
    payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "done", "--status", "succeeded"))
    payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "still-running", "--status", "running"))

    with sqlite3.connect(ledger) as conn:
        conn.row_factory = sqlite3.Row
        row = _dashboard_row(conn, experiment_id)
        assert row["has_pending_review"] == 1
        assert row["lifecycle_state"] == "in_progress"


def test_docs_and_skill_explain_lifecycle_review_semantics() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / ".codex" / "skills" / "fieldbook" / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, skill):
        assert "Needs attention" in text
        assert "In progress" in text
        assert "Review" in text
        assert "Open" in text
        assert "fieldbook experiment mark-reviewed" in text
        assert "Archived" in text


def _experiment(ledger: Path, name: str) -> str:
    return payload(run_fieldbook(ledger, "experiment", "create", "--name", name))["id"]


def _run(ledger: Path, experiment_id: str, name: str) -> str:
    return payload(
        run_fieldbook(
            ledger,
            "run",
            "add",
            "--name",
            name,
            "--experiment",
            experiment_id,
            "--external-system",
            "wandb",
            "--external-id",
            name,
        )
    )["id"]


def _dashboard_row(conn: sqlite3.Connection, experiment_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM v_dashboard_experiments_v1 WHERE experiment_id = ?", (experiment_id,)).fetchone()
    assert row is not None
    return row


def _section(html: str, slug: str) -> str:
    marker = f"id='{slug}'"
    assert marker in html
    tail = html.split(marker, 1)[1]
    end = "</section>" if slug != "archived" else "</details>"
    return tail.split(end, 1)[0]
