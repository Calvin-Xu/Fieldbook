import csv
import json
import subprocess
import sys
from pathlib import Path

from fieldbook.errors import ExitCode


def run_fieldbook(ledger: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", *args, "--ledger", str(ledger), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def payload(result: subprocess.CompletedProcess[str]):
    return json.loads(result.stdout)


def init_ledger(tmp_path: Path) -> Path:
    ledger = tmp_path / "ledger.sqlite"
    run_fieldbook(ledger, "init")
    return ledger


def create_experiment(ledger: Path) -> str:
    result = run_fieldbook(
        ledger,
        "experiment",
        "create",
        "--name",
        "benchmark-proxies",
        "--description",
        "Benchmark proxy modeling",
        "--tag",
        "marin",
        "--tag",
        "proxy",
        "--attr",
        "marin.scale=300m_6b",
    )
    data = payload(result)
    assert data["id"].startswith("exp_")
    assert data["tags"] == ["marin", "proxy"]
    assert data["attrs"] == {"marin.scale": "300m_6b"}
    return data["id"]


def create_run(ledger: Path, experiment_id: str) -> str:
    result = run_fieldbook(
        ledger,
        "run",
        "add",
        "--name",
        "run_00097",
        "--experiment",
        experiment_id,
        "--external-system",
        "wandb",
        "--external-id",
        "abc123",
        "--attr",
        "marin.mixture=proportional",
    )
    data = payload(result)
    assert data["id"].startswith("run_")
    assert data["experiment_ids"] == [experiment_id]
    return data["id"]


def test_experiment_run_job_note_status_flow(tmp_path):
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
            "--command",
            "uv run train",
            "--launcher",
            "iris",
            "--external-system",
            "iris",
            "--external-id",
            "/calvinxu/train",
            "--started-at",
            "2026-05-18T00:00:00Z",
        )
    )
    assert job["experiment_id"] == experiment_id
    assert job["code_commit"] is not None
    assert job["status"] == "running"

    updated = payload(run_fieldbook(ledger, "job", "update-status", job["id"], "--status", "failed"))
    assert updated["status"] == "failed"

    corrected = payload(run_fieldbook(ledger, "job", "update-status", job["id"], "--status", "running"))
    assert corrected["status"] == "running"

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
            "Retry failed evals",
        )
    )
    assert note["status"] == "open"

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["run_count"] == 1
    assert status["job_counts"] == {"running": 1}
    assert status["open_note_count"] == 1

    resolved = payload(run_fieldbook(ledger, "note", "resolve", note["id"]))
    assert resolved["status"] == "resolved"


def test_list_show_link_archive_and_tags(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)

    experiments = payload(run_fieldbook(ledger, "experiment", "list", "--tag", "marin"))
    assert [row["id"] for row in experiments] == [experiment_id]

    shown = payload(run_fieldbook(ledger, "run", "show", run_id))
    assert shown["name"] == "run_00097"

    other_experiment = payload(run_fieldbook(ledger, "experiment", "create", "--name", "evals"))["id"]
    linked = payload(run_fieldbook(ledger, "run", "link", run_id, "--experiment", other_experiment))
    assert linked["experiment_ids"] == [experiment_id, other_experiment]

    archived = payload(run_fieldbook(ledger, "run", "archive", run_id))
    assert archived["status"] == "archived"

    active_runs = payload(run_fieldbook(ledger, "run", "list", "--experiment", experiment_id))
    assert active_runs == []

    archived_runs = payload(
        run_fieldbook(ledger, "run", "list", "--experiment", experiment_id, "--include-archived")
    )
    assert [row["id"] for row in archived_runs] == [run_id]


def test_artifacts_metrics_and_metric_import_are_idempotent(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)

    artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--run",
            run_id,
            "--type",
            "checkpoint",
            "--uri",
            "gs://bucket/checkpoints/step-1",
            "--content-hash",
            "sha256:" + "a" * 64,
        )
    )
    assert artifact["id"].startswith("art_")

    metric = payload(
        run_fieldbook(
            ledger,
            "metric",
            "add",
            "--run",
            run_id,
            "--name",
            "eval/loss",
            "--value",
            "1.5",
            "--step",
            "1",
            "--split",
            "valid",
            "--source-artifact",
            artifact["id"],
        )
    )
    assert metric["value"] == 1.5

    updated = payload(
        run_fieldbook(
            ledger,
            "metric",
            "add",
            "--run",
            run_id,
            "--name",
            "eval/loss",
            "--value",
            "1.25",
            "--step",
            "1",
            "--split",
            "valid",
            "--source-artifact",
            artifact["id"],
        )
    )
    assert updated["id"] == metric["id"]
    assert updated["value"] == 1.25

    csv_path = ledger.parent / "metrics.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_id", "metric_name", "value", "step"])
        writer.writeheader()
        writer.writerow({"run_id": run_id, "metric_name": "eval/accuracy", "value": "0.4", "step": "1"})

    imported = payload(run_fieldbook(ledger, "metric", "import-csv", "--path", str(csv_path)))
    assert imported["imported"] == 1

    metrics = payload(run_fieldbook(ledger, "metric", "list", "--run", run_id))
    assert {row["metric_name"] for row in metrics} == {"eval/loss", "eval/accuracy"}


def test_validation_errors_and_external_identifier_ambiguity(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    create_run(ledger, experiment_id)

    duplicate = run_fieldbook(
        ledger,
        "run",
        "add",
        "--name",
        "duplicate",
        "--external-system",
        "wandb",
        "--external-id",
        "abc123",
        check=False,
    )
    assert duplicate.returncode == ExitCode.AMBIGUITY
    assert "already exists" in duplicate.stderr

    invalid_attr = run_fieldbook(
        ledger,
        "experiment",
        "create",
        "--name",
        "bad",
        "--attr",
        "fieldbook.owner=reserved",
        check=False,
    )
    assert invalid_attr.returncode == ExitCode.VALIDATION_ERROR

    invalid_hash = run_fieldbook(
        ledger,
        "artifact",
        "add",
        "--run",
        "run_00097",
        "--type",
        "checkpoint",
        "--uri",
        "gs://bucket/checkpoint",
        "--content-hash",
        "sha256:bad",
        check=False,
    )
    assert invalid_hash.returncode == ExitCode.VALIDATION_ERROR

    invalid_time = run_fieldbook(
        ledger,
        "job",
        "add",
        "--experiment",
        experiment_id,
        "--status",
        "running",
        "--started-at",
        "2026-05-18 00:00:00",
        check=False,
    )
    assert invalid_time.returncode == ExitCode.VALIDATION_ERROR
