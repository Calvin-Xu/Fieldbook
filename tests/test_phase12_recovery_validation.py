import json
import sqlite3
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def test_retry_lineage_submission_states_and_readiness(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)

    failed = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            run_id,
            "--name",
            "parity retry1",
            "--status",
            "failed",
            "--failure-reason",
            "bundle fetch reset",
        )
    )
    retry = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            run_id,
            "--name",
            "parity retry2",
            "--status",
            "submitting",
            "--retry-of",
            failed["id"],
        )
    )
    assert retry["retry_of"] == failed["id"]

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["ready"]["is_ready"] is False
    assert status["ready"]["has_active_blockers"] is False
    assert status["ready"]["active_job_count"] == 1
    assert status["ready"]["recovery_in_progress_count"] == 1
    assert status["ready"]["submission_uncertainty_count"] == 1
    assert [job["id"] for job in status["blocking_failed_jobs"]] == []
    assert [job["id"] for job in status["submission_in_progress_jobs"]] == [retry["id"]]
    assert [job["id"] for job in status["recovery_in_progress_failed_jobs"]] == [failed["id"]]
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        blocker_rows = conn.execute(
            "SELECT blocker_type, entity_id FROM v_experiment_blockers_v1 WHERE experiment_id = ? ORDER BY blocker_type",
            (experiment_id,),
        ).fetchall()
    finally:
        conn.close()
    assert [(row["blocker_type"], row["entity_id"]) for row in blocker_rows] == [
        ("submission_in_progress", retry["id"])
    ]

    unknown = payload(
        run_fieldbook(
            ledger,
            "job",
            "update-status",
            retry["id"],
            "--status",
            "unknown_submit",
            "--failure-reason",
            "controller timeout before acknowledgment",
        )
    )
    assert unknown["status"] == "unknown_submit"
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert [job["id"] for job in status["submission_unknown_jobs"]] == [retry["id"]]
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        blocker_rows = conn.execute(
            "SELECT blocker_type, entity_id FROM v_experiment_blockers_v1 WHERE experiment_id = ? ORDER BY blocker_type",
            (experiment_id,),
        ).fetchall()
    finally:
        conn.close()
    assert [(row["blocker_type"], row["entity_id"]) for row in blocker_rows] == [
        ("submission_unknown", retry["id"])
    ]

    acknowledged = payload(
        run_fieldbook(
            ledger,
            "job",
            "update-status",
            retry["id"],
            "--status",
            "queued",
            "--external-system",
            "iris",
            "--external-id",
            "/calvinxu/example-retry",
        )
    )
    assert acknowledged["status"] == "queued"
    assert acknowledged["external_system"] == "iris"
    assert acknowledged["external_id"] == "/calvinxu/example-retry"
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["submission_unknown_jobs"] == []

    succeeded = payload(run_fieldbook(ledger, "job", "update-status", retry["id"], "--status", "succeeded"))
    assert succeeded["status"] == "succeeded"
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["ready"]["is_ready"] is True
    assert status["ready"]["has_active_blockers"] is False
    assert status["ready"]["recovered_failed_count"] == 1
    assert [job["id"] for job in status["recovered_failed_jobs"]] == [failed["id"]]
    assert [job["id"] for job in status["failed_jobs"]] == [failed["id"]]

    missing = run_fieldbook(
        ledger,
        "job",
        "add",
        "--run",
        run_id,
        "--name",
        "bad retry",
        "--status",
        "queued",
        "--retry-of",
        "job_missing",
        check=False,
    )
    assert missing.returncode == ExitCode.VALIDATION_ERROR
    assert "retry_of" in missing.stderr

    self_link = run_fieldbook(
        ledger,
        "job",
        "link-retry",
        failed["id"],
        "--retry-of",
        failed["id"],
        check=False,
    )
    assert self_link.returncode == ExitCode.VALIDATION_ERROR

    cycle = run_fieldbook(
        ledger,
        "job",
        "link-retry",
        failed["id"],
        "--retry-of",
        retry["id"],
        check=False,
    )
    assert cycle.returncode == ExitCode.VALIDATION_ERROR
    assert "cycle" in cycle.stderr


