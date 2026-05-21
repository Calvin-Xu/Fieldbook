import json
import shutil
import sqlite3
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fieldbook.adapters import AdapterFailure, run_adapter
from fieldbook.errors import ValidationError
from fieldbook.freshness import drifted_artifacts
from fieldbook.ids import new_id
from fieldbook.reconcile import reconcile_manifest
from fieldbook.repository import Repository
from fieldbook.time_utils import utc_now
from fieldbook.validation import attrs_json, validate_utc_z


DEFAULT_REFRESH_LOG_LIMIT = 20
DEFAULT_COMMAND_TIMEOUT = 300.0


@dataclass(frozen=True)
class RefreshSource:
    name: str
    kind: str
    adapter: str
    description: str
    command: list[str] | None = None
    path: Path | None = None
    timeout: float = DEFAULT_COMMAND_TIMEOUT

    def summary(self) -> dict[str, Any]:
        runnable = bool(self.command) if self.kind == "command" else bool(self.path and self.path.exists())
        return {
            "name": self.name,
            "kind": self.kind,
            "adapter": self.adapter,
            "description": self.description,
            "runnable": runnable,
        }


@dataclass(frozen=True)
class RefreshConfig:
    path: Path
    sources: dict[str, RefreshSource]


def load_refresh_config(*, ledger_path: Path, config_path: Path | None) -> RefreshConfig:
    root = ledger_root(ledger_path)
    path = config_path or root / ".fieldbook" / "refresh.toml"
    if not path.exists():
        raise ValidationError(f"refresh config not found: {path}")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"refresh config is not valid TOML: {path}") from exc
    sources_raw = data.get("sources")
    if not isinstance(sources_raw, dict) or not sources_raw:
        raise ValidationError("refresh config requires at least one [sources.<name>] table")
    sources = {
        name: _source_from_config(name=name, data=source, config_dir=path.parent)
        for name, source in sources_raw.items()
    }
    return RefreshConfig(path=path, sources=sources)


def list_refresh_sources(*, ledger_path: Path, config_path: Path | None) -> dict[str, Any]:
    config = load_refresh_config(ledger_path=ledger_path, config_path=config_path)
    return {
        "config_path": str(config.path),
        "sources": [source.summary() for source in sorted(config.sources.values(), key=lambda item: item.name)],
    }


def run_refresh(
    repo: Repository,
    *,
    ledger_path: Path,
    config_path: Path | None,
    source_names: list[str],
    experiment_ref: str | None,
    apply: bool,
) -> dict[str, Any]:
    config = load_refresh_config(ledger_path=ledger_path, config_path=config_path)
    if not source_names:
        raise ValidationError("refresh run requires --source or --all")
    unknown = [name for name in source_names if name not in config.sources]
    if unknown:
        raise ValidationError(f"unknown refresh source(s): {', '.join(sorted(unknown))}")
    results = [
        _run_one_source(
            repo,
            ledger_path=ledger_path,
            source=config.sources[name],
            experiment_ref=experiment_ref,
            apply=apply,
        )
        for name in source_names
    ]
    if len(results) == 1:
        return results[0]
    return {"all": True, "results": results, "failed": any(result["status"] == "failed" for result in results)}


def refresh_log(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    status: str | None = None,
    since: str | None = None,
    before: str | None = None,
    limit: int = DEFAULT_REFRESH_LOG_LIMIT,
) -> dict[str, Any]:
    params: list[Any] = []
    query = "SELECT * FROM v_refresh_log_v1 WHERE 1=1"
    if source:
        query += " AND source = ?"
        params.append(source)
    if status:
        query += " AND status = ?"
        params.append(status)
    if since:
        validate_utc_z(since, "since")
        query += " AND finished_at >= ?"
        params.append(since)
    if before:
        validate_utc_z(before, "before")
        query += " AND finished_at < ?"
        params.append(before)
    query += " ORDER BY finished_at DESC, refresh_event_id DESC LIMIT ?"
    params.append(limit)
    return {"events": [_event_dict(row) for row in conn.execute(query, params).fetchall()]}


def ledger_root(ledger_path: Path) -> Path:
    resolved = ledger_path.resolve()
    if resolved.parent.name == ".experiments":
        return resolved.parent.parent
    return resolved.parent


def snapshot_dir(ledger_path: Path, source_name: str) -> Path:
    root = ledger_root(ledger_path)
    experiments_dir = root / ".experiments"
    return experiments_dir / "refresh-snapshots" / source_name


