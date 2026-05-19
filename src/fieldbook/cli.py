import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from fieldbook.db import connect, discover_ledger, init_ledger, resolve_init_path
from fieldbook.errors import ExitCode, FieldbookError, LedgerBusyError, NotFoundError, ValidationError
from fieldbook.output import emit
from fieldbook.repository import Repository, note_body_preview
from fieldbook.reconcile import load_manifest, reconcile_log, reconcile_manifest
from fieldbook.validation import NOTE_BODY_FORMATS, parse_attrs, validate_metric_value


Command = Callable[[argparse.Namespace, Repository], Any]


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", help="Path to Fieldbook ledger")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")


def _add_attr_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--attr", action="append", default=[], help="Namespaced key=value custom attribute")


def _with_repo(args: argparse.Namespace, command: Command) -> int:
    ledger_path = discover_ledger(ledger=args.ledger)
    if ledger_path is None:
        raise NotFoundError("Fieldbook ledger not found; run `fieldbook init` first")
    conn = connect(ledger_path, allow_newer_readonly=_is_read_only(args))
    try:
        repo = Repository(conn)
        payload = command(args, repo)
    finally:
        conn.close()
    emit(payload, json_output=args.json)
    return ExitCode.SUCCESS


def _is_read_only(args: argparse.Namespace) -> bool:
    command = getattr(args, "command", None)
    if command == "experiment":
        return getattr(args, "experiment_command", None) in {"list", "show", "status", "context"}
    if command == "run":
        return getattr(args, "run_command", None) in {"list", "show"}
    if command == "job":
        return getattr(args, "job_command", None) in {"list", "show"}
    if command == "artifact":
        return getattr(args, "artifact_command", None) in {"list", "show"}
    if command == "metric":
        return getattr(args, "metric_command", None) == "list"
    if command == "note":
        return getattr(args, "note_command", None) in {"list", "show"}
    if command == "reconcile":
        return getattr(args, "reconcile_command", None) == "log" or (
            getattr(args, "reconcile_command", None) == "file" and not getattr(args, "apply", False)
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


def _experiment_create(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.create_experiment(
        name=args.name,
        description=args.description,
        tags=args.tag,
        attrs=parse_attrs(args.attr),
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


def _run_add(args: argparse.Namespace, repo: Repository) -> dict[str, Any]:
    return repo.add_run(
        name=args.name,
        description=args.description,
        experiment_ref=args.experiment,
        status=args.status,
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


def _resolve_note_body(args: argparse.Namespace) -> str:
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
        f"- Runs: `{context['run_count']}`",
        f"- Jobs: `{context['job_counts']}`",
        "",
        "## Jobs",
        "",
        _format_job_list("Stale jobs", context["stale_jobs"]),
        "",
        _format_job_list("Failed jobs", context["failed_jobs"]),
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


def _format_artifact_list(artifacts: list[dict[str, Any]]) -> str:
    if not artifacts:
        return "(none)"
    return "\n".join(f"- `{artifact['id']}` {artifact['type']}: {artifact['uri']}" for artifact in artifacts)


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
    _add_note_parsers(subparsers)
    _add_reconcile_parsers(subparsers)
    _add_export_parsers(subparsers)
    return parser


def _add_experiment_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("experiment", help="Manage experiments")
    commands = parser.add_subparsers(dest="experiment_command", required=True)

    create = commands.add_parser("create")
    _common_repo_parser(create)
    create.add_argument("--name", required=True)
    create.add_argument("--description")
    create.add_argument("--tag", action="append", default=[])
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

    archive = commands.add_parser("archive")
    _common_repo_parser(archive)
    archive.add_argument("experiment")
    archive.set_defaults(func=_repo_command(_experiment_archive))


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
