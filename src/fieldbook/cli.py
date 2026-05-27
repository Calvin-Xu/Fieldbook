import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fieldbook.adapters import (
    AdapterFailure,
    describe_adapter,
    list_adapters,
    read_adapter_input,
    run_adapter,
    write_json_payload,
)
from fieldbook.db import connect, discover_ledger, init_ledger, resolve_init_path
from fieldbook.errors import ExitCode, FieldbookError, LedgerBusyError, NotFoundError, ValidationError
from fieldbook.git_info import current_git_revision
from fieldbook.ledger_resolution import (
    LedgerResolution,
    db_where_payload,
    ensure_marker_gitignore,
    resolve_ledger_location,
    session_marker_path,
)
from fieldbook.output import emit
from fieldbook.doctor import doctor_failed, format_doctor_text, list_doctor_checks, run_doctor
from fieldbook.repository import Repository, note_body_preview
from fieldbook.reconcile import load_manifest, reconcile_log, reconcile_manifest
from fieldbook.refresh import list_refresh_sources, refresh_log, run_refresh
from fieldbook.snapshot import export_snapshot, import_snapshot, inspect_snapshot
from fieldbook.sql_query import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_SQL_LIMIT, DEFAULT_SQL_TIMEOUT, execute_readonly_sql, resolve_sql_text
from fieldbook.validation import NOTE_BODY_FORMATS, parse_attrs, validate_metric_value
from fieldbook.writeback import apply_wandb_writeback, plan_wandb_writeback, wandb_writeback_log, writer_from_name


Command = Callable[[argparse.Namespace, Repository], Any]


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", help="Path to Fieldbook ledger")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")


def _add_attr_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--attr", action="append", default=[], help="Namespaced key=value custom attribute")


def _with_repo(args: argparse.Namespace, command: Command) -> int:
    resolution = resolve_ledger_location(ledger=args.ledger)
    args._fieldbook_resolution = resolution
    ledger_path = resolution.path
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    conn = connect(ledger_path, allow_newer_readonly=_is_read_only(args))
    try:
        session_id, _, _ = _resolved_session_id(resolution)
        repo = Repository(conn, current_session_id=session_id)
        payload = command(args, repo)
    finally:
        conn.close()
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _is_read_only(args: argparse.Namespace) -> bool:
    command = getattr(args, "command", None)
    if command == "experiment":
        experiment_command = getattr(args, "experiment_command", None)
        if experiment_command == "cleanup":
            return not getattr(args, "apply", False)
        return getattr(args, "experiment_command", None) in {
            "list",
            "show",
            "status",
            "context",
            "triage",
            "closeout-checklist",
        }
    if command == "run":
        return getattr(args, "run_command", None) in {"list", "show"}
    if command == "job":
        return getattr(args, "job_command", None) in {"list", "show"}
    if command == "artifact":
        return getattr(args, "artifact_command", None) in {"list", "show"}
    if command == "metric":
        return getattr(args, "metric_command", None) == "list"
    if command == "validation":
        return getattr(args, "validation_command", None) in {"list", "show"}
    if command == "note":
        return getattr(args, "note_command", None) in {"list", "show"}
    if command == "reconcile":
        return getattr(args, "reconcile_command", None) == "log" or (
            getattr(args, "reconcile_command", None) == "file" and not getattr(args, "apply", False)
        )
    if command == "refresh":
        return getattr(args, "refresh_command", None) in {"list-sources", "log"}
    if command in {"db", "sql"}:
        return True
    if command == "session":
        return getattr(args, "session_command", None) in {"current", "list"}
    if command == "writeback":
        return getattr(args, "writeback_command", None) == "log" or (
            getattr(args, "writeback_command", None) == "wandb" and not getattr(args, "apply", False)
        )
    if command == "export":
        return getattr(args, "export_command", None) == "coverage" and not getattr(args, "output", None)
    return False


def _cmd_init(args: argparse.Namespace) -> int:
    ledger_path = resolve_init_path(ledger=args.ledger)
    existed = ledger_path.exists()
    init_ledger(ledger_path)
    payload = {"ledger": str(ledger_path), "existed": existed}
    emit(payload, json_output=args.json, text=f"{'existing' if existed else 'created'} Fieldbook ledger: {ledger_path}")
    return ExitCode.SUCCESS