def test_validation_cli_idempotency_status_and_report_artifacts(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job = payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", "collect", "--status", "succeeded"))
    report = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "validation-report",
            "--uri",
            "reports/coverage.md",
        )
    )
    session = payload(
        run_fieldbook(ledger, "session", "start", "--experiment", experiment_id, "--agent", "codex")
    )["session"]

    validation = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "matrix.coverage.rollup",
            "--status",
            "fail",
            "--expected-value",
            "262 rows",
            "--measured-value",
            "261 rows",
            "--details-json",
            '{"missing": ["lm_eval/piqa/choice_logprob"]}',
            "--source-artifact",
            report["id"],
            "--source-job",
            job["id"],
            "--attr",
            "validation.blocking=true",
        )
    )
    assert validation["id"].startswith("val_")
    assert validation["status"] == "fail"
    assert validation["details"] == {"missing": ["lm_eval/piqa/choice_logprob"]}
    assert validation["source_artifact_id"] == report["id"]
    assert validation["source_job_id"] == job["id"]
    assert validation["session_id"] == session["id"]

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["ready"]["has_active_blockers"] is True
    assert status["validations"]["status"] == "fail"
    assert [row["id"] for row in status["validations"]["failed"]] == [validation["id"]]
    context = payload(run_fieldbook(ledger, "experiment", "context", experiment_id))
    assert context["ready"]["has_active_blockers"] is True
    assert context["validations"]["total"] == 1

    updated = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "matrix.coverage.rollup",
            "--status",
            "pass",
            "--expected-value",
            "262 rows",
            "--measured-value",
            "262 rows",
            "--details-json",
            '{"missing": []}',
        )
    )
    assert updated["id"] == validation["id"]
    assert updated["status"] == "pass"

    rows = payload(run_fieldbook(ledger, "validation", "list", "--entity-type", "experiment", "--entity-id", experiment_id))
    assert [row["id"] for row in rows] == [validation["id"]]
    shown = payload(run_fieldbook(ledger, "validation", "show", validation["id"]))
    assert shown["details"] == {"missing": []}

    invalid = run_fieldbook(
        ledger,
        "validation",
        "add",
        "--entity-type",
        "experiment",
        "--entity-id",
        experiment_id,
        "--check-name",
        "bad.status",
        "--status",
        "ok",
        check=False,
    )
    assert invalid.returncode == ExitCode.VALIDATION_ERROR

    unknown_blocking = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "freshness.external",
            "--status",
            "unknown",
            "--attr",
            "validation.blocking=true",
        )
    )
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert [row["id"] for row in status["validations"]["unknown_blocking"]] == [unknown_blocking["id"]]

    archived = payload(run_fieldbook(ledger, "validation", "archive", validation["id"]))
    assert archived["deleted_at"] is not None


