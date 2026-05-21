import json
import sqlite3
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import init_ledger, payload, run_fieldbook


def create_named_experiment(ledger: Path, name: str, *attrs: str) -> str:
    args = ["experiment", "create", "--name", name]
    for attr in attrs:
        args.extend(["--attr", attr])
    return payload(run_fieldbook(ledger, *args))["id"]


def add_run(ledger: Path, experiment_id: str, name: str, key: str, *, kind: str = "datapoint") -> dict:
    return payload(
        run_fieldbook(
            ledger,
            "run",
            "add",
            "--name",
            name,
            "--experiment",
            experiment_id,
            "--idempotency-key",
            key,
            "--kind",
            kind,
        )
    )


def add_job(ledger: Path, experiment_id: str, name: str, *, status: str = "planned") -> dict:
    return payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--experiment",
            experiment_id,
            "--name",
            name,
            "--status",
            status,
        )
    )


def link_job_run(
    ledger: Path,
    *,
    job_id: str,
    run_id: str,
    role: str,
    status: str,
    failure_reason: str | None = None,
) -> dict:
    args = [
        "run",
        "link-job",
        "--run",
        run_id,
        "--job",
        job_id,
        "--role",
        role,
        "--status",
        status,
    ]
    if failure_reason:
        args.extend(["--failure-reason", failure_reason])
    return payload(run_fieldbook(ledger, *args))