def _cmd_db_path(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    emit({"path": str(ledger_path)}, json_output=args.json, text=str(ledger_path))
    return ExitCode.SUCCESS


def _cmd_db_where(args: argparse.Namespace) -> int:
    resolution = resolve_ledger_location(ledger=args.ledger, require_exists=False)
    payload = db_where_payload(resolution)
    text = payload["ledger_path"] or f"no Fieldbook ledger found; would initialize at {payload['would_init_at']}"
    emit(payload, json_output=args.json, text=str(text))
    return ExitCode.SUCCESS


def _cmd_sql(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    sql = resolve_sql_text(
        query=args.query,
        file=args.file,
        stdin=args.stdin,
        stdin_text=sys.stdin.read() if args.stdin else None,
    )
    stdout, stderr = execute_readonly_sql(
        ledger_path=ledger_path,
        sql=sql,
        limit=args.limit,
        no_limit=args.no_limit,
        timeout=args.timeout,
        max_output_bytes=args.max_output_bytes,
        allow_blobs=args.allow_blobs,
        output_format=args.format,
    )
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return ExitCode.SUCCESS


def _cmd_doctor(args: argparse.Namespace) -> int:
    if args.list_checks:
        emit(list_doctor_checks(), json_output=args.json)
        return ExitCode.SUCCESS
    resolution = resolve_ledger_location(ledger=args.ledger)
    ledger_path = resolution.path
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    try:
        envelope = run_doctor(
            ledger_path,
            check_ids=args.check,
            stale_hours=args.stale_hours,
            stale_session_hours=args.stale_session_hours,
            stale_submitting_hours=args.stale_submitting_hours,
            stale_unknown_submit_hours=args.stale_unknown_submit_hours,
            retry_loop_threshold=args.retry_loop_threshold,
            stale_refresh_snapshot_days=args.stale_refresh_snapshot_days,
            locality_recent_days=args.locality_recent_days,
            cwd=Path.cwd(),
            resolved_via=resolution.resolved_via,
            experiment_ref=args.experiment,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    emit(envelope, json_output=args.json, text=format_doctor_text(envelope))
    return ExitCode.VALIDATION_ERROR if doctor_failed(envelope, strict=args.strict) else ExitCode.SUCCESS


def _cmd_experiment_workloop(args: argparse.Namespace) -> int:
    if not args.checkpoint and (args.body is not None or args.body_file is not None or args.body_stdin):
        raise ValidationError("workloop body sources require --checkpoint")
    if args.refresh and args.refresh_all:
        raise ValidationError("workloop refresh requires --refresh or --refresh-all, not both")
    resolution = resolve_ledger_location(ledger=args.ledger)
    ledger_path = resolution.path
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    needs_write = args.checkpoint or args.apply or bool(args.refresh) or args.refresh_all
    conn = connect(ledger_path, allow_newer_readonly=not needs_write)
    try:
        session_id, session_source, marker_status = _resolved_session_id(resolution)
        repo = Repository(conn, current_session_id=session_id)
        experiment = repo.get_experiment(args.experiment)
        if args.checkpoint and experiment["deleted_at"] is not None:
            raise ValidationError("workloop checkpoint requires an active experiment")
        source_names: list[str] = []
        refresh_payload = None
        if args.refresh or args.refresh_all:
            config_path = Path(args.config) if args.config else None
            source_names = list(args.refresh or [])
            if args.refresh_all:
                listing = list_refresh_sources(ledger_path=ledger_path, config_path=config_path)
                source_names = [source["name"] for source in listing["sources"]]
            refresh_payload = run_refresh(
                repo,
                ledger_path=ledger_path,
                config_path=config_path,
                source_names=source_names,
                experiment_ref=experiment["id"],
                apply=args.apply,
            )
        status = repo.experiment_status(experiment["id"], stale_hours=args.stale_hours)
        doctor = run_doctor(
            ledger_path,
            check_ids=None,
            stale_hours=args.stale_hours,
            cwd=Path.cwd(),
            experiment_ref=experiment["id"],
            resolved_via=resolution.resolved_via,
        )
        payload = _workloop_payload(
            status=status,
            doctor=doctor,
            resolution=resolution,
            session_id=session_id,
            session_source=session_source,
            marker_status=marker_status,
            refresh_payload=refresh_payload,
        )
        if refresh_payload is not None:
            payload["refresh_request"] = {
                "all": args.refresh_all,
                "sources": source_names,
                "apply": args.apply,
            }
        if args.checkpoint:
            checkpoint = repo.checkpoint_experiment(
                experiment["id"],
                body=_resolve_optional_body(args),
                archive=False,
                errata=False,
                stale_hours=args.stale_hours,
            )
            payload["checkpoint"] = checkpoint
    finally:
        conn.close()
    emit(payload, json_output=args.json, text=_format_workloop_markdown(payload))
    return ExitCode.SUCCESS


def _cmd_experiment_triage(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    conn = connect(ledger_path, allow_newer_readonly=True)
    try:
        repo = Repository(conn)
        status = repo.experiment_status(args.experiment, stale_hours=args.stale_hours)
        experiment_id = status["experiment"]["id"]
        doctor = run_doctor(ledger_path, check_ids=None, stale_hours=args.stale_hours, cwd=Path.cwd())
        payload = _triage_payload(conn, status, doctor, experiment_id)
    finally:
        conn.close()
    emit(payload, json_output=args.json, text=_format_triage_markdown(payload))
    return ExitCode.SUCCESS


def _cmd_experiment_closeout_checklist(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    conn = connect(ledger_path, allow_newer_readonly=True)
    try:
        repo = Repository(conn)
        status = repo.experiment_status(args.experiment, stale_hours=args.stale_hours)
        experiment_id = status["experiment"]["id"]
        doctor = run_doctor(ledger_path, check_ids=None, stale_hours=args.stale_hours, cwd=Path.cwd())
        payload = _closeout_payload(conn, status, doctor, experiment_id)
    finally:
        conn.close()
    emit(payload, json_output=args.json, text=_format_closeout_markdown(payload))
    return ExitCode.SUCCESS


def _snapshot_export(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    payload = export_snapshot(
        ledger_path=ledger_path,
        output_path=Path(args.output),
        replace=args.replace,
        metadata=not args.no_metadata,
    )
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _snapshot_inspect(args: argparse.Namespace) -> int:
    emit(inspect_snapshot(Path(args.input)), json_output=args.json)
    return ExitCode.SUCCESS


def _snapshot_import(args: argparse.Namespace) -> int:
    payload = import_snapshot(input_path=Path(args.input), output_path=Path(args.output), replace=args.replace)
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _adapter_list(args: argparse.Namespace) -> int:
    emit(list_adapters(), json_output=args.json)
    return ExitCode.SUCCESS


def _adapter_describe(args: argparse.Namespace) -> int:
    emit(describe_adapter(args.adapter), json_output=args.json)
    return ExitCode.SUCCESS


def _adapter_run(args: argparse.Namespace) -> int:
    if args.output == "-" and args.debug_output == "-":
        raise ValidationError("--output - and --debug-output - cannot both write to stdout")
    try:
        text = read_adapter_input(args.input, stdin_text=sys.stdin.read() if args.input == "-" else None)
        result = run_adapter(args.adapter, text, strict=args.strict)
    except AdapterFailure as exc:
        if args.debug_output:
            write_json_payload(args.debug_output, exc.debug_payload)
        print(f"fieldbook: {exc}", file=sys.stderr)
        return exc.exit_code

    if args.debug_output:
        write_json_payload(args.debug_output, result.debug_payload())
    write_json_payload(args.output, result.manifest)
    if args.output == "-" or args.debug_output == "-":
        return ExitCode.SUCCESS
    emit(result.summary(output=args.output, debug_output=args.debug_output), json_output=args.json)
    return ExitCode.SUCCESS


def _writeback_wandb(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    if args.apply and not args.writer:
        raise ValidationError("--apply requires explicit --writer")
    if args.apply and args.raw_keys and not args.force_target:
        raise ValidationError("--raw-keys requires --force-target for apply-safe target acknowledgement")
    plan = plan_wandb_writeback(
        repo.conn,
        run_ref=args.run,
        metric_patterns=args.metric,
        target_run=args.target_run,
        key_prefix=args.key_prefix,
        raw_keys=args.raw_keys,
        force_target=args.force_target,
        enforce_target_guard=args.apply,
        allow_rewrite=args.allow_rewrite,
    )
    if not args.apply:
        return plan
    writer = writer_from_name(args.writer, fake_fail_fields=args.fake_fail_field)
    return apply_wandb_writeback(repo.conn, plan=plan, writer=writer, first_write_ok=args.first_write_ok)


def _writeback_log(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return wandb_writeback_log(
        repo.conn,
        target_system=args.target_system,
        status=args.status,
        run_id=args.run,
        target_identifier=args.target_identifier,
        origin=args.origin,
        source_entity_id=args.source_entity,
        limit=args.limit,
    )


def _triage_payload(
    conn: sqlite3.Connection,
    status: dict[str, Any],
    doctor: dict[str, Any],
    experiment_id: str,
) -> dict[str, Any]:
    failed_jobs = status["failed_jobs"]
    stale_jobs = status["stale_jobs"]
    debug_notes = status["notes"]["open_debug"]
    actions: list[str] = []
    if failed_jobs:
        actions.append("Inspect failed jobs and attach a debug note with the recovery path.")
    if stale_jobs:
        actions.append("Refresh or reconcile stale queued/running jobs.")
    if debug_notes:
        actions.append("Resolve or update open debug notes.")
    if doctor["issue_count"]:
        actions.append("Run `fieldbook doctor --json` and address reported ledger issues.")
    if not actions:
        actions.append("No urgent triage items found; continue with the next planned analysis step.")
    return {
        "experiment": status["experiment"],
        "failed_jobs": failed_jobs,
        "stale_jobs": stale_jobs,
        "unresolved_debug_notes": debug_notes,
        "key_artifacts": _redacted_artifacts(conn, experiment_id, limit=20),
        "doctor_ok": doctor["ok"],
        "doctor_issue_count": doctor["issue_count"],
        "suggested_next_actions": actions,
    }


def _closeout_payload(
    conn: sqlite3.Connection,
    status: dict[str, Any],
    doctor: dict[str, Any],
    experiment_id: str,
) -> dict[str, Any]:
    failed_count = len(status["failed_jobs"])
    stale_count = len(status["stale_jobs"])
    unresolved_notes = sum(
        len(status["notes"][key])
        for key in ("open_handoffs", "open_next_actions", "open_debug")
    )
    metric_table_count = conn.execute(
        "SELECT COUNT(*) FROM v_artifacts_redacted_v1 WHERE experiment_id = ? AND type = 'metric-table'",
        (experiment_id,),
    ).fetchone()[0]
    decision_count = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
        "AND note_type = 'decision' AND deleted_at IS NULL",
        (experiment_id,),
    ).fetchone()[0]
    items = [
        _checklist_item("doctor", "Doctor clean", bool(doctor["ok"]), f"{doctor['issue_count']} issue(s)"),
        _checklist_item("failed_jobs", "No failed jobs", failed_count == 0, f"{failed_count} failed job(s)"),
        _checklist_item("stale_jobs", "No stale active jobs", stale_count == 0, f"{stale_count} stale job(s)"),
        _checklist_item(
            "unresolved_notes",
            "No open handoff/next-action/debug notes",
            unresolved_notes == 0,
            f"{unresolved_notes} open note(s)",
        ),
        _checklist_item(
            "metric_table_export",
            "Metric-table export present",
            metric_table_count > 0,
            f"{metric_table_count} metric-table artifact(s)",
        ),
        _checklist_item(
            "decision_note",
            "Final decision note present",
            decision_count > 0,
            f"{decision_count} decision note(s)",
        ),
    ]
    return {"experiment": status["experiment"], "items": items, "ready": all(item["ok"] for item in items)}


def _checklist_item(item_id: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": item_id, "label": label, "ok": ok, "detail": detail}


def _redacted_artifacts(conn: sqlite3.Connection, experiment_id: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM v_artifacts_redacted_v1 WHERE experiment_id = ? ORDER BY updated_at DESC, artifact_id DESC LIMIT ?",
        (experiment_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _format_triage_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Fieldbook Triage: {payload['experiment']['name']}", ""]
    lines.append(f"Doctor: {'ok' if payload['doctor_ok'] else 'issues'} ({payload['doctor_issue_count']} issue(s))")
    lines.extend(["", "## Failed Jobs"])
    lines.extend(_job_lines(payload["failed_jobs"]))
    lines.extend(["", "## Stale Jobs"])
    lines.extend(_job_lines(payload["stale_jobs"]))
    lines.extend(["", "## Open Debug Notes"])
    lines.extend(_note_lines(payload["unresolved_debug_notes"]))
    lines.extend(["", "## Key Artifacts"])
    lines.extend(_artifact_lines(payload["key_artifacts"]))
    lines.extend(["", "## Suggested Next Actions"])
    lines.extend(f"- {action}" for action in payload["suggested_next_actions"])
    return "\n".join(lines)


def _workloop_payload(
    *,
    status: dict[str, Any],
    doctor: dict[str, Any],
    resolution: LedgerResolution,
    session_id: str | None,
    session_source: str | None,
    marker_status: str,
    refresh_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    jobs = {
        "active": status["ready"]["active_job_count"],
        "failed": status["job_counts"].get("failed", 0),
        "blockers": status["blocking_failed_jobs"],
        "stale": status["stale_jobs"],
        "submission_in_progress": status["submission_in_progress_jobs"],
        "submission_unknown": status["submission_unknown_jobs"],
        "recovery_in_progress": status["recovery_in_progress_failed_jobs"],
        "recovered_failed": status["recovered_failed_jobs"],
    }
    payload = {
        "experiment": status["experiment"],
        "locality": db_where_payload(resolution),
        "session": {
            "current_session_id": session_id,
            "session_source": session_source,
            "marker_status": marker_status,
        },
        "runs": status["runs"],
        "jobs": jobs,
        "validations": status["validations"],
        "freshness": status["freshness"],
        "notes": status["notes"],
        "doctor": {
            "ok": doctor["ok"],
            "scoped_issue_count": doctor["issue_count"],
            "global_omitted_count": doctor.get("global_omitted_count", 0),
            "issues": doctor["issues"][:20],
        },
        "suggested_next_actions": _workloop_suggested_actions(status=status, doctor=doctor),
    }
    if refresh_payload is not None:
        payload["refresh"] = refresh_payload
    return payload


def _workloop_suggested_actions(*, status: dict[str, Any], doctor: dict[str, Any]) -> list[dict[str, str]]:
    experiment_id = status["experiment"]["id"]
    actions: list[dict[str, str]] = []
    if status["ready"]["active_job_count"]:
        actions.append(
            {
                "label": "Refresh external job state",
                "command": f"fieldbook experiment workloop {experiment_id} --refresh <source> --apply --json",
            }
        )
    if doctor["issue_count"]:
        actions.append(
            {
                "label": "Inspect scoped doctor issues",
                "command": f"fieldbook doctor --experiment {experiment_id} --json",
            }
        )
    if status["freshness"].get("checkpoint_status") in {"missing", "stale"}:
        actions.append(
            {
                "label": "Write experiment checkpoint",
                "command": f"fieldbook experiment workloop {experiment_id} --checkpoint --body-file <handoff.md> --json",
            }
        )
    if not actions:
        actions.append(
            {
                "label": "Continue active experiment work",
                "command": f"fieldbook experiment workloop {experiment_id} --json",
            }
        )
    return actions


def _format_workloop_markdown(payload: dict[str, Any]) -> str:
    experiment = payload["experiment"]
    lines = [
        f"# Fieldbook Workloop: {experiment['name']}",
        "",
        f"- Experiment: `{experiment['id']}`",
        f"- Runs: `{payload['runs']['total']}`",
        f"- Active jobs: `{payload['jobs']['active']}`",
        f"- Doctor issues: `{payload['doctor']['scoped_issue_count']}`",
        f"- Omitted global issues: `{payload['doctor']['global_omitted_count']}`",
        f"- Checkpoint status: `{payload['freshness'].get('checkpoint_status')}`",
        "",
        "## Suggested Next Actions",
        "",
    ]
    for action in payload["suggested_next_actions"]:
        lines.append(f"- {action['label']}: `{action['command']}`")
    if payload["doctor"]["issues"]:
        lines.extend(["", "## Scoped Doctor Issues", ""])
        for issue in payload["doctor"]["issues"][:10]:
            lines.append(f"- `{issue['code']}` {issue['message']}")
    return "\n".join(lines)


def _format_closeout_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Fieldbook Closeout Checklist: {payload['experiment']['name']}", ""]
    for item in payload["items"]:
        mark = "x" if item["ok"] else " "
        lines.append(f"- [{mark}] {item['label']} ({item['detail']})")
    return "\n".join(lines)


def _job_lines(jobs: list[dict[str, Any]]) -> list[str]:
    if not jobs:
        return ["- none"]
    return [f"- `{job['id']}` {job.get('name') or '(unnamed)'}: {job['status']}" for job in jobs]


def _note_lines(notes: list[dict[str, Any]]) -> list[str]:
    if not notes:
        return ["- none"]
    return [f"- `{note['id']}` {note.get('title') or note['note_type']}" for note in notes]


def _artifact_lines(artifacts: list[dict[str, Any]]) -> list[str]:
    if not artifacts:
        return ["- none"]
    return [
        f"- `{artifact['artifact_id']}` {artifact['type']}: {artifact['display_uri']}"
        for artifact in artifacts
    ]


def _experiment_create(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.create_experiment(
        name=args.name,
        description=args.description,
        tags=args.tag,
        attrs=parse_attrs(args.attr),
        idempotency_key=args.idempotency_key,
    )


def _experiment_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    rows = repo.list_experiments(tag=args.tag, include_archived=args.include_archived)
    return [_compact_experiment(row) if not args.verbose else row for row in rows]


def _experiment_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.get_experiment(args.experiment)


def _experiment_status(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.experiment_status(args.experiment, stale_hours=args.stale_hours)


def _experiment_context(args: argparse.Namespace, repo: Repository) -> dict[str, Any] | str:
    context = repo.experiment_context(args.experiment, stale_hours=args.stale_hours)
    if args.json:
        return context
    return _format_experiment_context_markdown(context)


def _experiment_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_experiment(args.experiment)


def _experiment_checkpoint(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.checkpoint_experiment(
        args.experiment,
        body=_resolve_optional_body(args),
        archive=args.archive,
        errata=args.errata,
        stale_hours=args.stale_hours,
    )


def _experiment_cleanup(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.cleanup_experiment(args.experiment, apply=args.apply)


def _run_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_run(
        name=args.name,
        description=args.description,
        experiment_ref=args.experiment,
        status=args.status,
        kind=args.kind,
        idempotency_key=args.idempotency_key,
        external_system=args.external_system,
        external_id=args.external_id,
        parent_run_ref=args.parent_run,
        attrs=parse_attrs(args.attr),
        update_existing=args.update_existing,
    )


def _run_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    rows = repo.list_runs(experiment_ref=args.experiment, include_archived=args.include_archived)
    return [_compact_run(row) if not args.verbose else row for row in rows]


def _run_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.get_run(args.run)


def _run_link(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.link_run(run_ref=args.run, experiment_ref=args.experiment)


def _run_link_job(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.link_job_run(
        run_ref=args.run,
        job_ref=args.job,
        role=args.role,
        status=args.status,
        failure_reason=args.failure_reason,
        started_at=args.started_at,
        finished_at=args.finished_at,
        attrs=parse_attrs(args.attr),
    )


def _run_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_run(args.run)


def _job_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_job(
        experiment_ref=args.experiment,
        run_ref=args.run,
        name=args.name,
        status=args.status,
        command=args.command,
        launcher=args.launcher,
        external_system=args.external_system,
        external_id=args.external_id,
        failure_reason=args.failure_reason,
        started_at=args.started_at,
        finished_at=args.finished_at,
        retry_of_ref=args.retry_of,
        attrs=parse_attrs(args.attr),
        update_existing=args.update_existing,
    )


def _job_update_status(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.update_job_status(
        job_ref=args.job,
        status=args.status,
        failure_reason=args.failure_reason,
        started_at=args.started_at,
        finished_at=args.finished_at,
        external_system=args.external_system,
        external_id=args.external_id,
    )


def _job_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    rows = repo.list_jobs(
        experiment_ref=args.experiment,
        run_ref=args.run,
        status=args.status,
        include_archived=args.include_archived,
    )
    return [_compact_job(row) if not args.verbose else row for row in rows]


def _job_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.get_job(args.job)


def _job_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_job(args.job)


def _job_link_retry(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.link_job_retry(job_ref=args.job, retry_of_ref=args.retry_of)


def _artifact_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_artifact(
        experiment_ref=args.experiment,
        run_ref=args.run,
        job_ref=args.job,
        artifact_type=args.type,
        uri=args.uri,
        content_hash=args.content_hash,
        attrs=parse_attrs(args.attr),
        update_existing=args.update_existing,
        errata=args.errata,
    )


def _artifact_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    rows = repo.list_artifacts(
        experiment_ref=args.experiment,
        run_ref=args.run,
        job_ref=args.job,
        artifact_type=args.type,
        include_archived=args.include_archived,
    )
    return [_compact_artifact(row) if not args.verbose else row for row in rows]


def _artifact_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.get_artifact(args.artifact)


def _artifact_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_artifact(args.artifact)


def _artifact_refresh_local(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.refresh_local_artifact(args.artifact, update_hash=args.update_hash)


def _validation_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_validation(
        entity_type=args.entity_type,
        entity_ref=args.entity_id,
        check_name=args.check_name,
        status=args.status,
        expected_value=args.expected_value,
        measured_value=args.measured_value,
        details=_parse_json_object(args.details_json, "--details-json"),
        source_artifact_ref=args.source_artifact,
        source_job_ref=args.source_job,
        attrs=parse_attrs(args.attr),
        errata=args.errata,
    )


def _validation_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    return repo.list_validations(
        entity_type=args.entity_type,
        entity_ref=args.entity_id,
        status=args.status,
        include_archived=args.include_archived,
    )


def _validation_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.get_validation(args.validation)


def _validation_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_validation(args.validation)


def _metric_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_metric(
        run_ref=args.run,
        metric_name=args.name,
        value=validate_metric_value(args.value),
        step=args.step,
        split=args.split,
        source_job_ref=args.source_job,
        source_artifact_ref=args.source_artifact,
    )


def _metric_import_csv(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    rows = repo.import_metrics_csv(Path(args.path))
    return {"imported": len(rows), "metrics": rows}


def _metric_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    return repo.list_metrics(
        run_ref=args.run,
        metric_name=args.name,
        include_archived=args.include_archived,
    )


def _metric_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_metric(args.metric)


def _note_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    body = _resolve_note_body(args)
    return repo.add_note(
        entity_type=args.entity_type,
        entity_ref=args.entity_id,
        note_type=args.type,
        status=args.status,
        title=args.title,
        body=body,
        body_format=args.body_format,
        author=args.author,
        attrs=parse_attrs(args.attr),
        errata=args.errata,
    )


def _note_list(args: argparse.Namespace, repo: Repository) -> list[dict[str, Any]]:
    rows = repo.list_notes(
        entity_type=args.entity_type,
        entity_ref=args.entity_id,
        note_type=args.type,
        status=args.status,
        include_archived=args.include_archived,
    )
    return [_compact_note(row) if not args.verbose else row for row in rows]


def _note_resolve(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.resolve_note(args.note)


def _note_show(args: argparse.Namespace, repo: Repository) -> dict[str, Any] | str:
    note = repo.get_note(args.note)
    if args.json:
        return note
    return _format_note_markdown(note)


def _note_archive(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.archive_note(args.note)


def _session_start(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    resolution = args._fieldbook_resolution
    session = repo.start_session(
        experiment_ref=args.experiment,
        agent=args.agent,
        intent=args.intent,
        attrs=parse_attrs(args.attr),
        force_archived=args.force_archived,
        **_session_context_fields(resolution),
    )
    marker = _write_session_marker(resolution, session["id"])
    return {"session": session, **marker}


def _session_current(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    resolution = args._fieldbook_resolution
    raw_id, source, marker_status = _resolved_session_id(resolution)
    _marker_id, marker_file_status = _marker_session_id(resolution)
    session = repo.current_session()
    session_status = "missing"
    if raw_id and session is None:
        session_status = "stale"
    if raw_id and session is not None:
        session_status = "ok"
    return {
        "session": session,
        "resolved_session_id": raw_id,
        "resolution_source": source,
        "marker_path": str(session_marker_path(resolution)),
        "marker_status": marker_file_status if source == "FIELDBOOK_SESSION_ID" else marker_status,
        "session_status": session_status,
    }


def _session_switch(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    resolution = args._fieldbook_resolution
    payload = repo.switch_session(
        to_experiment_ref=args.to,
        agent=args.agent,
        intent=args.intent,
        attrs=parse_attrs(args.attr),
        force_archived=args.force_archived,
        **_session_context_fields(resolution),
    )
    payload.update(_write_session_marker(resolution, payload["session"]["id"]))
    return payload


def _session_end(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    resolution = args._fieldbook_resolution
    payload = repo.end_session(session_ref=args.id, force=args.force)
    marker_path = session_marker_path(resolution)
    closed_session = payload.get("session")
    if payload.get("closed") and closed_session is not None:
        marker_id, _marker_status = _marker_session_id(resolution)
        if marker_id == closed_session["id"]:
            try:
                marker_path.unlink()
            except FileNotFoundError:
                pass
        env_id = os.environ.get("FIELDBOOK_SESSION_ID")
        if env_id == closed_session["id"]:
            payload["env_hint"] = "FIELDBOOK_SESSION_ID still points at the closed session; unset it in the parent shell."
    payload["marker_path"] = str(marker_path)
    payload["marker_status"] = "removed" if not marker_path.exists() else "unchanged"
    return payload


def _session_list(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return {
        "sessions": repo.list_sessions(
            experiment_ref=args.experiment,
            agent=args.agent,
            open_only=args.open,
            limit=args.limit,
        )
    }


def _reconcile_file(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    manifest = load_manifest(Path(args.path))
    return reconcile_manifest(
        repo,
        manifest=manifest,
        source=args.source or args.path,
        experiment_ref=args.experiment,
        apply=args.apply,
    )


def _reconcile_log(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return reconcile_log(
        repo.conn,
        event_id=args.event,
        source=args.source,
        since=args.since,
        before=args.before,
        limit=args.limit,
        include_operations=args.operations,
    )


def _refresh_list_sources(args: argparse.Namespace) -> int:
    resolution = resolve_ledger_location(ledger=args.ledger)
    ledger_path = resolution.path
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    payload = list_refresh_sources(ledger_path=ledger_path, config_path=Path(args.config) if args.config else None)
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _refresh_run(args: argparse.Namespace) -> int:
    if bool(args.source) == bool(args.all):
        raise ValidationError("refresh run requires exactly one of --source or --all")
    resolution = resolve_ledger_location(ledger=args.ledger)
    ledger_path = resolution.path
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    conn = connect(ledger_path)
    try:
        session_id, _, _ = _resolved_session_id(resolution)
        repo = Repository(conn, current_session_id=session_id)
        config_path = Path(args.config) if args.config else None
        source_listing = list_refresh_sources(ledger_path=ledger_path, config_path=config_path)
        source_names = [source["name"] for source in source_listing["sources"]] if args.all else [args.source]
        payload = run_refresh(
            repo,
            ledger_path=ledger_path,
            config_path=config_path,
            source_names=source_names,
            experiment_ref=args.experiment,
            apply=args.apply,
        )
        if args.all and not payload.get("all"):
            payload = {"all": True, "results": [payload], "failed": payload.get("status") == "failed"}
    finally:
        conn.close()
    emit(payload, json_output=args.json, text=_format_refresh_result(payload))
    failed = payload.get("failed") or payload.get("status") == "failed"
    return ExitCode.VALIDATION_ERROR if failed else ExitCode.SUCCESS


def _refresh_log(args: argparse.Namespace) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    conn = connect(ledger_path, allow_newer_readonly=True)
    try:
        payload = refresh_log(
            conn,
            source=args.source,
            status=args.status,
            since=args.since,
            before=args.before,
            limit=args.limit,
        )
    finally:
        conn.close()
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _export_metrics_long(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.export_metrics_long(
        experiment_ref=args.experiment,
        output_path=Path(args.output),
        metric_names=_metric_names_from_args(args),
    )


def _export_runs_wide(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.export_runs_wide(
        experiment_ref=args.experiment,
        output_path=Path(args.output),
        metric_names=_metric_names_from_args(args),
    )


def _export_coverage(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    output_path = Path(args.output) if args.output else None
    return repo.export_metric_coverage(
        experiment_ref=args.experiment,
        output_path=output_path,
        metric_names=_metric_names_from_args(args),
    )


def _metric_names_from_args(args: argparse.Namespace) -> list[str] | None:
    names = list(args.metric or [])
    if args.metric_file:
        with Path(args.metric_file).open() as handle:
            names.extend(line.strip() for line in handle if line.strip())
    return names or None


def _compact_experiment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "updated_at": row["updated_at"],
        "tags": row["tags"],
    }


def _compact_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "updated_at": row["updated_at"],
        "experiment_ids": row["experiment_ids"],
    }


def _compact_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "experiment_id": row["experiment_id"],
        "run_id": row["run_id"],
        "retry_of": row.get("retry_of"),
        "updated_at": row["updated_at"],
        "external_id": row["external_id"],
    }


def _compact_artifact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "uri": row["uri"],
        "run_id": row["run_id"],
        "job_id": row["job_id"],
        "updated_at": row["updated_at"],
    }


def _compact_note(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "note_type": row["note_type"],
        "status": row["status"],
        "title": row["title"],
        "body_format": row["body_format"],
        "body_preview": note_body_preview(row["body"]),
        "updated_at": row["updated_at"],
    }


def _parse_json_object(value: str | None, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{label} must decode to an object")
    return parsed


def _resolve_note_body(args: argparse.Namespace) -> str:
    if args.body_file is not None:
        return Path(args.body_file).read_text()
    if args.body_stdin:
        return sys.stdin.read()
    return args.body


def _resolve_optional_body(args: argparse.Namespace) -> str | None:
    if args.body_file is not None:
        return Path(args.body_file).read_text()
    if args.body_stdin:
        return sys.stdin.read()
    return args.body


def _format_note_markdown(note: dict[str, Any]) -> str:
    header = [
        f"id: {note['id']}",
        f"entity: {note['entity_type']}:{note['entity_id']}",
        f"type: {note['note_type']}",
        f"status: {note['status']}",
        f"title: {note['title'] or ''}",
        f"body_format: {note['body_format']}",
        f"updated_at: {note['updated_at']}",
        "---",
        note["body"],
    ]
    return "\n".join(header)


def _format_experiment_context_markdown(context: dict[str, Any]) -> str:
    experiment = context["experiment"]
    sections = [
        f"# Fieldbook Context: {experiment['name']}",
        "",
        "## Summary",
        "",
        f"- Experiment ID: `{experiment['id']}`",
        f"- Status: `{experiment['status']}`",
        f"- Runs: `{context['runs']['total']}`",
        f"- Jobs: `{context['job_counts']}`",
        f"- Ready: `{context['ready']['is_ready']}`",
        f"- Active blockers: `{context['ready']['blocker_count']}`",
        f"- Active jobs: `{context['ready']['active_job_count']}`",
        f"- Submission uncertainty: `{context['ready']['submission_uncertainty_count']}`",
        "",
        "## Run Matrix",
        "",
        _format_run_progress(context["runs"]),
        "",
        "## Jobs",
        "",
        _format_job_list("Blocking failed jobs", context["blocking_failed_jobs"]),
        "",
        _format_job_list("Submission in progress", context["submission_in_progress_jobs"]),
        "",
        _format_job_list("Unknown submissions", context["submission_unknown_jobs"]),
        "",
        _format_job_list("Recovery in progress", context["recovery_in_progress_failed_jobs"]),
        "",
        _format_job_list("Recovered failures", context["recovered_failed_jobs"]),
        "",
        _format_job_list("Stale jobs", context["stale_jobs"]),
        "",
        _format_job_list("Failed jobs", context["failed_jobs"]),
        "",
        "## Validations",
        "",
        _format_validation_summary(context["validations"]),
        "",
        "## Key Artifacts",
        "",
        _format_artifact_list(context["key_artifacts"]),
        "",
    ]
    note_sections = [
        ("Open Handoffs", "open_handoffs"),
        ("Open Next Actions", "open_next_actions"),
        ("Open Debug Notes", "open_debug"),
        ("Recent Research", "recent_research"),
        ("Recent Decisions", "recent_decisions"),
    ]
    for title, key in note_sections:
        sections.extend(["", f"## {title}", "", _format_note_list(context["notes"][key])])
    return "\n".join(sections).rstrip() + "\n"


def _format_job_list(title: str, jobs: list[dict[str, Any]]) -> str:
    if not jobs:
        return f"### {title}\n\n(none)"
    lines = [f"### {title}", ""]
    for job in jobs:
        lines.append(f"- `{job['id']}` {job.get('name') or ''} status=`{job['status']}`")
    return "\n".join(lines)


def _format_run_progress(runs: dict[str, Any]) -> str:
    lines = [
        f"- Total: `{runs['total']}`",
        f"- Expected: `{runs.get('expected')}`",
        f"- Missing expected: `{runs.get('missing_expected_count')}`",
        f"- By phase: `{runs.get('by_phase', {})}`",
        f"- By kind: `{runs.get('by_kind', {})}`",
        f"- Checkpoints: `{runs.get('coverage', {}).get('has_checkpoint', 0)}`",
        f"- Eval artifacts: `{runs.get('coverage', {}).get('has_eval_result', 0)}`",
        f"- Metric coverage: `{runs.get('coverage', {}).get('by_metric', {})}`",
    ]
    failed = runs.get("failed_examples", [])
    if failed:
        lines.append("- Failed examples: " + ", ".join(f"`{row['id']}` {row.get('name') or ''}" for row in failed[:10]))
    return "\n".join(lines)


def _format_artifact_list(artifacts: list[dict[str, Any]]) -> str:
    if not artifacts:
        return "(none)"
    return "\n".join(f"- `{artifact['id']}` {artifact['type']}: {artifact['uri']}" for artifact in artifacts)


def _format_validation_summary(summary: dict[str, Any]) -> str:
    if not summary["rows"]:
        return "(none)"
    lines = [f"- Status: `{summary['status']}`", f"- Total: `{summary['total']}`"]
    for validation in summary["rows"][:10]:
        lines.append(
            f"- `{validation['id']}` {validation['check_name']} status=`{validation['status']}` "
            f"measured=`{validation.get('measured_value') or ''}`"
        )
    return "\n".join(lines)


def _format_refresh_result(payload: dict[str, Any]) -> str:
    if payload.get("all"):
        lines = [f"Fieldbook refresh: {len(payload['results'])} source(s)"]
        for result in payload["results"]:
            lines.append(f"- {result['source']}: {result['status']} at {result['stage']}")
        return "\n".join(lines)
    return (
        f"Fieldbook refresh {payload['source']}: {payload['status']} at {payload['stage']}\n"
        f"snapshot: {payload.get('snapshot_path')}\n"
        f"manifest: {payload.get('manifest_path')}\n"
        f"next: {payload.get('suggested_next_action')}"
    )


def _format_note_list(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "(none)"
    blocks: list[str] = []
    for note in notes:
        title = f" — {note['title']}" if note.get("title") else ""
        blocks.append(
            "\n".join(
                [
                    f"### `{note['id']}`{title}",
                    "",
                    f"- Type: `{note['note_type']}`",
                    f"- Status: `{note['status']}`",
                    f"- Updated: `{note['updated_at']}`",
                    "",
                    note["body"],
                ]
            )
        )
    return "\n\n".join(blocks)


def _session_context_fields(resolution: LedgerResolution) -> dict[str, str | None]:
    commit, _dirty = current_git_revision(resolution.cwd)
    return {
        "cwd": str(resolution.cwd),
        "git_root": str(resolution.git_root) if resolution.git_root else None,
        "git_worktree_dir": str(resolution.git_worktree_dir) if resolution.git_worktree_dir else None,
        "git_branch": resolution.git_branch,
        "git_commit": commit,
    }


def _resolved_session_id(resolution: LedgerResolution) -> tuple[str | None, str | None, str]:
    env_id = os.environ.get("FIELDBOOK_SESSION_ID")
    if env_id:
        return env_id, "FIELDBOOK_SESSION_ID", "env"
    marker_id, marker_status = _marker_session_id(resolution)
    return marker_id, "marker" if marker_id else None, marker_status


def _marker_session_id(resolution: LedgerResolution) -> tuple[str | None, str]:
    marker = session_marker_path(resolution)
    try:
        text = marker.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing"
    if not text.startswith("id: ") or not text.endswith("\n"):
        return None, "malformed"
    session_id = text[4:].strip()
    return (session_id or None), "ok" if session_id else "malformed"


def _write_session_marker(resolution: LedgerResolution, session_id: str) -> dict[str, str]:
    marker = session_marker_path(resolution)
    marker.write_text(f"id: {session_id}\n", encoding="utf-8")
    ensure_marker_gitignore(marker)
    return {"marker_path": str(marker), "marker_status": "ok"}


def _repo_command(command: Command) -> Callable[[argparse.Namespace], int]:
    return lambda args: _with_repo(args, command)


def _common_repo_parser(parser: argparse.ArgumentParser) -> None:
    _add_common_options(parser)


def _add_include_verbose(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--verbose", action="store_true")


def _add_external_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--external-system")
    parser.add_argument("--external-id")
    parser.add_argument("--update-existing", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fieldbook")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a Fieldbook ledger")
    _add_common_options(init_parser)
    init_parser.set_defaults(func=_cmd_init)

    _add_experiment_parsers(subparsers)
    _add_run_parsers(subparsers)
    _add_job_parsers(subparsers)
    _add_artifact_parsers(subparsers)
    _add_metric_parsers(subparsers)
    _add_validation_parsers(subparsers)
    _add_note_parsers(subparsers)
    _add_session_parsers(subparsers)
    _add_reconcile_parsers(subparsers)
    _add_refresh_parsers(subparsers)
    _add_writeback_parsers(subparsers)
    _add_export_parsers(subparsers)
    _add_adapter_parsers(subparsers)
    _add_doctor_parser(subparsers)
    _add_snapshot_parsers(subparsers)
    _add_db_parsers(subparsers)
    _add_sql_parser(subparsers)
    return parser


def _add_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("doctor", help="Audit Fieldbook ledger health")
    _add_common_options(parser)
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--list-checks", action="store_true")
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--stale-session-hours", type=float, default=24.0)
    parser.add_argument("--stale-submitting-hours", type=float, default=1.0)
    parser.add_argument("--stale-unknown-submit-hours", type=float, default=6.0)
    parser.add_argument("--retry-loop-threshold", type=int, default=3)
    parser.add_argument("--stale-refresh-snapshot-days", type=float, default=30.0)
    parser.add_argument("--locality-recent-days", type=float, default=7.0)
    parser.add_argument("--experiment")
    parser.add_argument("--strict", action="store_true")
    parser.set_defaults(func=_cmd_doctor)


def _add_snapshot_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("snapshot", help="Export, inspect, and import full-ledger snapshots")
    commands = parser.add_subparsers(dest="snapshot_command", required=True)

    export = commands.add_parser("export")
    _add_common_options(export)
    export.add_argument("--output", required=True)
    export.add_argument("--replace", action="store_true")
    export.add_argument("--no-metadata", action="store_true")
    export.set_defaults(func=_snapshot_export)

    inspect = commands.add_parser("inspect")
    _add_common_options(inspect)
    inspect.add_argument("--input", required=True)
    inspect.set_defaults(func=_snapshot_inspect)

    import_parser = commands.add_parser("import")
    _add_common_options(import_parser)
    import_parser.add_argument("--input", required=True)
    import_parser.add_argument("--output", required=True)
    import_parser.add_argument("--replace", action="store_true")
    import_parser.set_defaults(func=_snapshot_import)


def _add_adapter_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("adapter", help="Transform refresh snapshots into reconcile manifests")
    commands = parser.add_subparsers(dest="adapter_command", required=True)

    list_parser = commands.add_parser("list")
    _add_common_options(list_parser)
    list_parser.set_defaults(func=_adapter_list)

    describe = commands.add_parser("describe")
    _add_common_options(describe)
    describe.add_argument("adapter")
    describe.set_defaults(func=_adapter_describe)

    run = commands.add_parser("run")
    _add_common_options(run)
    run.add_argument("adapter")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--debug-output")
    run.add_argument("--strict", action="store_true")
    run.set_defaults(func=_adapter_run)


def _add_experiment_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("experiment", help="Manage experiments")
    commands = parser.add_subparsers(dest="experiment_command", required=True)

    create = commands.add_parser("create")
    _common_repo_parser(create)
    create.add_argument("--name", required=True)
    create.add_argument("--description")
    create.add_argument("--tag", action="append", default=[])
    create.add_argument("--idempotency-key")
    _add_attr_option(create)
    create.set_defaults(func=_repo_command(_experiment_create))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--tag")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_experiment_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("experiment")
    show.set_defaults(func=_repo_command(_experiment_show))

    status = commands.add_parser("status")
    _common_repo_parser(status)
    status.add_argument("experiment")
    status.add_argument("--stale-hours", type=float, default=24.0)
    status.set_defaults(func=_repo_command(_experiment_status))

    context = commands.add_parser("context")
    _common_repo_parser(context)
    context.add_argument("experiment")
    context.add_argument("--stale-hours", type=float, default=24.0)
    context.set_defaults(func=_repo_command(_experiment_context))

    workloop = commands.add_parser("workloop")
    _add_common_options(workloop)
    workloop.add_argument("experiment")
    workloop.add_argument("--stale-hours", type=float, default=24.0)
    workloop.add_argument("--refresh", action="append", default=[])
    workloop.add_argument("--refresh-all", action="store_true")
    workloop.add_argument("--config")
    workloop.add_argument("--apply", action="store_true")
    workloop.add_argument("--checkpoint", action="store_true")
    workloop_body_group = workloop.add_mutually_exclusive_group()
    workloop_body_group.add_argument("--body")
    workloop_body_group.add_argument("--body-file")
    workloop_body_group.add_argument("--body-stdin", action="store_true")
    workloop.set_defaults(func=_cmd_experiment_workloop)

    triage = commands.add_parser("triage")
    _add_common_options(triage)
    triage.add_argument("experiment")
    triage.add_argument("--stale-hours", type=float, default=24.0)
    triage.set_defaults(func=_cmd_experiment_triage)

    closeout = commands.add_parser("closeout-checklist")
    _add_common_options(closeout)
    closeout.add_argument("experiment")
    closeout.add_argument("--stale-hours", type=float, default=24.0)
    closeout.set_defaults(func=_cmd_experiment_closeout_checklist)

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("experiment")
    archive.set_defaults(func=_repo_command(_experiment_archive))

    checkpoint = commands.add_parser("checkpoint")
    _common_repo_parser(checkpoint)
    checkpoint.add_argument("experiment")
    body_group = checkpoint.add_mutually_exclusive_group()
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    body_group.add_argument("--body-stdin", action="store_true")
    checkpoint.add_argument("--archive", action="store_true")
    checkpoint.add_argument("--errata", action="store_true")
    checkpoint.add_argument("--stale-hours", type=float, default=24.0)
    checkpoint.set_defaults(func=_repo_command(_experiment_checkpoint))

    cleanup = commands.add_parser("cleanup")
    _common_repo_parser(cleanup)
    cleanup.add_argument("experiment")
    cleanup.add_argument("--apply", action="store_true")
    cleanup.set_defaults(func=_repo_command(_experiment_cleanup))


def _add_run_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("run", help="Manage runs")
    commands = parser.add_subparsers(dest="run_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--name", required=True)
    add.add_argument("--description")
    add.add_argument("--experiment")
    add.add_argument("--parent-run")
    add.add_argument("--status", default="active")
    add.add_argument("--kind", default="datapoint")
    add.add_argument("--idempotency-key")
    _add_external_options(add)
    _add_attr_option(add)
    add.set_defaults(func=_repo_command(_run_add))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--experiment")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_run_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("run")
    show.set_defaults(func=_repo_command(_run_show))

    link = commands.add_parser("link")
    _common_repo_parser(link)
    link.add_argument("run")
    link.add_argument("--experiment", required=True)
    link.set_defaults(func=_repo_command(_run_link))

    link_job = commands.add_parser("link-job")
    _common_repo_parser(link_job)
    link_job.add_argument("--run", required=True)
    link_job.add_argument("--job", required=True)
    link_job.add_argument("--role", required=True)
    link_job.add_argument("--status", required=True)
    link_job.add_argument("--failure-reason")
    link_job.add_argument("--started-at")
    link_job.add_argument("--finished-at")
    _add_attr_option(link_job)
    link_job.set_defaults(func=_repo_command(_run_link_job))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("run")
    archive.set_defaults(func=_repo_command(_run_archive))


def _add_job_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("job", help="Manage jobs")
    commands = parser.add_subparsers(dest="job_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--experiment")
    add.add_argument("--run")
    add.add_argument("--name")
    add.add_argument("--status", default="planned")
    add.add_argument("--command")
    add.add_argument("--launcher")
    add.add_argument("--failure-reason")
    add.add_argument("--started-at")
    add.add_argument("--finished-at")
    add.add_argument("--retry-of")
    _add_external_options(add)
    _add_attr_option(add)
    add.set_defaults(func=_repo_command(_job_add))

    update = commands.add_parser("update-status")
    _common_repo_parser(update)
    update.add_argument("job")
    update.add_argument("--status", required=True)
    update.add_argument("--failure-reason")
    update.add_argument("--started-at")
    update.add_argument("--finished-at")
    _add_external_options(update)
    update.set_defaults(func=_repo_command(_job_update_status))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--experiment")
    list_parser.add_argument("--run")
    list_parser.add_argument("--status")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_job_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("job")
    show.set_defaults(func=_repo_command(_job_show))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("job")
    archive.set_defaults(func=_repo_command(_job_archive))

    link_retry = commands.add_parser("link-retry")
    _common_repo_parser(link_retry)
    link_retry.add_argument("job")
    link_retry.add_argument("--retry-of", required=True)
    link_retry.set_defaults(func=_repo_command(_job_link_retry))


def _add_artifact_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("artifact", help="Manage artifacts")
    commands = parser.add_subparsers(dest="artifact_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--experiment")
    add.add_argument("--run")
    add.add_argument("--job")
    add.add_argument("--type", required=True)
    add.add_argument("--uri", required=True)
    add.add_argument("--content-hash")
    add.add_argument("--update-existing", action="store_true")
    add.add_argument("--errata", action="store_true")
    _add_attr_option(add)
    add.set_defaults(func=_repo_command(_artifact_add))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--experiment")
    list_parser.add_argument("--run")
    list_parser.add_argument("--job")
    list_parser.add_argument("--type")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_artifact_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("artifact")
    show.set_defaults(func=_repo_command(_artifact_show))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("artifact")
    archive.set_defaults(func=_repo_command(_artifact_archive))

    refresh_local = commands.add_parser("refresh-local")
    _common_repo_parser(refresh_local)
    refresh_local.add_argument("artifact")
    refresh_local.add_argument("--update-hash", action="store_true")
    refresh_local.set_defaults(func=_repo_command(_artifact_refresh_local))


def _add_validation_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("validation", help="Manage structured validation checks")
    commands = parser.add_subparsers(dest="validation_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--entity-type", required=True)
    add.add_argument("--entity-id", required=True)
    add.add_argument("--check-name", required=True)
    add.add_argument("--status", required=True)
    add.add_argument("--expected-value")
    add.add_argument("--measured-value")
    add.add_argument("--details-json")
    add.add_argument("--source-artifact")
    add.add_argument("--source-job")
    add.add_argument("--errata", action="store_true")
    _add_attr_option(add)
    add.set_defaults(func=_repo_command(_validation_add))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--entity-type")
    list_parser.add_argument("--entity-id")
    list_parser.add_argument("--status")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_validation_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("validation")
    show.set_defaults(func=_repo_command(_validation_show))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("validation")
    archive.set_defaults(func=_repo_command(_validation_archive))


def _add_metric_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("metric", help="Manage metrics")
    commands = parser.add_subparsers(dest="metric_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--run", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--value", required=True)
    add.add_argument("--step")
    add.add_argument("--split")
    add.add_argument("--source-job")
    add.add_argument("--source-artifact")
    add.set_defaults(func=_repo_command(_metric_add))

    import_csv = commands.add_parser("import-csv")
    _common_repo_parser(import_csv)
    import_csv.add_argument("--path", required=True)
    import_csv.set_defaults(func=_repo_command(_metric_import_csv))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--run")
    list_parser.add_argument("--name")
    list_parser.add_argument("--include-archived", action="store_true")
    list_parser.set_defaults(func=_repo_command(_metric_list))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("metric")
    archive.set_defaults(func=_repo_command(_metric_archive))


def _add_note_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("note", help="Manage notes")
    commands = parser.add_subparsers(dest="note_command", required=True)

    add = commands.add_parser("add")
    _common_repo_parser(add)
    add.add_argument("--entity-type", required=True)
    add.add_argument("--entity-id", required=True)
    add.add_argument("--type", required=True)
    add.add_argument("--status", default="open")
    add.add_argument("--title")
    body_group = add.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    body_group.add_argument("--body-stdin", action="store_true")
    add.add_argument("--body-format", default="markdown", choices=sorted(NOTE_BODY_FORMATS))
    add.add_argument("--author")
    add.add_argument("--errata", action="store_true")
    _add_attr_option(add)
    add.set_defaults(func=_repo_command(_note_add))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--entity-type")
    list_parser.add_argument("--entity-id")
    list_parser.add_argument("--type")
    list_parser.add_argument("--status")
    _add_include_verbose(list_parser)
    list_parser.set_defaults(func=_repo_command(_note_list))

    show = commands.add_parser("show")
    _common_repo_parser(show)
    show.add_argument("note")
    show.set_defaults(func=_repo_command(_note_show))

    resolve = commands.add_parser("resolve")
    _common_repo_parser(resolve)
    resolve.add_argument("note")
    resolve.set_defaults(func=_repo_command(_note_resolve))

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("note")
    archive.set_defaults(func=_repo_command(_note_archive))


def _add_reconcile_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("reconcile", help="Reconcile external manifests")
    commands = parser.add_subparsers(dest="reconcile_command", required=True)

    file_parser = commands.add_parser("file")
    _common_repo_parser(file_parser)
    file_parser.add_argument("--path", required=True)
    file_parser.add_argument("--source")
    file_parser.add_argument("--experiment")
    file_parser.add_argument("--apply", action="store_true")
    file_parser.set_defaults(func=_repo_command(_reconcile_file))

    log_parser = commands.add_parser("log")
    _common_repo_parser(log_parser)
    log_parser.add_argument("--event")
    log_parser.add_argument("--source")
    log_parser.add_argument("--since")
    log_parser.add_argument("--before")
    log_parser.add_argument("--limit", type=int, default=20)
    log_parser.add_argument("--operations", action="store_true")
    log_parser.set_defaults(func=_repo_command(_reconcile_log))


def _add_refresh_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("refresh", help="Refresh external state through snapshots and reconcile")
    commands = parser.add_subparsers(dest="refresh_command", required=True)

    list_sources = commands.add_parser("list-sources")
    _add_common_options(list_sources)
    list_sources.add_argument("--config")
    list_sources.set_defaults(func=_refresh_list_sources)

    run = commands.add_parser("run")
    _add_common_options(run)
    selection = run.add_mutually_exclusive_group()
    selection.add_argument("--source")
    selection.add_argument("--all", action="store_true")
    run.add_argument("--experiment")
    run.add_argument("--config")
    run.add_argument("--apply", action="store_true")
    run.set_defaults(func=_refresh_run)

    log = commands.add_parser("log")
    _add_common_options(log)
    log.add_argument("--source")
    log.add_argument("--status")
    log.add_argument("--since")
    log.add_argument("--before")
    log.add_argument("--limit", type=int, default=20)
    log.set_defaults(func=_refresh_log)


def _add_writeback_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("writeback", help="Push Fieldbook data to external systems")
    commands = parser.add_subparsers(dest="writeback_command", required=True)

    wandb = commands.add_parser("wandb", help="Write Fieldbook metrics to W&B summaries")
    _common_repo_parser(wandb)
    wandb.add_argument("--run", required=True)
    wandb.add_argument("--metric", action="append", required=True)
    wandb.add_argument("--target-run")
    wandb.add_argument("--key-prefix")
    wandb.add_argument("--raw-keys", action="store_true")
    wandb.add_argument("--force-target", action="store_true")
    wandb.add_argument("--allow-rewrite", action="store_true")
    wandb.add_argument("--apply", action="store_true")
    wandb.add_argument("--writer", choices=["fake", "real"])
    wandb.add_argument("--first-write-ok", action="store_true")
    wandb.add_argument("--fake-fail-field", action="append", default=[])
    wandb.set_defaults(func=_repo_command(_writeback_wandb))

    log = commands.add_parser("log", help="Inspect writeback sync events")
    _common_repo_parser(log)
    log.add_argument("--target-system")
    log.add_argument("--status")
    log.add_argument("--run")
    log.add_argument("--target-identifier")
    log.add_argument("--origin")
    log.add_argument("--source-entity")
    log.add_argument("--limit", type=int, default=20)
    log.set_defaults(func=_repo_command(_writeback_log))


def _add_db_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("db", help="Inspect the Fieldbook database")
    commands = parser.add_subparsers(dest="db_command", required=True)

    path = commands.add_parser("path")
    _add_common_options(path)
    path.set_defaults(func=_cmd_db_path)

    where = commands.add_parser("where")
    _add_common_options(where)
    where.set_defaults(func=_cmd_db_where)


def _add_session_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("session", help="Manage advisory agent sessions")
    commands = parser.add_subparsers(dest="session_command", required=True)

    start = commands.add_parser("start")
    _common_repo_parser(start)
    start.add_argument("--experiment")
    start.add_argument("--agent", default="codex")
    start.add_argument("--intent")
    start.add_argument("--force-archived", action="store_true")
    _add_attr_option(start)
    start.set_defaults(func=_repo_command(_session_start))

    switch = commands.add_parser("switch")
    _common_repo_parser(switch)
    switch.add_argument("--to", required=True)
    switch.add_argument("--agent", default="codex")
    switch.add_argument("--intent")
    switch.add_argument("--force-archived", action="store_true")
    _add_attr_option(switch)
    switch.set_defaults(func=_repo_command(_session_switch))

    end = commands.add_parser("end")
    _common_repo_parser(end)
    end.add_argument("--id")
    end.add_argument("--force", action="store_true")
    end.set_defaults(func=_repo_command(_session_end))

    current = commands.add_parser("current")
    _common_repo_parser(current)
    current.set_defaults(func=_repo_command(_session_current))

    list_parser = commands.add_parser("list")
    _common_repo_parser(list_parser)
    list_parser.add_argument("--experiment")
    list_parser.add_argument("--agent")
    list_parser.add_argument("--open", action="store_true")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.set_defaults(func=_repo_command(_session_list))


def _add_sql_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("sql", help="Run safe read-only SQL")
    _add_common_options(parser)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query")
    source.add_argument("--file")
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--format", choices=["json", "ndjson", "csv"], default="json")
    parser.add_argument("--limit", type=int, default=DEFAULT_SQL_LIMIT)
    parser.add_argument("--no-limit", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SQL_TIMEOUT)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    parser.add_argument("--allow-blobs", action="store_true")
    parser.set_defaults(func=_cmd_sql)


def _add_export_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("export", help="Export metric tables")
    commands = parser.add_subparsers(dest="export_command", required=True)

    long_parser = commands.add_parser("metrics-long")
    _common_repo_parser(long_parser)
    long_parser.add_argument("--experiment", required=True)
    long_parser.add_argument("--output", required=True)
    _add_metric_selection(long_parser)
    long_parser.set_defaults(func=_repo_command(_export_metrics_long))

    wide = commands.add_parser("runs-wide")
    _common_repo_parser(wide)
    wide.add_argument("--experiment", required=True)
    wide.add_argument("--output", required=True)
    _add_metric_selection(wide)
    wide.set_defaults(func=_repo_command(_export_runs_wide))

    coverage = commands.add_parser("coverage")
    _common_repo_parser(coverage)
    coverage.add_argument("--experiment", required=True)
    coverage.add_argument("--output")
    _add_metric_selection(coverage)
    coverage.set_defaults(func=_repo_command(_export_coverage))


def _add_metric_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--metric", action="append", default=[])
    parser.add_argument("--metric-file")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FieldbookError as exc:
        print(f"fieldbook: {exc}", file=sys.stderr)
        return exc.exit_code
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            print(f"fieldbook: {exc}", file=sys.stderr)
            return LedgerBusyError(str(exc)).exit_code
        raise
    except Exception as exc:
        print(f"fieldbook: internal error: {exc}", file=sys.stderr)
        return ExitCode.INTERNAL_ERROR