def _source_from_config(*, name: str, data: Any, config_dir: Path) -> RefreshSource:
    if not isinstance(data, dict):
        raise ValidationError(f"refresh source {name!r} must be a table")
    kind = _require_string(data, "kind", source=name)
    adapter = _require_string(data, "adapter", source=name)
    description = str(data.get("description", ""))
    timeout = float(data.get("timeout", DEFAULT_COMMAND_TIMEOUT))
    if kind == "command":
        command = data.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            raise ValidationError(f"refresh source {name!r} command must be a non-empty string list")
        return RefreshSource(name=name, kind=kind, adapter=adapter, description=description, command=command, timeout=timeout)
    if kind == "file":
        raw_path = _require_string(data, "path", source=name)
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = config_dir / path
        return RefreshSource(name=name, kind=kind, adapter=adapter, description=description, path=path, timeout=timeout)
    raise ValidationError(f"refresh source {name!r} kind must be 'command' or 'file'")


def _require_string(data: dict[str, Any], key: str, *, source: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"refresh source {source!r} requires non-empty {key}")
    return value


def _run_one_source(
    repo: Repository,
    *,
    ledger_path: Path,
    source: RefreshSource,
    experiment_ref: str | None,
    apply: bool,
) -> dict[str, Any]:
    started_at = utc_now()
    experiment_id = repo.get_experiment(experiment_ref)["id"] if experiment_ref else None
    command_argv = _planned_command(source, experiment_id=experiment_id, ledger_path=ledger_path)
    paths = _refresh_paths(ledger_path=ledger_path, source_name=source.name)
    try:
        _capture_snapshot(source, paths["snapshot"], command_argv=command_argv)
    except Exception as exc:
        _write_json(paths["debug"], {"stage": "helper", "error": str(exc), "command": command_argv})
        return _finalize_refresh(
            repo,
            source=source,
            experiment_id=experiment_id,
            started_at=started_at,
            status="failed",
            stage="helper",
            paths=paths,
            counts={},
            command_argv=command_argv,
            error_message=str(exc),
        )

    try:
        adapter_run = run_adapter(source.adapter, paths["snapshot"].read_text(encoding="utf-8"))
    except AdapterFailure as exc:
        _write_json(paths["debug"], exc.debug_payload)
        return _finalize_refresh(
            repo,
            source=source,
            experiment_id=experiment_id,
            started_at=started_at,
            status="failed",
            stage="adapter",
            paths=paths,
            counts={},
            command_argv=command_argv,
            error_message=str(exc),
        )
    _write_json(paths["manifest"], adapter_run.manifest)
    _write_json(paths["debug"], adapter_run.debug_payload())

    submission_resolutions = _submission_resolutions(repo.conn, adapter_run.manifest, experiment_id=experiment_id)
    drifted = drifted_artifacts(repo.conn, experiment_id=experiment_id, cwd=Path.cwd(), limit=20)
    try:
        reconcile_result = reconcile_manifest(
            repo,
            manifest=adapter_run.manifest,
            source=f"refresh:{source.name}",
            experiment_ref=experiment_id,
            apply=apply,
        )
    except Exception as exc:
        return _finalize_refresh(
            repo,
            source=source,
            experiment_id=experiment_id,
            started_at=started_at,
            status="failed",
            stage="reconcile",
            paths=paths,
            counts={},
            command_argv=command_argv,
            error_message=str(exc),
            submission_resolutions=submission_resolutions,
            drifted_artifacts=drifted,
        )
    reconcile_event_id = None
    if apply:
        reconcile_event_id = reconcile_result["reconcile_event"]["id"]
    return _finalize_refresh(
        repo,
        source=source,
        experiment_id=experiment_id,
        started_at=started_at,
        status="applied" if apply else "dry_run",
        stage="reconcile",
        paths=paths,
        counts=reconcile_result["counts"],
        command_argv=command_argv,
        reconcile_event_id=reconcile_event_id,
        submission_resolutions=submission_resolutions,
        drifted_artifacts=drifted,
    )


def _refresh_paths(*, ledger_path: Path, source_name: str) -> dict[str, Path]:
    directory = snapshot_dir(ledger_path, source_name)
    directory.mkdir(parents=True, exist_ok=True)
    stem = utc_now().replace("-", "").replace(":", "").replace(".", "_") + "-" + new_id("snap").split("_", 1)[1][:8]
    snapshot = directory / f"{stem}.json"
    return {
        "snapshot": snapshot,
        "manifest": snapshot.with_suffix(".manifest.json"),
        "debug": snapshot.with_suffix(".debug.json"),
    }


def _planned_command(source: RefreshSource, *, experiment_id: str | None, ledger_path: Path) -> list[str]:
    if source.command is None:
        return []
    return [
        _replace_placeholders(value, experiment_id=experiment_id, ledger_path=ledger_path, source=source.name)
        for value in source.command
    ]


def _capture_snapshot(source: RefreshSource, snapshot_path: Path, *, command_argv: list[str]) -> None:
    if source.kind == "file":
        if source.path is None or not source.path.exists():
            raise ValidationError(f"refresh file source path does not exist: {source.path}")
        shutil.copyfile(source.path, snapshot_path)
        return
    if not command_argv:
        raise ValidationError(f"refresh command source {source.name!r} has no command")
    result = subprocess.run(command_argv, text=True, capture_output=True, timeout=source.timeout, check=False)
    snapshot_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        raise ValidationError(f"refresh helper exited {result.returncode}: {result.stderr.strip()}")


