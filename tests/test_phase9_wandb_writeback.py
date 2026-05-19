import builtins
import json
import sqlite3

import pytest
from fieldbook.errors import ExitCode, ValidationError
from fieldbook.writeback import writer_from_name
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def add_metric(ledger, run_id: str, name: str, value: str = "1.25", *extra: str) -> dict:
    return payload(run_fieldbook(ledger, "metric", "add", "--run", run_id, "--name", name, "--value", value, *extra))


def create_child_run(ledger, experiment_id: str, parent_id: str) -> str:
    child = payload(
        run_fieldbook(
            ledger,
            "run",
            "add",
            "--name",
            "followup-eval",
            "--experiment",
            experiment_id,
            "--parent-run",
            parent_id,
        )
    )
    return child["id"]


def test_wandb_writeback_schema_and_retry_idempotency(tmp_path):
    ledger = init_ledger(tmp_path)
    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_events)").fetchall()}
        assert {
            "origin",
            "source_entity_type",
            "source_entity_id",
            "target_field",
            "payload_summary_json",
        }.issubset(columns)

        views = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()}
        assert "v_wandb_writeback_coverage_v1" in views

        conn.execute(
            "INSERT INTO sync_events (id, target_system, target_identifier, status, idempotency_key, created_at) "
            "VALUES ('manifest_a', 'wandb', 'target', 'synced', 'same', '2026-01-01T00:00:00Z')"
        )
        try:
            conn.execute(
                "INSERT INTO sync_events (id, target_system, target_identifier, status, idempotency_key, created_at) "
                "VALUES ('manifest_b', 'wandb', 'target', 'synced', 'same', '2026-01-01T00:00:01Z')"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("manifest sync-event idempotency should remain unique")

        conn.execute(
            "INSERT INTO sync_events (id, target_system, target_identifier, status, origin, idempotency_key, created_at) "
            "VALUES ('writeback_a', 'wandb', 'target', 'failed', 'writeback', 'retry', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO sync_events (id, target_system, target_identifier, status, origin, idempotency_key, created_at) "
            "VALUES ('writeback_b', 'wandb', 'target', 'synced', 'writeback', 'retry', '2026-01-01T00:00:01Z')"
        )
    finally:
        conn.close()


def test_wandb_writeback_dry_run_target_resolution_and_first_write_guardrail(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    parent_id = create_run(ledger, experiment_id)
    child_id = create_child_run(ledger, experiment_id, parent_id)
    metric = add_metric(ledger, child_id, "eval/new_metric", "0.42")

    plan = payload(run_fieldbook(ledger, "writeback", "wandb", "--run", child_id, "--metric", "eval/*"))

    assert plan["dry_run"] is True
    assert plan["source_run_id"] == child_id
    assert plan["target_identifier"] == "abc123"
    assert plan["summary"]["first_write_requires_ack"] is True
    assert plan["summary"]["planned_count"] == 1
    assert plan["planned"][0]["source_metric_id"] == metric["id"]
    assert plan["planned"][0]["target_field"] == "fieldbook/eval/new_metric"


def test_wandb_writeback_apply_requires_explicit_writer(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    add_metric(ledger, run_id, "eval/loss")

    result = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        run_id,
        "--metric",
        "eval/*",
        "--apply",
        "--first-write-ok",
        check=False,
    )

    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "--writer" in result.stderr


def test_real_wandb_writer_missing_dependency_message(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "wandb":
            raise ImportError("missing wandb")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ValidationError, match="W&B extra"):
        writer_from_name("real")


def test_wandb_writeback_fake_apply_and_idempotent_skip(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    metric = add_metric(ledger, run_id, "eval/loss", "1.5")

    applied = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--apply",
            "--writer",
            "fake",
            "--first-write-ok",
        )
    )
    assert applied["summary"]["synced_count"] == 1
    assert applied["results"][0]["status"] == "synced"

    skipped = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--apply",
            "--writer",
            "fake",
        )
    )
    assert skipped["summary"]["planned_count"] == 0
    assert skipped["summary"]["skipped_count"] == 1

    conn = sqlite3.connect(ledger)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM sync_events WHERE origin = 'writeback'").fetchall()
        assert len(rows) == 1
        assert rows[0]["source_entity_id"] == metric["id"]
        assert rows[0]["source_entity_type"] == "metric"
        assert rows[0]["target_field"] == "fieldbook/eval/loss"
        assert json.loads(rows[0]["payload_summary_json"]) == {"value": 1.5}
    finally:
        conn.close()

    rewritten = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--apply",
            "--writer",
            "fake",
            "--allow-rewrite",
        )
    )
    assert rewritten["summary"]["synced_count"] == 1


