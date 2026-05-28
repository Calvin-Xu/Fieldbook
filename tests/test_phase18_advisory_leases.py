import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, create_run, init_ledger, payload, run_fieldbook


def _ts(hours: float) -> str:
    return (datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _add_job(ledger: Path, run_id: str, name: str, status: str, *extra: str) -> dict:
    return payload(run_fieldbook(ledger, "job", "add", "--run", run_id, "--name", name, "--status", status, *extra))


def _set_heartbeat(ledger: Path, lease_id: str, timestamp: str) -> None:
    with sqlite3.connect(ledger) as conn:
        conn.execute("UPDATE leases SET heartbeat_at = ? WHERE id = ?", (timestamp, lease_id))


def test_lease_claim_list_show_heartbeat_and_release(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)

    claim = payload(
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
            "--expires-at",
            _ts(2),
            "--attr",
            "monitor.intent=babysit",
        )
    )
    assert claim["lease"]["id"].startswith("lea_")
    assert claim["lease"]["owner_agent"] == "codex"
    assert claim["lease"]["attrs"] == {"monitor.intent": "babysit"}
    assert claim["existed"] is False

    listed = payload(run_fieldbook(ledger, "lease", "list", "--entity-type", "experiment", "--entity-id", experiment_id))
    assert [lease["id"] for lease in listed["leases"]] == [claim["lease"]["id"]]
    shown = payload(run_fieldbook(ledger, "lease", "show", claim["lease"]["id"]))
    assert shown["id"] == claim["lease"]["id"]

    heartbeat = payload(
        run_fieldbook(
            ledger,
            "lease",
            "heartbeat",
            claim["lease"]["id"],
            "--owner",
            "codex",
            "--attr",
            "monitor.last_seen=running",
        )
    )
    assert heartbeat["heartbeat_at"] >= claim["lease"]["heartbeat_at"]
    assert heartbeat["owner_agent"] == "codex"
    assert heartbeat["claimed_at"] == claim["lease"]["claimed_at"]
    assert heartbeat["attrs"]["monitor.last_seen"] == "running"

    released = payload(
        run_fieldbook(ledger, "lease", "release", claim["lease"]["id"], "--owner", "codex", "--reason", "handoff")
    )
    assert released["released_at"] is not None
    assert released["release_reason"] == "handoff"
    assert payload(run_fieldbook(ledger, "lease", "list"))["leases"] == []


def test_lease_conflict_same_owner_idempotency_expired_and_force_takeover(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)

    first = payload(
        run_fieldbook(ledger, "lease", "claim", "--entity-type", "experiment", "--entity-id", experiment_id, "--owner", "codex")
    )
    duplicate = payload(
        run_fieldbook(ledger, "lease", "claim", "--entity-type", "experiment", "--entity-id", experiment_id, "--owner", "codex")
    )
    assert duplicate["lease"]["id"] == first["lease"]["id"]
    assert duplicate["existed"] is True

    conflict = run_fieldbook(
        ledger,
        "lease",
        "claim",
        "--entity-type",
        "experiment",
        "--entity-id",
        experiment_id,
        "--owner",
        "claude",
        check=False,
    )
    assert conflict.returncode == ExitCode.VALIDATION_ERROR

    forced = payload(
        run_fieldbook(
            ledger,
            "lease",
            "claim",
            "--entity-type",
            "experiment",
            "--entity-id",
            experiment_id,
            "--owner",
            "claude",
            "--force",
        )
    )
    assert forced["takeover"]["release_reason"] == "force_takeover"
    assert forced["lease"]["previous_lease_id"] == first["lease"]["id"]

    run_id = create_run(ledger, experiment_id)
    expired = payload(
        run_fieldbook(
            ledger,
            "lease",
            "claim",
            "--entity-type",
            "run",
            "--entity-id",
            run_id,
            "--owner",
            "codex",
            "--expires-at",
            _ts(-1),
        )
    )
    takeover = payload(
        run_fieldbook(ledger, "lease", "claim", "--entity-type", "run", "--entity-id", run_id, "--owner", "claude")
    )
    assert takeover["takeover"]["id"] == expired["lease"]["id"]
    assert takeover["takeover"]["release_reason"] == "expired"
    assert takeover["lease"]["previous_lease_id"] == expired["lease"]["id"]


