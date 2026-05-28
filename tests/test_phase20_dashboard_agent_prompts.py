import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fieldbook.cli import _is_read_only, build_parser
from fieldbook.dashboard import dashboard_routes, render_experiment_detail, render_experiment_index
from fieldbook.errors import ExitCode
from fieldbook.prompts import (
    FORBIDDEN_PROMPT_SUBSTRINGS,
    PROMPT_CATALOG_VERSION,
    _validate_prompt_body,
    prompt_actions,
    prompt_catalog,
    prompt_queries,
)
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


EXPECTED_ACTIONS = {
    "refresh-external-state",
    "resolve-failed-jobs",
    "fix-failing-validations",
    "write-handoff",
    "resolve-stale-leases",
    "review-open-notes",
    "review-outputs",
}

EXPECTED_ATTENTION_ACTIONS = EXPECTED_ACTIONS - {"review-outputs"}


def test_prompt_catalog_is_closed_and_complete() -> None:
    catalog = prompt_catalog()
    assert {action["action_id"] for action in catalog["actions"]} == EXPECTED_ACTIONS
    assert catalog["catalog_version"] == PROMPT_CATALOG_VERSION
    for action in catalog["actions"]:
        assert action["title"]
        assert action["description"]
        assert action["entry_command"]
        assert action["constraint"]