def test_wandb_writeback_failure_retry_log_view_and_doctor(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    metric = add_metric(ledger, run_id, "eval/fail", "2.0")

    failed = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--apply",
            "--writer",
            "fake",
            "--first-write-ok",
            "--fake-fail-field",
            "fieldbook/eval/fail",
        )
    )
    assert failed["results"][0]["status"] == "failed"
    assert "Bearer" not in failed["results"][0]["error_message"]

    unresolved_doctor = payload(run_fieldbook(ledger, "doctor", "--check", "sync-events", "--stale-hours", "0"))
    assert "sync_event.failed_writeback" in {issue["code"] for issue in unresolved_doctor["issues"]}

    retry_plan = payload(run_fieldbook(ledger, "writeback", "wandb", "--run", run_id, "--metric", "eval/*"))
    assert retry_plan["summary"]["planned_count"] == 1

    retried = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--apply",
            "--writer",
            "fake",
        )
    )
    assert retried["summary"]["synced_count"] == 1

    log = payload(run_fieldbook(ledger, "writeback", "log", "--target-system", "wandb", "--source-entity", metric["id"]))
    assert [event["status"] for event in log["events"]] == ["synced", "failed"]

    coverage = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT source_entity_id, latest_status FROM v_wandb_writeback_coverage_v1",
        )
    )
    assert coverage["rows"] == [{"source_entity_id": metric["id"], "latest_status": "synced"}]

    legacy_sync = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT run_id, wandb_sync_count FROM v_wandb_sync_coverage_v1 WHERE run_id = '%s'" % run_id,
        )
    )
    assert legacy_sync["rows"] == [{"run_id": run_id, "wandb_sync_count": 0}]

    doctor = payload(run_fieldbook(ledger, "doctor", "--check", "sync-events", "--stale-hours", "0"))
    assert "sync_event.duplicate_idempotency_key" not in {issue["code"] for issue in doctor["issues"]}
    assert "sync_event.failed_writeback" not in {issue["code"] for issue in doctor["issues"]}


def test_wandb_writeback_rejects_collisions_and_unsafe_targets(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    add_metric(ledger, run_id, "eval/loss", "1.0", "--split", "validation")
    add_metric(ledger, run_id, "eval/loss", "2.0", "--split", "test")

    collision = run_fieldbook(ledger, "writeback", "wandb", "--run", run_id, "--metric", "eval/*", check=False)
    assert collision.returncode == ExitCode.VALIDATION_ERROR
    assert "target field collision" in collision.stderr

    raw = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        run_id,
        "--metric",
        "eval/*",
        "--raw-keys",
        "--apply",
        "--writer",
        "fake",
        "--first-write-ok",
        check=False,
    )
    assert raw.returncode == ExitCode.VALIDATION_ERROR

    wrong_target = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        run_id,
        "--metric",
        "eval/loss",
        "--target-run",
        "wrong-target",
        "--apply",
        "--writer",
        "fake",
        "--first-write-ok",
        check=False,
    )
    assert wrong_target.returncode == ExitCode.VALIDATION_ERROR
    assert "--force-target" in wrong_target.stderr


def test_wandb_writeback_prefix_and_validation_edges(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    add_metric(ledger, run_id, "eval/loss", "1.0")

    custom = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            run_id,
            "--metric",
            "eval/*",
            "--key-prefix",
            "custom/",
        )
    )
    assert custom["planned"][0]["target_field"] == "custom/eval/loss"

    raw_preview = payload(
        run_fieldbook(ledger, "writeback", "wandb", "--run", run_id, "--metric", "eval/*", "--raw-keys")
    )
    assert raw_preview["planned"][0]["target_field"] == "eval/loss"

    empty_prefix = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        run_id,
        "--metric",
        "eval/*",
        "--key-prefix",
        "",
        check=False,
    )
    assert empty_prefix.returncode == ExitCode.VALIDATION_ERROR

    raw_prefix = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        run_id,
        "--metric",
        "eval/*",
        "--raw-keys",
        "--key-prefix",
        "fieldbook",
        check=False,
    )
    assert raw_prefix.returncode == ExitCode.VALIDATION_ERROR

    run_fieldbook(ledger, "run", "archive", run_id)
    archived = run_fieldbook(ledger, "writeback", "wandb", "--run", run_id, "--metric", "eval/*", check=False)
    assert archived.returncode == ExitCode.VALIDATION_ERROR
    assert "archived" in archived.stderr

    orphan = payload(run_fieldbook(ledger, "run", "add", "--experiment", experiment_id, "--name", "no-wandb"))
    orphan_metric = add_metric(ledger, orphan["id"], "eval/loss", "1.0")
    missing_target = run_fieldbook(
        ledger,
        "writeback",
        "wandb",
        "--run",
        orphan["id"],
        "--metric",
        "eval/*",
        check=False,
    )
    assert missing_target.returncode == ExitCode.VALIDATION_ERROR
    assert "--target-run" in missing_target.stderr

    explicit = payload(
        run_fieldbook(
            ledger,
            "writeback",
            "wandb",
            "--run",
            orphan["id"],
            "--metric",
            "eval/*",
            "--target-run",
            "entity/project/runid",
        )
    )
    assert explicit["target_identifier"] == "entity/project/runid"
    assert explicit["planned"][0]["source_metric_id"] == orphan_metric["id"]


def test_reconcile_rejects_writeback_origin_sync_events(tmp_path):
    ledger = init_ledger(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sync_events": [
                    {
                        "target_system": "wandb",
                        "target_identifier": "abc123",
                        "status": "synced",
                        "origin": "writeback",
                    }
                ]
            }
        )
    )

    result = run_fieldbook(
        ledger,
        "reconcile",
        "file",
        "--path",
        str(manifest),
        "--source",
        "bad-sync",
        "--apply",
        check=False,
    )

    assert result.returncode == ExitCode.VALIDATION_ERROR
    assert "origin='writeback'" in result.stderr