def test_archived_experiment_errata_notes_artifacts_and_validations(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
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
            str(tmp_path / "report.md"),
        )
    )
    validation = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "matrix.coverage.rollup",
            "--status",
            "pass",
        )
    )
    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))

    normal_note = run_fieldbook(
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
        "late note without errata",
        check=False,
    )
    assert normal_note.returncode == ExitCode.VALIDATION_ERROR
    assert "errata" in normal_note.stderr

    erratum_note = payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "run",
            "--entity-id",
            run_id,
            "--type",
            "research",
            "--body",
            "post-archive correction",
            "--errata",
        )
    )
    assert erratum_note["attrs"]["fieldbook.erratum"] is True
    assert "fieldbook.erratum_at" in erratum_note["attrs"]

    normal_artifact = run_fieldbook(
        ledger,
        "artifact",
        "add",
        "--experiment",
        experiment_id,
        "--type",
        "report",
        "--uri",
        str(tmp_path / "new-report.md"),
        check=False,
    )
    assert normal_artifact.returncode == ExitCode.VALIDATION_ERROR

    replacement_artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "report",
            "--uri",
            artifact["uri"],
            "--errata",
        )
    )
    assert replacement_artifact["id"] != artifact["id"]
    assert replacement_artifact["attrs"]["fieldbook.replaces"] == artifact["id"]
    assert replacement_artifact["attrs"]["fieldbook.erratum"] is True
    assert payload(run_fieldbook(ledger, "artifact", "show", artifact["id"]))["deleted_at"] is not None

    normal_validation = run_fieldbook(
        ledger,
        "validation",
        "add",
        "--entity-type",
        "experiment",
        "--entity-id",
        experiment_id,
        "--check-name",
        "matrix.coverage.rollup",
        "--status",
        "warning",
        check=False,
    )
    assert normal_validation.returncode == ExitCode.VALIDATION_ERROR

    replacement_validation = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "matrix.coverage.rollup",
            "--status",
            "warning",
            "--errata",
        )
    )
    assert replacement_validation["id"] != validation["id"]
    assert replacement_validation["attrs"]["fieldbook.replaces"] == validation["id"]
    assert replacement_validation["attrs"]["fieldbook.erratum"] is True
    assert payload(run_fieldbook(ledger, "validation", "show", validation["id"]))["deleted_at"] is not None

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["experiment"]["deleted_at"] is not None
    assert status["historical"]["erratum_count"] == 3
    assert {row["entity_type"] for row in status["historical"]["recent_errata"]} == {"artifact", "note", "validation"}