def test_lease_heartbeat_stale_doctor_and_no_auto_release(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    lease = payload(
        run_fieldbook(ledger, "lease", "claim", "--entity-type", "experiment", "--entity-id", experiment_id, "--owner", "codex")
    )["lease"]
    _set_heartbeat(ledger, lease["id"], _ts(-3))

    doctor = payload(
        run_fieldbook(ledger, "doctor", "--check", "leases", "--stale-lease-hours", "1", check=False)
    )
    assert doctor["issues"][0]["code"] == "lease.stale_heartbeat"
    assert doctor["issues"][0]["entity_id"] == lease["id"]
    assert payload(run_fieldbook(ledger, "lease", "show", lease["id"]))["released_at"] is None


def test_lease_release_rejects_invalid_reason_even_when_released(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    lease = payload(
        run_fieldbook(ledger, "lease", "claim", "--entity-type", "experiment", "--entity-id", experiment_id, "--owner", "codex")
    )["lease"]
    payload(run_fieldbook(ledger, "lease", "release", lease["id"], "--owner", "codex", "--reason", "handoff"))

    invalid = run_fieldbook(ledger, "lease", "release", lease["id"], "--reason", "bogus", check=False)
    assert invalid.returncode == ExitCode.VALIDATION_ERROR


def test_lease_doctor_outlived_session_and_archived_entity(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    session = payload(run_fieldbook(ledger, "session", "start", "--experiment", experiment_id, "--agent", "codex"))["session"]
    lease = payload(
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
            "--session",
            session["id"],
        )
    )["lease"]
    payload(run_fieldbook(ledger, "session", "end", "--id", session["id"]))
    payload(run_fieldbook(ledger, "experiment", "archive", experiment_id))

    doctor = payload(run_fieldbook(ledger, "doctor", "--check", "leases", check=False))
    codes = {issue["code"] for issue in doctor["issues"] if issue["entity_id"] == lease["id"]}
    assert {"lease.outlived_session", "lease.archived_entity"} <= codes


def test_lease_attrs_do_not_mutate_authoritative_job_status(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    job = _add_job(ledger, run_id, "train", "running")

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
            "--attr",
            "monitor.observed_status=succeeded",
        )
    )
    assert payload(run_fieldbook(ledger, "job", "show", job["id"]))["status"] == "running"


def test_lease_status_workloop_and_views(tmp_path: Path) -> None:
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)
    run_id = create_run(ledger, experiment_id)
    failed = _add_job(ledger, run_id, "retry1", "failed")
    retry = _add_job(ledger, run_id, "retry2", "running", "--retry-of", failed["id"])

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
            "planner",
        )
    )
    job_lease = payload(
        run_fieldbook(
            ledger,
            "lease",
            "claim",
            "--entity-type",
            "job",
            "--entity-id",
            retry["id"],
            "--owner",
            "babysitter",
        )
    )["lease"]
    _set_heartbeat(ledger, job_lease["id"], _ts(-3))

    status = payload(run_fieldbook(ledger, "experiment", "status", experiment_id, "--stale-lease-hours", "1"))
    assert status["leases"]["active_count"] == 2
    assert status["leases"]["stale_count"] == 1
    assert {lease["owner_agent"] for lease in status["leases"]["active"]} == {"planner", "babysitter"}

    workloop = payload(run_fieldbook(ledger, "experiment", "workloop", experiment_id, "--stale-lease-hours", "1"))
    assert workloop["leases"]["stale_count"] == 1
    assert any("lease" in action["command"] for action in workloop["suggested_next_actions"])

    active = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT owner_agent, entity_type FROM v_leases_active_v1 ORDER BY owner_agent",
        )
    )
    assert active["rows"] == [
        {"owner_agent": "babysitter", "entity_type": "job"},
        {"owner_agent": "planner", "entity_type": "experiment"},
    ]
    job_summary = payload(
        run_fieldbook(
            ledger,
            "sql",
            "--query",
            "SELECT owner_agent, retry_depth FROM v_job_ownership_v1 WHERE job_id = '" + retry["id"] + "'",
        )
    )
    assert job_summary["rows"] == [{"owner_agent": "babysitter", "retry_depth": 1}]


def test_docs_and_skill_describe_advisory_leases() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    skill = (root / ".codex" / "skills" / "fieldbook" / "SKILL.md").read_text(encoding="utf-8")

    assert "uv run fieldbook lease claim --entity-type job" in readme
    assert "Leases are advisory ownership records, not locks." in readme
    assert "uv run fieldbook lease heartbeat" in skill
    assert "Lease attrs are monitor observations only" in skill