def test_prompt_cli_actions_and_build_contract(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _seed_attention_experiment(ledger)

    actions = payload(run_fieldbook(ledger, "prompt", "actions", experiment_id))
    assert {action["action_id"] for action in actions["actions"]} == EXPECTED_ATTENTION_ACTIONS

    for action_id in EXPECTED_ATTENTION_ACTIONS:
        built = payload(run_fieldbook(ledger, "prompt", "build", action_id, experiment_id))
        assert built["envelope_version"] == 1
        assert built["catalog_version"] == PROMPT_CATALOG_VERSION
        assert built["action_id"] == action_id
        assert built["applicable"] is True
        assert built["experiment_id"] == experiment_id
        assert built["experiment_name"] in built["body"]
        assert experiment_id in built["body"]
        assert "Fieldbook skill" in built["body"]
        assert built["issue_summary"] in built["body"]
        assert built["entry_command"] in built["body"]
        assert len(built["body"]) <= 1500
        assert not any(flag in built["body"] for flag in FORBIDDEN_PROMPT_SUBSTRINGS)
        fieldbook_lines = [line for line in built["body"].splitlines() if line.strip().startswith("fieldbook ")]
        assert fieldbook_lines == [built["entry_command"]]


def test_prompt_text_output_and_inapplicable_rejection(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    create_run(ledger, experiment_id)

    text = subprocess.run(
        [
            sys.executable,
            "-m",
            "fieldbook",
            "prompt",
            "build",
            "write-handoff",
            experiment_id,
            "--ledger",
            str(ledger),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert text.returncode == ExitCode.SUCCESS
    assert "Fieldbook skill" in text.stdout
    assert "fieldbook experiment workloop" in text.stdout

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
            "--title",
            "checkpoint",
            "--body",
            "Current state is up to date.",
        )
    )
    result = run_fieldbook(ledger, "prompt", "build", "write-handoff", experiment_id, check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "not applicable" in result.stderr


def test_prompt_safety_rejects_secrets(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    secret_name = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz"
    experiment_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", secret_name))["id"]
    run_id = create_run(ledger, experiment_id)
    payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "train", "--status", "running"))

    result = run_fieldbook(ledger, "prompt", "build", "refresh-external-state", experiment_id, check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "suspected secret" in result.stderr


def test_prompt_safety_rejects_length_and_skill_body_overlap(tmp_path: Path) -> None:
    long_body = "x" * 1501
    try:
        _validate_prompt_body(long_body, skill_path=None)
    except Exception as exc:
        assert "1500" in str(exc)
    else:
        raise AssertionError("expected long prompt body to be rejected")

    copied = "A" * 201
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(f"prefix {copied} suffix", encoding="utf-8")
    try:
        _validate_prompt_body(copied, skill_path=skill_path)
    except Exception as exc:
        assert "skill" in str(exc)
    else:
        raise AssertionError("expected skill overlap to be rejected")


def test_prompt_commands_are_read_only_and_stable_view_backed() -> None:
    parser = build_parser()
    for argv in (
        ["prompt", "list"],
        ["prompt", "actions", "exp_123"],
        ["prompt", "build", "write-handoff", "exp_123"],
    ):
        args = parser.parse_args(argv)
        assert _is_read_only(args) is True

    for name, query in prompt_queries().items():
        lowered = " ".join(query.lower().split())
        assert "_v1" in lowered, name
        assert " from experiments" not in lowered, name
        assert " from jobs" not in lowered, name
        assert " from notes" not in lowered, name
        assert " from artifacts" not in lowered, name


def test_dashboard_index_uses_category_sidebar_and_collapses_archived(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    active_id = create_experiment(ledger)
    attention_id = _seed_attention_experiment(ledger, name="attention")
    archived_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "archived"))["id"]
    payload(run_fieldbook(ledger, "experiment", "archive", archived_id))

    html = render_experiment_index(ledger)
    assert active_id in html
    assert attention_id in html
    assert archived_id in html
    assert "Needs attention" in html
    assert "Open" in html
    assert "Archived" in html
    assert "status-chip" in html
    assert "<th>experiment_id</th>" not in html
    assert "experiment-sidebar" in html
    assert "href='#needs-attention'" in html
    assert "<details class='group archived-group'" in html
    assert "<details class='group archived-group' open>" not in html
    assert "fixed-left" not in html.lower()


def test_dashboard_detail_schema_aware_prompt_cards_no_raw_tables(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _seed_attention_experiment(ledger)
    other_id = create_experiment(ledger)

    html = render_experiment_detail(ledger, experiment_id, tab="runs")
    for section in (
        "Run Progress",
    ):
        assert section in html
    assert '<nav class="tab-bar"' in html
    assert "section-anchors" not in html
    assert "tab=runs" in html
    assert "tab=jobs" in html
    assert "<h2>Job Recovery</h2>" not in html
    assert "fieldbook refresh run" not in html
    assert "class='command'" not in html
    assert "<th>experiment_id</th>" not in html
    assert "experiment-sidebar" in html
    assert other_id in html
    assert f"href='/experiment?id={experiment_id}' aria-current='page'" in html
    assert f"href='/experiment?id={other_id}' aria-current='page'" not in html
    assert "overflow-wrap:anywhere" in html
    assert "min-width:0" in html

    overview_html = render_experiment_detail(ledger, experiment_id, tab="overview")
    assert "Preview agent instruction" in overview_html
    assert "Copy instruction" in overview_html
    assert "data-copy-target='prompt-copy-" in overview_html
    assert "navigator.clipboard.writeText" in overview_html
    assert "font-size:14px" in overview_html
    assert "<details" in overview_html
    assert "<h2>Run Progress</h2>" not in overview_html

    notes_html = render_experiment_detail(ledger, experiment_id, tab="notes")
    assert "<h2>Notes</h2>" in notes_html
    assert "<h2>Artifacts</h2>" not in notes_html
    assert "next-action" in notes_html

    validations_html = render_experiment_detail(ledger, experiment_id, tab="validations")
    assert "metrics.coverage" in validations_html

    leases_html = render_experiment_detail(ledger, experiment_id, tab="leases")
    assert "status-chip stale" in leases_html


def test_dashboard_detail_tabs_query_only_active_tab(tmp_path: Path, monkeypatch) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = _seed_attention_experiment(ledger)
    calls = []

    original_fetch = __import__("fieldbook.dashboard", fromlist=["_fetch_rows"])._fetch_rows

    def tracking_fetch(conn, query_name, experiment_id_arg):
        calls.append(query_name)
        return original_fetch(conn, query_name, experiment_id_arg)

    monkeypatch.setattr("fieldbook.dashboard._fetch_rows", tracking_fetch)
    html = render_experiment_detail(ledger, experiment_id, tab="runs")

    assert "Run Progress" in html
    assert calls == ["runs"]


def test_dashboard_routes_remain_get_only_prompt_cards_are_not_send_routes() -> None:
    assert {route["method"] for route in dashboard_routes()} == {"GET"}
    assert not any("send" in route["path"] or "prompt" in route["path"] for route in dashboard_routes())


def test_docs_and_skill_describe_dashboard_prompt_cards() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / ".codex" / "skills" / "fieldbook" / "SKILL.md").read_text(encoding="utf-8")

    assert "copyable agent instruction" in readme
    assert "does not send prompts" in readme
    assert "fieldbook prompt actions" in skill
    assert "human-to-agent handoff" in skill


def test_experiment_handoff_command_creates_agent_handoff_surface(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    create_run(ledger, experiment_id)

    handoff = payload(run_fieldbook(ledger, "experiment", "handoff", experiment_id, "--body", "Ready for next agent."))
    assert handoff["note"]["note_type"] == "checkpoint"
    assert handoff["note"]["title"] == "Experiment handoff"
    assert "Handoff status" in handoff["note"]["body"]

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["freshness"]["handoff_status"] == "current"
    assert status["freshness"]["last_handoff_at"] == handoff["note"]["created_at"]

    html = render_experiment_detail(ledger, experiment_id, tab="freshness")
    assert "Last handoff" in html
    assert "Last checkpoint" not in html


def _seed_attention_experiment(ledger: Path, *, name: str = "attention-experiment") -> str:
    experiment_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", name))["id"]
    run_id = create_run(ledger, experiment_id)
    failed = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "failed", "--status", "failed"))
    payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            run_id,
            "--name",
            "running",
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
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "metrics.coverage",
            "--status",
            "fail",
            "--expected-value",
            "all metrics",
            "--measured-value",
            "missing gsm8k",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "lease",
            "claim",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--owner",
            "codex",
        )
    )
    with sqlite3.connect(ledger) as conn:
        stale_heartbeat = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE leases SET heartbeat_at = ? WHERE entity_type = 'experiment' AND entity_id = ?",
            (stale_heartbeat, experiment_id),
        )
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
            "next-action",
            "--title",
            "Fix remaining failures",
            "--body",
            "body line 1\nbody line 2 should stay in preview only",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--job",
            failed["id"],
            "--type",
            "report",
            "--uri",
            "https://example.com/report",
        )
    )
    return experiment_id