def test_reconcile_errata_required_for_archived_targets(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
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
            str(tmp_path / "coverage.md"),
        )
    )
    validation = payload(
        run_fieldbook(
            ledger,
            "validation",
            "add",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--check-name",
            "matrix.coverage.rollup",
            "--status",
            "pass",
        )
    )
    session_id = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id))["session"]["id"]
    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "late note",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rejected = run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply", check=False)
    assert rejected.returncode == ExitCode.VALIDATION_ERROR
    assert "_errata" in rejected.stderr

    manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "late note",
                        "_errata": True,
                    }
                ],
                "metrics": [
                    {
                        "run_id": "run_missing",
                        "metric_name": "eval/bpb",
                        "value": 1.0,
                        "_errata": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    metric_errata = run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply", check=False)
    assert metric_errata.returncode == ExitCode.VALIDATION_ERROR
    assert "_errata" in metric_errata.stderr

    manifest.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "note_type": "research",
                        "body": "late note",
                        "_errata": True,
                    }
                ],
                "artifacts": [
                    {
                        "experiment_id": experiment_id,
                        "type": "report",
                        "uri": artifact["uri"],
                        "_errata": True,
                    }
                ],
                "validations": [
                    {
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "check_name": "matrix.coverage.rollup",
                        "status": "warning",
                        "_errata": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    applied = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply"))
    assert applied["counts"]["insert"]["notes"] == 1
    assert applied["counts"]["insert"]["artifacts"] == 1
    assert applied["counts"]["archive"]["artifacts"] == 1
    assert applied["counts"]["insert"]["validations"] == 1
    assert applied["counts"]["archive"]["validations"] == 1
    note_id = payload(run_fieldbook(ledger, "note", "list", "--entity-type", "experiment", "--entity-id", experiment_id))[0]["id"]
    note = payload(run_fieldbook(ledger, "note", "show", note_id))
    assert note["attrs"]["fieldbook.erratum"] is True
    assert note["attrs"]["fieldbook.erratum_session_id"] == session_id
    replaced_artifact_id = payload(run_fieldbook(ledger, "artifact", "list", "--experiment", experiment_id))[0]["id"]
    replaced_artifact = payload(run_fieldbook(ledger, "artifact", "show", replaced_artifact_id))
    assert replaced_artifact["id"] != artifact["id"]
    assert replaced_artifact["attrs"]["fieldbook.replaces"] == artifact["id"]
    assert replaced_artifact["attrs"]["fieldbook.erratum_session_id"] == session_id
    assert payload(run_fieldbook(ledger, "artifact", "show", artifact["id"]))["deleted_at"] is not None
    replaced_validation = payload(run_fieldbook(ledger, "validation", "list", "--entity-type", "experiment", "--entity-id", experiment_id))[0]
    assert replaced_validation["id"] != validation["id"]
    assert replaced_validation["attrs"]["fieldbook.replaces"] == validation["id"]
    assert replaced_validation["attrs"]["fieldbook.erratum_session_id"] == session_id


def test_reconcile_artifact_errata_does_not_replace_other_experiment_uri(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    archived_experiment_id = create_experiment(ledger)
    active_experiment_id = create_experiment(ledger)
    artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            active_experiment_id,
            "--type",
            "report",
            "--uri",
            str(tmp_path / "shared.md"),
        )
    )
    payload(run_fieldbook(ledger, "experiment", "archive", archived_experiment_id))

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "experiment_id": archived_experiment_id,
                        "type": "report",
                        "uri": artifact["uri"],
                        "_errata": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply", check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "outside the errata target experiments" in result.stderr
    assert payload(run_fieldbook(ledger, "artifact", "show", artifact["id"]))["deleted_at"] is None


def test_reconcile_retry_lineage_and_validations_are_atomic(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    acknowledged_submission = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "ambiguous acknowledged",
            "--status",
            "unknown_submit",
        )
    )
    missing_submission = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "ambiguous missing",
            "--status",
            "unknown_submit",
        )
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": acknowledged_submission["id"],
                        "status": "queued",
                        "external_system": "iris",
                        "external_id": "/calvinxu/acknowledged",
                    },
                    {
                        "id": missing_submission["id"],
                        "status": "failed",
                        "failure_reason": "submission was never acknowledged",
                    },
                    {"id": "job_failed_manifest", "name": "failed", "status": "failed"},
                    {
                        "id": "job_retry_manifest",
                        "name": "retry",
                        "status": "queued",
                        "retry_of": "job_failed_manifest",
                    },
                ],
                "validations": [
                    {
                        "id": "val_manifest",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "check_name": "coverage.rollup",
                        "status": "warning",
                        "expected_value": "all rows",
                        "measured_value": "pending retry",
                        "details": {"pending": 1},
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
            "--experiment",
            experiment_id,
            "--path",
            str(manifest),
            "--apply",
        )
    )
    assert result["counts"]["insert"]["jobs"] == 2
    assert result["counts"]["insert"]["validations"] == 1

    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        retry = conn.execute("SELECT retry_of FROM jobs WHERE id = 'job_retry_manifest'").fetchone()
        validation = conn.execute("SELECT * FROM v_validations_v1 WHERE validation_id = 'val_manifest'").fetchone()
        recovery = conn.execute(
            "SELECT retry_state FROM v_jobs_with_recovery_v1 WHERE job_id = 'job_failed_manifest'"
        ).fetchone()
        acknowledged = conn.execute(
            "SELECT status, external_id FROM jobs WHERE id = ?", (acknowledged_submission["id"],)
        ).fetchone()
        missing = conn.execute("SELECT status, failure_reason FROM jobs WHERE id = ?", (missing_submission["id"],)).fetchone()
        blockers = conn.execute(
            "SELECT blocker_type, entity_id FROM v_experiment_blockers_v1 WHERE experiment_id = ? ORDER BY blocker_type",
            (experiment_id,),
        ).fetchall()
    finally:
        conn.close()
    assert retry["retry_of"] == "job_failed_manifest"
    assert validation["status"] == "warning"
    assert recovery["retry_state"] == "recovery_in_progress"
    assert acknowledged["status"] == "queued"
    assert acknowledged["external_id"] == "/calvinxu/acknowledged"
    assert missing["status"] == "failed"
    assert missing["failure_reason"] == "submission was never acknowledged"
    assert [(row["blocker_type"], row["entity_id"]) for row in blockers] == [
        ("blocking_failed_job", missing_submission["id"])
    ]

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "jobs": [{"id": "job_bad_retry", "status": "queued", "retry_of": "job_missing"}],
                "validations": [
                    {
                        "id": "val_should_not_insert",
                        "entity_type": "experiment",
                        "entity_id": experiment_id,
                        "check_name": "should.not.insert",
                        "status": "pass",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    failed = run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--experiment",
        experiment_id,
        "--path",
        str(invalid),
        "--apply",
        check=False,
    )
    assert failed.returncode == ExitCode.VALIDATION_ERROR
    conn = sqlite3.connect(ledger)
    try:
        row = conn.execute("SELECT id FROM validations WHERE id = 'val_should_not_insert'").fetchone()
    finally:
        conn.close()
    assert row is None


def test_doctor_reports_recovery_validation_and_submission_issues(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    failed = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "failed",
            "--status",
            "failed",
        )
    )
    retry = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "retry",
            "--status",
            "unknown_submit",
            "--retry-of",
            failed["id"],
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
            "coverage.rollup",
            "--status",
            "fail",
        )
    )
    recovered = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "recovered failed",
            "--status",
            "failed",
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "successful retry",
            "--status",
            "succeeded",
            "--retry-of",
            recovered["id"],
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "note",
            "add",
            "--entity-type",
            "job",
            "--entity-id",
            recovered["id"],
            "--type",
            "debug",
            "--body",
            "Retry succeeded; resolve this note after reviewing logs.",
        )
    )
    first_loop_job = payload(
        run_fieldbook(ledger, "job", "add", "--experiment", experiment_id, "--name", "loop root", "--status", "failed")
    )
    previous = first_loop_job["id"]
    for index in range(4):
        child = payload(
            run_fieldbook(
                ledger,
                "job",
                "add",
                "--experiment",
                experiment_id,
                "--name",
                f"loop retry {index}",
                "--status",
                "failed",
                "--retry-of",
                previous,
            )
        )
        previous = child["id"]
    secret_job = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            "secret command",
            "--status",
            "planned",
            "--command",
            "OPENAI_API_KEY=sk-example12345678901234567890 uv run task",
        )
    )
    cycle_a = payload(
        run_fieldbook(ledger, "job", "add", "--experiment", experiment_id, "--name", "cycle a", "--status", "failed")
    )
    cycle_b = payload(
        run_fieldbook(ledger, "job", "add", "--experiment", experiment_id, "--name", "cycle b", "--status", "failed")
    )
    missing_target = payload(
        run_fieldbook(ledger, "job", "add", "--experiment", experiment_id, "--name", "missing target", "--status", "queued")
    )

    conn = sqlite3.connect(ledger)
    try:
        conn.execute("UPDATE jobs SET updated_at = '2026-01-01T00:00:00Z' WHERE id = ?", (retry["id"],))
        conn.execute("UPDATE jobs SET retry_of = ? WHERE id = ?", (cycle_b["id"], cycle_a["id"]))
        conn.execute("UPDATE jobs SET retry_of = ? WHERE id = ?", (cycle_a["id"], cycle_b["id"]))
        conn.execute("UPDATE jobs SET retry_of = 'job_missing' WHERE id = ?", (missing_target["id"],))
        conn.commit()
    finally:
        conn.close()

    doctor = payload(
        run_fieldbook(
            ledger,
            "doctor",
            "--stale-unknown-submit-hours",
            "1",
            "--retry-loop-threshold",
            "2",
            check=False,
        )
    )
    codes = {issue["code"] for issue in doctor["issues"]}
    assert "job_submission.unknown_stale" in codes
    assert "validation.failed" in codes
    assert "job_retry.recovered_debug_open" in codes
    assert "job_retry.loop" in codes
    assert "job_retry.cycle" in codes
    assert "job_retry.missing_target" in codes
    assert "privacy.secret_pattern" in codes
    assert any(issue["entity_id"] == secret_job["id"] for issue in doctor["issues"] if issue["code"] == "privacy.secret_pattern")