def _replace_placeholders(value: str, *, experiment_id: str | None, ledger_path: Path, source: str) -> str:
    return (
        value.replace("{experiment_id}", experiment_id or "")
        .replace("{ledger_path}", str(ledger_path))
        .replace("{source}", source)
    )


def _submission_resolutions(
    conn: sqlite3.Connection,
    manifest: dict[str, list[dict[str, Any]]],
    *,
    experiment_id: str | None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, status, external_system, external_id FROM jobs WHERE deleted_at IS NULL "
        "AND status IN ('submitting', 'unknown_submit') "
        "AND (? IS NULL OR experiment_id = ?) ORDER BY updated_at, id",
        (experiment_id, experiment_id),
    ).fetchall()
    manifest_jobs = {row.get("id"): row for row in manifest.get("jobs", []) if row.get("id")}
    resolutions: list[dict[str, Any]] = []
    for row in rows:
        manifest_job = manifest_jobs.get(row["id"])
        resolved_status = str(manifest_job.get("status", row["status"])) if manifest_job else row["status"]
        external_system = _optional_str(manifest_job.get("external_system", row["external_system"])) if manifest_job else row["external_system"]
        external_id = _optional_str(manifest_job.get("external_id", row["external_id"])) if manifest_job else row["external_id"]
        resolutions.append(
            {
                "job_id": row["id"],
                "previous_status": row["status"],
                "resolved_status": resolved_status,
                "external_system": external_system,
                "external_id": external_id,
                "suggested_action": _submission_suggested_action(previous_status=row["status"], resolved_status=resolved_status),
            }
        )
    return resolutions


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _submission_suggested_action(*, previous_status: str, resolved_status: str) -> str:
    if resolved_status != previous_status:
        return "none"
    if previous_status == "submitting":
        return "wait"
    return "mark_failed"


def _finalize_refresh(
    repo: Repository,
    *,
    source: RefreshSource,
    experiment_id: str | None,
    started_at: str,
    status: str,
    stage: str,
    paths: dict[str, Path],
    counts: dict[str, Any],
    command_argv: list[str],
    error_message: str | None = None,
    reconcile_event_id: str | None = None,
    submission_resolutions: list[dict[str, Any]] | None = None,
    drifted_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    finished_at = utc_now()
    event_id = new_id("refresh")
    repo.conn.execute(
        "INSERT INTO refresh_events (id, source, experiment_id, session_id, status, stage, started_at, finished_at, "
        "snapshot_path, manifest_path, debug_path, reconcile_event_id, counts_json, command_argv_json, error_message, "
        "attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            source.name,
            experiment_id,
            repo.current_session_id,
            status,
            stage,
            started_at,
            finished_at,
            str(paths["snapshot"]) if paths["snapshot"].exists() else None,
            str(paths["manifest"]) if paths["manifest"].exists() else None,
            str(paths["debug"]) if paths["debug"].exists() else None,
            reconcile_event_id,
            json.dumps(counts, sort_keys=True),
            json.dumps(command_argv),
            error_message,
            attrs_json({}),
        ),
    )
    repo.conn.commit()
    row = repo.conn.execute("SELECT * FROM v_refresh_log_v1 WHERE refresh_event_id = ?", (event_id,)).fetchone()
    payload = _event_dict(row)
    payload.update(
        {
            "event_id": event_id,
            "counts": counts,
            "submission_resolutions": submission_resolutions or [],
            "drifted_artifacts": drifted_artifacts or [],
            "suggested_next_action": _suggested_next_action(status=status, stage=stage),
            "truncated": False,
        }
    )
    return payload


def _suggested_next_action(*, status: str, stage: str) -> str:
    if status == "failed":
        return {
            "helper": "Inspect the snapshot/debug files and rerun the external helper.",
            "adapter": "Inspect the snapshot and adapter debug payload.",
            "reconcile": "Inspect the manifest and reconcile error, then rerun refresh.",
        }.get(stage, "Inspect refresh debug output.")
    if status == "dry_run":
        return "Inspect the manifest, then rerun with --apply if it is correct."
    return "Run experiment status to inspect readiness."


def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["refresh_event_id"],
        "source": row["source"],
        "experiment_id": row["experiment_id"],
        "session_id": row["session_id"],
        "status": row["status"],
        "stage": row["stage"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "snapshot_path": row["snapshot_path"],
        "manifest_path": row["manifest_path"],
        "debug_path": row["debug_path"],
        "reconcile_event_id": row["reconcile_event_id"],
        "counts": json.loads(row["counts_json"]),
        "command_argv": json.loads(row["command_argv_json"]),
        "error_message": row["error_message"],
        "attrs": json.loads(row["attrs_json"]),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
