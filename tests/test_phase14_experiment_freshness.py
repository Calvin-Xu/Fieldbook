import json
import os
from pathlib import Path

from fieldbook.validation import file_sha256
from tests.test_phase2_cli import create_experiment, init_ledger, payload, run_fieldbook


def _touch_future(path: Path) -> None:
    future = path.stat().st_mtime + 10.0
    os.utime(path, (future, future))


def test_local_artifact_metadata_refresh_and_drift_doctor(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    report = tmp_path / "report.md"
    report.write_text("initial\n", encoding="utf-8")

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
            str(report),
        )
    )
    attrs = artifact["attrs"]
    assert attrs["fieldbook.local_path_at_capture"] == str(report.resolve())
    assert isinstance(attrs["fieldbook.local_mtime_at_capture"], float)
    assert attrs["fieldbook.local_size_at_capture"] == report.stat().st_size

    remote = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "report",
            "--uri",
            "gs://bucket/report.md",
        )
    )
    assert "fieldbook.local_mtime_at_capture" not in remote["attrs"]

    report.write_text("changed\n", encoding="utf-8")
    _touch_future(report)
    doctor = payload(
        run_fieldbook(
            ledger,
            "doctor",
            "--check",
            "artifact.local_drift",
            check=False,
        )
    )
    drift_issue = next(issue for issue in doctor["issues"] if issue["code"] == "artifact.local_drift")
    assert drift_issue["entity_id"] == artifact["id"]
    assert drift_issue["details"]["drift_kind"] in {"mtime", "size", "mtime_size"}

    refreshed = payload(run_fieldbook(ledger, "artifact", "refresh-local", artifact["id"], "--update-hash"))
    assert refreshed["content_hash"] == file_sha256(report)
    assert refreshed["attrs"]["fieldbook.local_size_at_capture"] == report.stat().st_size
    doctor = payload(run_fieldbook(ledger, "doctor", "--check", "artifact.local_drift"))
    assert doctor["issues"] == []


def test_validation_source_drift_and_experiment_checkpoint_status(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    report = tmp_path / "coverage.json"
    report.write_text('{"complete": true}\n', encoding="utf-8")
    artifact = payload(
        run_fieldbook(
            ledger,
            "artifact",
            "add",
            "--experiment",
            experiment_id,
            "--type",
            "validation-report",
            "--uri",
            str(report),
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
            "--source-artifact",
            artifact["id"],
        )
    )

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["freshness"]["checkpoint_status"] == "missing"
    assert status["freshness"]["drifted_artifact_count"] == 0
    assert status["freshness"]["stale_validation_count"] == 0

    report.write_text('{"complete": false}\n', encoding="utf-8")
    _touch_future(report)
    doctor = payload(
        run_fieldbook(
            ledger,
            "doctor",
            "--check",
            "artifact.local_drift",
            "--check",
            "validation.source_drift",
            check=False,
        )
    )
    codes = {issue["code"] for issue in doctor["issues"]}
    assert "artifact.local_drift" in codes
    validation_issue = next(issue for issue in doctor["issues"] if issue["code"] == "validation.source_drift")
    assert validation_issue["entity_id"] == validation["id"]
    assert validation_issue["details"]["source_drifted"] is True

    checkpoint = payload(run_fieldbook(ledger, "experiment", "checkpoint", experiment_id, "--body", "Manual checkpoint."))
    assert checkpoint["note"]["note_type"] == "checkpoint"
    assert "## Freshness" in checkpoint["note"]["body"]
    assert checkpoint["freshness"]["drifted_artifact_count"] == 1
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["freshness"]["checkpoint_status"] == "current"
    assert status["freshness"]["last_checkpoint_at"] == checkpoint["note"]["created_at"]

    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))
    erratum_checkpoint = payload(
        run_fieldbook(ledger, "experiment", "checkpoint", experiment_id, "--errata", "--body", "Post-archive correction.")
    )
    assert erratum_checkpoint["experiment"]["deleted_at"] is not None
    assert erratum_checkpoint["note"]["attrs"]["fieldbook.erratum"] is True


def test_empty_experiment_freshness_is_idle(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id))
    assert status["freshness"]["checkpoint_status"] == "idle"
    doctor = payload(run_fieldbook(ledger, "doctor", "--check", "experiment.checkpoint_stale"))
    assert doctor["issues"] == []
