import subprocess
import sys
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase13_refresh_orchestration import _job_json_command, _toml_array, _write_refresh_config
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def _add_job(ledger: Path, run_id: str, name: str, status: str, *extra: str) -> dict:
    return payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", name, "--status", status, *extra))


def test_workloop_json_markdown_and_read_only_default(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    _add_job(ledger, run_id, "train", "running")
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
            "Refresh Iris and collect evals.",
        )
    )

    before_notes = payload(run_fieldbook(ledger, "note", "list", "--entity-type", "experiment", "--entity-id", experiment_id))
    workloop = payload(run_fieldbook(ledger, "experiment", "workloop", experiment_id))
    assert set(workloop) >= {
        "experiment",
        "locality",
        "session",
        "runs",
        "jobs",
        "validations",
        "freshness",
        "notes",
        "doctor",
        "suggested_next_actions",
    }
    assert workloop["experiment"]["id"] == experiment_id
    assert workloop["runs"]["total"] == 1
    assert workloop["jobs"]["active"] == 1
    assert workloop["notes"]["open_next_actions"][0]["id"] == note["id"]
    assert isinstance(workloop["doctor"]["global_omitted_count"], int)
    assert all("command" in action for action in workloop["suggested_next_actions"])

    after_notes = payload(run_fieldbook(ledger, "note", "list", "--entity-type", "experiment", "--entity-id", experiment_id))
    assert after_notes == before_notes

    text = subprocess.run(
        [sys.executable, "-m", "fieldbook", "experiment", "workloop", experiment_id, "--ledger", str(ledger)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert text.startswith("# Fieldbook Workloop:")
    assert "Suggested Next Actions" in text


def test_workloop_checkpoint_body_sources_and_validation(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    body_file = tmp_path / "handoff.md"
    body_file.write_text("Manual handoff body.\n", encoding="utf-8")

    missing_checkpoint = run_fieldbook(
        ledger,
        "experiment",
        "workloop",
        experiment_id,
        "--body-file",
        str(body_file),
        check=False,
    )
    assert missing_checkpoint.returncode == ExitCode.VALIDATION_ERROR

    workloop = payload(
        run_fieldbook(
            ledger,
            "experiment",
            "workloop",
            experiment_id,
            "--handoff",
            "--body-file",
            str(body_file),
        )
    )
    assert workloop["handoff"]["note"]["note_type"] == "checkpoint"
    assert "Manual handoff body." in workloop["handoff"]["note"]["body"]
    assert "## Freshness" in workloop["handoff"]["note"]["body"]


def test_workloop_refresh_dry_run_apply_and_all_source_request(tmp_path: Path) -> None:
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
        command = {_toml_array(_job_json_command(job["id"], "running", "/iris/workloop"))}
        description = "Refresh Iris job summaries."
        """,
    )

    dry_run = payload(run_fieldbook(ledger, "experiment", "workloop", experiment_id, "--refresh", "iris_jobs"))
    assert dry_run["refresh"]["status"] == "dry_run"
    assert dry_run["refresh_request"] == {"all": False, "sources": ["iris_jobs"], "apply": False}
    assert dry_run["refresh"]["counts"]["update"]["jobs"] == 1
    assert dry_run["refresh"]["submission_resolutions"][0]["job_id"] == job["id"]
    assert dry_run["jobs"]["submission_unknown"][0]["id"] == job["id"]

    applied = payload(
        run_fieldbook(ledger, "experiment", "workloop", experiment_id, "--refresh", "iris_jobs", "--apply")
    )
    assert applied["refresh"]["status"] == "applied"
    assert applied["refresh_request"] == {"all": False, "sources": ["iris_jobs"], "apply": True}
    assert applied["jobs"]["active"] == 1
    assert payload(run_fieldbook(ledger, "job", "show", job["id"]))["status"] == "running"

    all_sources = payload(run_fieldbook(ledger, "experiment", "workloop", experiment_id, "--refresh-all"))
    assert all_sources["refresh_request"] == {"all": True, "sources": ["iris_jobs"], "apply": False}


def test_doctor_experiment_scope_and_workloop_omitted_global_count(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    target_id = create_experiment(ledger)
    other_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "other"))["id"]

    payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            target_id,
            "--check-name",
            "target.coverage",
            "--status",
            "fail",
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
            other_id,
            "--check-name",
            "other.coverage",
            "--status",
            "fail",
        )
    )

    scoped = payload(run_fieldbook(ledger, "doctor", "--experiment", target_id, "--check", "validations", check=False))
    assert scoped["issue_count"] == 1
    assert scoped["global_omitted_count"] >= 1
    assert scoped["issues"][0]["details"]["check_name"] == "target.coverage"

    workloop = payload(run_fieldbook(ledger, "experiment", "workloop", target_id))
    assert workloop["doctor"]["scoped_issue_count"] >= 1
    assert workloop["doctor"]["global_omitted_count"] >= 1
    assert any(
        issue["code"] == "validation.failed" and issue["details"]["check_name"] == "target.coverage"
        for issue in workloop["doctor"]["issues"]
    )


def test_experiment_cleanup_dry_run_and_apply(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    failed = _add_job(ledger, run_id, "train retry1", "failed")
    _add_job(ledger, run_id, "train retry2", "succeeded", "--retry-of", failed["id"])
    debug_note = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "job",
            "--entity-id",
            failed["id"],
            "--type",
            "debug",
            "--body",
            "Retry fixed this.",
        )
    )
    experiment_debug_note = payload(
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
            "Unrelated experiment investigation stays open.",
        )
    )

    dry_run = payload(run_fieldbook(ledger, "experiment", "cleanup", experiment_id))
    assert dry_run["applied"] is False
    assert dry_run["planned"]["debug_notes"][0]["id"] == debug_note["id"]
    assert dry_run["planned"]["validations"] == []

    note_before = payload(run_fieldbook(ledger, "note", "show", debug_note["id"]))
    assert note_before["status"] == "open"

    applied = payload(run_fieldbook(ledger, "experiment", "cleanup", experiment_id, "--apply"))
    assert applied["applied"] is True
    assert applied["counts"] == {"debug_notes_resolved": 1, "validations_archived": 0}
    assert applied["checkpoint"]["note_type"] == "checkpoint"

    note_after = payload(run_fieldbook(ledger, "note", "show", debug_note["id"]))
    assert note_after["status"] == "resolved"
    assert payload(run_fieldbook(ledger, "note", "show", experiment_debug_note["id"]))["status"] == "open"

    other_id = payload(run_fieldbook(ledger, "experiment", "create", "--name", "other-cleanup"))["id"]
    other_note = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            other_id,
            "--type",
            "debug",
            "--body",
            "Do not resolve from another cleanup.",
        )
    )
    payload(run_fieldbook(ledger, "experiment", "cleanup", experiment_id, "--apply"))
    assert payload(run_fieldbook(ledger, "note", "show", other_note["id"]))["status"] == "open"


def test_cleanup_apply_rejects_archived_without_mutation(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    failed = _add_job(ledger, run_id, "archived retry1", "failed")
    _add_job(ledger, run_id, "archived retry2", "succeeded", "--retry-of", failed["id"])
    debug_note = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "job",
            "--entity-id",
            failed["id"],
            "--type",
            "debug",
            "--body",
            "Archived cleanup must not partially apply.",
        )
    )
    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))

    rejected = run_fieldbook(ledger, "experiment", "cleanup", experiment_id, "--apply", check=False)
    assert rejected.returncode == ExitCode.VALIDATION_ERROR
    assert payload(run_fieldbook(ledger, "note", "show", debug_note["id"]))["status"] == "open"
    checkpoints = payload(run_fieldbook(ledger, "note", "list", "--entity-type", "experiment", "--entity-id", experiment_id))
    assert [note for note in checkpoints if note["note_type"] == "checkpoint"] == []


def test_workloop_checkpoint_rejects_archived_before_refresh_apply(tmp_path: Path) -> None:
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
            "archived submit",
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
        command = {_toml_array(_job_json_command(job["id"], "running", "/iris/archived"))}
        description = "Refresh Iris job summaries."
        """,
    )
    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))

    read_only = payload(run_fieldbook(ledger, "experiment", "workloop", experiment_id))
    assert read_only["experiment"]["deleted_at"] is not None

    rejected = run_fieldbook(
        ledger,
        "experiment",
        "workloop",
        experiment_id,
        "--refresh",
        "iris_jobs",
        "--apply",
        "--handoff",
        check=False,
    )
    assert rejected.returncode == ExitCode.VALIDATION_ERROR
    assert payload(run_fieldbook(ledger, "job", "show", job["id"]))["status"] == "unknown_submit"


def test_docs_and_skill_prefer_workloop() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / ".codex" / "skills" / "fieldbook" / "SKILL.md").read_text(encoding="utf-8")

    assert 'fieldbook experiment workloop "$EXP_ID" --json' in readme
    assert "workloop` is the preferred one-command active-experiment resume surface" in readme
    assert 'fieldbook experiment workloop "$EXP_ID" --json' in skill
    assert "Start active-experiment work with\n  `experiment workloop`" in skill