def test_run_idempotency_kind_and_cli_validation(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(ledger, "phase15-a")
    other_experiment_id = create_named_experiment(ledger, "phase15-b")

    created = add_run(ledger, experiment_id, "candidate-a", "phase15.candidate-a", kind="external")
    assert created["id"].startswith("run_")
    assert created["experiment_id"] == experiment_id
    assert created["experiment_ids"] == [experiment_id]
    assert created["idempotency_key"] == "phase15.candidate-a"
    assert created["kind"] == "external"
    assert created["existed"] is False

    reused = payload(
        run_fieldbook(
            ledger,
            "run",
            "add",
            "--name",
            "candidate-a-renamed",
            "--experiment",
            experiment_id,
            "--idempotency-key",
            "phase15.candidate-a",
            "--kind",
            "datapoint",
        )
    )
    assert reused["id"] == created["id"]
    assert reused["name"] == "candidate-a"
    assert reused["kind"] == "external"
    assert reused["existed"] is True

    same_key_other_experiment = add_run(ledger, other_experiment_id, "candidate-a", "phase15.candidate-a")
    assert same_key_other_experiment["id"] != created["id"]
    assert same_key_other_experiment["experiment_id"] == other_experiment_id

    invalid_kind = run_fieldbook(
        ledger,
        "run",
        "add",
        "--name",
        "bad-kind",
        "--experiment",
        experiment_id,
        "--kind",
        "baseline",
        check=False,
    )
    assert invalid_kind.returncode == ExitCode.VALIDATION_ERROR

    invalid_key = run_fieldbook(
        ledger,
        "run",
        "add",
        "--name",
        "bad-key",
        "--experiment",
        experiment_id,
        "--idempotency-key",
        "Bad Key",
        check=False,
    )
    assert invalid_key.returncode == ExitCode.VALIDATION_ERROR


def test_job_runs_many_to_many_and_legacy_job_run_backfill(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(ledger, "phase15-fanout")
    run_a = add_run(ledger, experiment_id, "candidate-a", "phase15.a")
    run_b = add_run(ledger, experiment_id, "candidate-b", "phase15.b")
    parent = add_job(ledger, experiment_id, "iris-parent", status="succeeded")

    edge_a = link_job_run(ledger, job_id=parent["id"], run_id=run_a["id"], role="train", status="succeeded")
    edge_b = link_job_run(
        ledger,
        job_id=parent["id"],
        run_id=run_b["id"],
        role="train",
        status="failed",
        failure_reason="child task failed",
    )
    assert edge_a["job_id"] == parent["id"]
    assert edge_a["run_id"] == run_a["id"]
    assert edge_a["role"] == "train"
    assert edge_a["status"] == "succeeded"
    assert edge_b["failure_reason"] == "child task failed"

    legacy = payload(
        run_fieldbook(
            ledger,
            "job",
            "add",
            "--run",
            run_a["id"],
            "--name",
            "legacy-single-run",
            "--status",
            "running",
        )
    )
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT job_id, run_id, role, status FROM v_job_runs_v1 WHERE job_id IN (?, ?) ORDER BY job_id, run_id",
            (parent["id"], legacy["id"]),
        ).fetchall()
    finally:
        conn.close()
    assert [dict(row) for row in rows] == [
        {"job_id": parent["id"], "run_id": run_a["id"], "role": "train", "status": "succeeded"},
        {"job_id": parent["id"], "run_id": run_b["id"], "role": "train", "status": "failed"},
        {"job_id": legacy["id"], "run_id": run_a["id"], "role": "other", "status": "running"},
    ]

    bad_role = run_fieldbook(
        ledger,
        "run",
        "link-job",
        "--run",
        run_a["id"],
        "--job",
        parent["id"],
        "--role",
        "finetune",
        "--status",
        "planned",
        check=False,
    )
    assert bad_role.returncode == ExitCode.VALIDATION_ERROR

    bad_status = run_fieldbook(
        ledger,
        "run",
        "link-job",
        "--run",
        run_a["id"],
        "--job",
        parent["id"],
        "--role",
        "eval",
        "--status",
        "done",
        check=False,
    )
    assert bad_status.returncode == ExitCode.VALIDATION_ERROR


def test_reconcile_runs_and_job_runs_are_idempotent_with_forward_references(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(ledger, "phase15-reconcile")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "run_phase15_a",
                        "name": "candidate-a",
                        "experiment_id": experiment_id,
                        "idempotency_key": "phase15.reconcile-a",
                        "kind": "datapoint",
                    },
                    {
                        "id": "run_phase15_b",
                        "name": "candidate-b",
                        "experiment_id": experiment_id,
                        "idempotency_key": "phase15.reconcile-b",
                        "kind": "external",
                    },
                ],
                "jobs": [
                    {
                        "id": "job_phase15_parent",
                        "experiment_id": experiment_id,
                        "name": "iris-parent",
                        "status": "unknown_submit",
                    }
                ],
                "job_runs": [
                    {
                        "job_id": "job_phase15_parent",
                        "run_id": "run_phase15_a",
                        "role": "train",
                        "status": "unknown_submit",
                    },
                    {
                        "job_id": "job_phase15_parent",
                        "run_id": "run_phase15_b",
                        "role": "train",
                        "status": "killed",
                        "failure_reason": "preempted",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    applied = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply"))
    assert applied["counts"]["insert"]["runs"] == 2
    assert applied["counts"]["insert"]["jobs"] == 1
    assert applied["counts"]["insert"]["job_runs"] == 2

    reapplied = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply"))
    assert reapplied["counts"]["noop"]["runs"] == 2
    assert reapplied["counts"]["noop"]["job_runs"] == 2

    archive_edge = tmp_path / "archive-edge.json"
    archive_edge.write_text(
        json.dumps(
            {
                "job_runs": [
                    {
                        "job_id": "job_phase15_parent",
                        "run_id": "run_phase15_a",
                        "_op": "archive",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    archived = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(archive_edge), "--apply"))
    assert archived["counts"]["archive"]["job_runs"] == 1
    resurrected = payload(run_fieldbook(ledger, "reconcile", "file", "--path", str(manifest), "--apply"))
    assert resurrected["counts"]["update"]["job_runs"] == 1
    assert resurrected["counts"]["noop"]["job_runs"] == 1

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["runs"]["total"] == 2
    assert status["runs"]["by_kind"] == {"datapoint": 1, "external": 1}
    assert status["runs"]["by_phase"] == {"failed": 1, "submitted": 1}

    role_mutation = tmp_path / "role-mutation.json"
    role_mutation.write_text(
        json.dumps(
            {
                "job_runs": [
                    {
                        "job_id": "job_phase15_parent",
                        "run_id": "run_phase15_a",
                        "role": "eval",
                        "status": "running",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = run_fieldbook(ledger, "reconcile", "file", "--path", str(role_mutation), "--apply", check=False)
    assert result.returncode == ExitCode.VALIDATION_ERROR

    errata_edge = tmp_path / "errata-edge.json"
    errata_edge.write_text(
        json.dumps(
            {
                "job_runs": [
                    {
                        "job_id": "job_phase15_parent",
                        "run_id": "run_phase15_a",
                        "role": "train",
                        "status": "running",
                        "_errata": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    errata_result = run_fieldbook(ledger, "reconcile", "file", "--path", str(errata_edge), "--apply", check=False)
    assert errata_result.returncode == ExitCode.VALIDATION_ERROR


def test_experiment_status_context_and_progress_views_report_matrix_progress(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(
        ledger,
        "phase15-progress",
        "progress.expected_runs=10",
        'progress.required_metrics=["eval/bpb"]',
    )
    run_ids = {
        name: add_run(ledger, experiment_id, name, f"phase15.{name}")["id"]
        for name in [
            "planned",
            "submitted",
            "unknown-submit",
            "training",
            "trained",
            "evaluated",
            "complete",
            "failed",
            "killed",
            "skipped",
        ]
    }
    for name, status in {
        "submitted": "planned",
        "unknown-submit": "unknown_submit",
        "training": "running",
        "trained": "succeeded",
        "evaluated": "succeeded",
        "complete": "succeeded",
        "failed": "failed",
        "killed": "killed",
        "skipped": "skipped",
    }.items():
        job = add_job(ledger, experiment_id, f"job-{name}", status=status)
        role = "eval" if name in {"evaluated", "complete"} else "train"
        link_job_run(ledger, job_id=job["id"], run_id=run_ids[name], role=role, status=status)
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_ids["trained"],
            "--type",
            "checkpoint",
            "--uri",
            str(tmp_path / "trained-checkpoint"),
        )
    )
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_ids["evaluated"],
            "--type",
            "eval-result",
            "--uri",
            str(tmp_path / "evaluated.json"),
        )
    )
    payload(run_fieldbook(ledger, "metric", "add", "--run", run_ids["complete"], "--name", "eval/bpb", "--value", "1.23"))

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["runs"]["total"] == 10
    assert status["runs"]["expected"] == 10
    assert status["runs"]["missing_expected_count"] == 0
    assert status["runs"]["by_phase"] == {
        "complete": 1,
        "evaluated": 1,
        "failed": 2,
        "planned": 1,
        "skipped": 1,
        "submitted": 2,
        "trained": 1,
        "training": 1,
    }
    assert status["runs"]["coverage"]["has_checkpoint"] == 1
    assert status["runs"]["coverage"]["has_eval_result"] == 1
    assert status["runs"]["coverage"]["by_metric"] == {"eval/bpb": 1}
    assert {row["name"] for row in status["runs"]["failed_examples"]} == {"failed", "killed"}
    assert status["runs"]["missing_examples"] == []

    context_text = run_fieldbook(ledger, "experiment", "context", experiment_id, "--json", check=True)
    context = payload(context_text)
    assert context["runs"]["total"] == 10

    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        phases = {
            row["name"]: row["phase"]
            for row in conn.execute(
                "SELECT name, phase FROM v_runs_progress_v1 WHERE experiment_id = ? ORDER BY name",
                (experiment_id,),
            ).fetchall()
        }
    finally:
        conn.close()
    assert phases["unknown-submit"] == "submitted"
    assert phases["killed"] == "failed"
    assert phases["complete"] == "complete"


def test_doctor_reports_run_matrix_and_linkage_issues(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(ledger, "phase15-doctor", "progress.expected_runs=2")
    run_id = add_run(ledger, experiment_id, "candidate-a", "phase15.doctor-a")["id"]
    job = add_job(ledger, experiment_id, "active-job", status="succeeded")
    link_job_run(ledger, job_id=job["id"], run_id=run_id, role="train", status="running")
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "checkpoint",
            "--uri",
            str(tmp_path / "unlinked-checkpoint"),
        )
    )

    doctor = payload(
        run_fieldbook(
            ledger,
            "doctor",
            "--check",
            "runs.expected_missing",
            "--check",
            "artifact.unlinked_to_run",
            "--check",
            "job_runs.stale_state",
            check=False,
        )
    )
    codes = {issue["code"] for issue in doctor["issues"]}
    assert {"runs.expected_missing", "artifact.unlinked_to_run", "job_runs.stale_state"}.issubset(codes)


def test_phase15_stable_views_exist_and_include_run_progress_columns(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_named_experiment(ledger, "phase15-skipped-precedence")
    skipped = add_run(ledger, experiment_id, "skipped-with-checkpoint", "phase15.skipped-precedence")
    job = add_job(ledger, experiment_id, "skip-job", status="skipped")
    link_job_run(ledger, job_id=job["id"], run_id=skipped["id"], role="train", status="skipped")
    payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            skipped["id"],
            "--type",
            "checkpoint",
            "--uri",
            str(tmp_path / "skipped-checkpoint"),
        )
    )
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        phase = conn.execute(
            "SELECT phase FROM v_runs_progress_v1 WHERE run_id = ?",
            (skipped["id"],),
        ).fetchone()["phase"]
        assert phase == "skipped"
        views = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()
        }
        assert {"v_job_runs_v1", "v_runs_progress_v1"}.issubset(views)
        run_columns = [row["name"] for row in conn.execute("PRAGMA table_info(v_runs_v1)").fetchall()]
        assert {"experiment_id", "kind", "idempotency_key"}.issubset(run_columns)
        progress_columns = [row["name"] for row in conn.execute("PRAGMA table_info(v_runs_progress_v1)").fetchall()]
        assert {
            "experiment_id",
            "run_id",
            "kind",
            "phase",
            "has_checkpoint",
            "has_eval_result",
            "metric_count",
            "train_active_count",
            "eval_succeeded_count",
        }.issubset(progress_columns)
    finally:
        conn.close()
