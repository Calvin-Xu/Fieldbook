import csv
import io
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fieldbook.errors import ValidationError
from fieldbook.validation import (
    ARTIFACT_TYPES,
    JOB_STATUSES,
    RUN_STATUSES,
    require_choice,
    validate_attrs_dict,
    validate_content_hash,
    validate_utc_z,
)


MANIFEST_VERSION = 1
MANIFEST_SECTIONS = [
    "runs",
    "jobs",
    "artifacts",
    "metrics",
    "notes",
    "validations",
    "custom_attributes",
    "sync_events",
]


class AdapterHandler(Protocol):
    def __call__(self, text: str) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        ...


@dataclass(frozen=True)
class AdapterDescription:
    name: str
    description: str
    input_format: str
    required_fields: list[str]
    optional_fields: list[str]
    coercion_rules: list[str]
    emits: list[str]
    failure_behavior: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_format": self.input_format,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "coercion_rules": self.coercion_rules,
            "emits": self.emits,
            "failure_behavior": self.failure_behavior,
        }


@dataclass(frozen=True)
class Adapter:
    description: AdapterDescription
    handler: AdapterHandler


@dataclass(frozen=True)
class AdapterRun:
    adapter: str
    outcome: str
    input_rows: int
    manifest: dict[str, Any]
    skipped_rows: list[dict[str, Any]]

    def debug_payload(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "outcome": self.outcome,
            "input_rows": self.input_rows,
            "skipped_rows": self.skipped_rows,
            "skipped_count": len(self.skipped_rows),
            "emitted_counts": self.emitted_counts(),
        }

    def emitted_counts(self) -> dict[str, int]:
        return {section: len(self.manifest[section]) for section in MANIFEST_SECTIONS}

    def summary(self, *, output: str, debug_output: str | None) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "outcome": self.outcome,
            "input_rows": self.input_rows,
            "skipped_rows": len(self.skipped_rows),
            "emitted_counts": self.emitted_counts(),
            "output": output,
            "debug_output": debug_output,
        }


class AdapterFailure(ValidationError):
    def __init__(self, message: str, *, debug_payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.debug_payload = debug_payload


def list_adapters() -> list[dict[str, str]]:
    return [
        {"name": name, "description": adapter.description.description}
        for name, adapter in sorted(ADAPTERS.items())
    ]


def describe_adapter(name: str) -> dict[str, Any]:
    return _adapter(name).description.to_dict()


def run_adapter(name: str, text: str, *, strict: bool = False) -> AdapterRun:
    adapter = _adapter(name)
    try:
        input_rows, sections, skipped_rows = adapter.handler(text)
    except AdapterFailure as exc:
        exc.debug_payload["adapter"] = name
        raise
    manifest = canonical_manifest(sections)
    outcome = "partial" if skipped_rows else "clean"
    run = AdapterRun(
        adapter=name,
        outcome=outcome,
        input_rows=input_rows,
        manifest=manifest,
        skipped_rows=skipped_rows,
    )
    if strict and skipped_rows:
        raise AdapterFailure("adapter produced partial coverage in strict mode", debug_payload=run.debug_payload())
    return run


def canonical_manifest(sections: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    manifest: dict[str, Any] = {"manifest_version": MANIFEST_VERSION}
    provided = sections or {}
    for section in MANIFEST_SECTIONS:
        manifest[section] = list(provided.get(section, []))
    return manifest


def read_adapter_input(path: str, *, stdin_text: str | None = None) -> str:
    if path == "-":
        if stdin_text is None:
            raise ValidationError("stdin input was requested but no stdin text was supplied")
        return stdin_text
    return Path(path).read_text(encoding="utf-8")


def write_json_payload(path: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path == "-":
        print(text, end="")
        return
    Path(path).write_text(text, encoding="utf-8")


def _adapter(name: str) -> Adapter:
    adapter = ADAPTERS.get(name)
    if adapter is None:
        raise ValidationError(f"unknown adapter: {name}")
    return adapter


def _json_rows(text: str, *, key: str) -> list[Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _hard_failure(f"input is not valid JSON: {exc}") from exc
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        rows = value.get(key)
        if isinstance(rows, list):
            return rows
    raise _hard_failure(f"JSON input must be a list or an object with a {key!r} list")


def _hard_failure(message: str) -> AdapterFailure:
    return AdapterFailure(
        message,
        debug_payload={
            "adapter": None,
            "outcome": "failed",
            "input_rows": 0,
            "skipped_rows": [{"row_index": None, "severity": "error", "message": message, "source_row": None}],
            "skipped_count": 1,
            "emitted_counts": {section: 0 for section in MANIFEST_SECTIONS},
        },
    )


def _skip(row_index: int | None, message: str, source_row: Any) -> dict[str, Any]:
    return {
        "row_index": row_index,
        "severity": "error",
        "message": message,
        "source_row": source_row,
    }


def _require_dict(row: Any, *, row_index: int, skipped_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        skipped_rows.append(_skip(row_index, "source row must be an object", row))
        return None
    return row


def _require_nonempty(row: dict[str, Any], field: str) -> Any:
    value = row.get(field)
    if not _present(value):
        raise ValueError(f"missing required field {field!r}")
    return value


def _optional_fields(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: row[field] for field in fields if _present(row.get(field))}


def _attrs(row: dict[str, Any], *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs = dict(base or {})
    raw_attrs = row.get("attrs")
    if _present(raw_attrs):
        if not isinstance(raw_attrs, dict):
            raise ValueError("attrs must be an object")
        attrs.update(raw_attrs)
    return validate_attrs_dict(attrs)


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _sync_event(
    *,
    adapter_name: str,
    target_system: str,
    target_identifier: str,
    run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "target_system": target_system,
        "target_identifier": target_identifier,
        "status": "synced",
        "idempotency_key": f"adapter:{adapter_name}:{target_system}:{target_identifier}",
        "attrs": {"adapter.name": adapter_name},
    }
    if run_id:
        event["run_id"] = run_id
    if job_id:
        event["job_id"] = job_id
    return event


def _iris_jobs_json(text: str) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    rows = _json_rows(text, key="jobs")
    jobs: list[dict[str, Any]] = []
    sync_events: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row_index, raw_row in enumerate(rows):
        row = _require_dict(raw_row, row_index=row_index, skipped_rows=skipped_rows)
        if row is None:
            continue
        try:
            external_id = str(_require_nonempty(row, "external_id"))
            status = require_choice(str(_require_nonempty(row, "status")), JOB_STATUSES, "job status")
            started_at = validate_utc_z(row.get("started_at"), "started_at")
            finished_at = validate_utc_z(row.get("finished_at"), "finished_at")
            job = {
                **_optional_fields(
                    row,
                    ["id", "run_id", "experiment_id", "name", "command", "launcher", "failure_reason"],
                ),
                "external_system": "iris",
                "external_id": external_id,
                "status": status,
            }
            if started_at:
                job["started_at"] = started_at
            if finished_at:
                job["finished_at"] = finished_at
            attrs = _attrs(row)
            if attrs:
                job["attrs"] = attrs
            jobs.append(job)
            sync_events.append(
                _sync_event(
                    adapter_name="iris-jobs-json",
                    target_system="iris",
                    target_identifier=external_id,
                    job_id=job.get("id"),
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            skipped_rows.append(_skip(row_index, str(exc), row))
    return len(rows), {"jobs": jobs, "sync_events": sync_events}, skipped_rows


def _wandb_runs_json(text: str) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    rows = _json_rows(text, key="runs")
    runs: list[dict[str, Any]] = []
    sync_events: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row_index, raw_row in enumerate(rows):
        row = _require_dict(raw_row, row_index=row_index, skipped_rows=skipped_rows)
        if row is None:
            continue
        try:
            external_id = str(row.get("external_id") or _require_nonempty(row, "id"))
            name = str(_require_nonempty(row, "name"))
            status = require_choice(str(row.get("status", "active")), RUN_STATUSES, "run status")
            wandb_attrs = {
                f"wandb.{field}": row[field]
                for field in ["url", "project", "entity", "state", "summary"]
                if field in row and _present(row[field])
            }
            run = {
                **_optional_fields(row, ["description", "parent_run_id", "experiment_id"]),
                "external_system": "wandb",
                "external_id": external_id,
                "name": name,
                "status": status,
            }
            attrs = _attrs(row, base=wandb_attrs)
            if attrs:
                run["attrs"] = attrs
            runs.append(run)
            sync_events.append(
                _sync_event(
                    adapter_name="wandb-runs-json",
                    target_system="wandb",
                    target_identifier=external_id,
                    run_id=run.get("id"),
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            skipped_rows.append(_skip(row_index, str(exc), row))
    return len(rows), {"runs": runs, "sync_events": sync_events}, skipped_rows


def _metrics_csv(text: str) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    handle = io.StringIO(text)
    reader = csv.DictReader(handle)
    required = {"run_id", "metric_name", "value"}
    fieldnames = set(reader.fieldnames or [])
    if not fieldnames:
        raise _hard_failure("CSV input requires a header row")
    if "metric_name" not in fieldnames or "value" not in fieldnames:
        raise _hard_failure("CSV input requires metric_name and value columns")
    metrics: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    input_rows = 0
    for row_index, row in enumerate(reader):
        input_rows += 1
        try:
            if not required.issubset({field for field, value in row.items() if _present(value)}):
                raise ValueError("metric rows require run_id, metric_name, and value; external IDs are not resolved")
            value = float(row["value"])
            if not math.isfinite(value):
                raise ValueError("metric value must be a finite float")
            metric = {
                "run_id": row["run_id"],
                "metric_name": row["metric_name"],
                "value": value,
            }
            for field in ["step", "split", "source_job_id", "source_artifact_id"]:
                if _present(row.get(field)):
                    metric[field] = row[field]
            metrics.append(metric)
        except (TypeError, ValueError) as exc:
            skipped_rows.append(_skip(row_index, str(exc), dict(row)))
    return input_rows, {"metrics": metrics}, skipped_rows


def _artifacts_json(text: str) -> tuple[int, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    rows = _json_rows(text, key="artifacts")
    artifacts: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    owner_fields = ["experiment_id", "run_id", "job_id"]
    for row_index, raw_row in enumerate(rows):
        row = _require_dict(raw_row, row_index=row_index, skipped_rows=skipped_rows)
        if row is None:
            continue
        try:
            artifact_type = require_choice(str(_require_nonempty(row, "type")), ARTIFACT_TYPES, "artifact type")
            uri = str(_require_nonempty(row, "uri"))
            owners = _optional_fields(row, owner_fields)
            if not owners:
                raise ValueError("artifact rows require experiment_id, run_id, or job_id")
            content_hash = validate_content_hash(row.get("content_hash"))
            artifact = {
                **_optional_fields(row, ["id"]),
                **owners,
                "type": artifact_type,
                "uri": uri,
            }
            if content_hash:
                artifact["content_hash"] = content_hash
            attrs = _attrs(row)
            if attrs:
                artifact["attrs"] = attrs
            artifacts.append(artifact)
        except (TypeError, ValueError, ValidationError) as exc:
            skipped_rows.append(_skip(row_index, str(exc), row))
    return len(rows), {"artifacts": artifacts}, skipped_rows


ADAPTERS: dict[str, Adapter] = {
    "artifacts-json": Adapter(
        description=AdapterDescription(
            name="artifacts-json",
            description="Transform local artifact JSON into reconcile artifacts.",
            input_format="JSON list or object with artifacts list",
            required_fields=["type", "uri", "one of experiment_id/run_id/job_id"],
            optional_fields=["id", "content_hash", "attrs"],
            coercion_rules=["artifact type must be a Fieldbook artifact type", "content_hash must match sha256:<hex>"],
            emits=["artifacts"],
            failure_behavior=["malformed rows are skipped", "hard JSON parse failures emit no manifest"],
        ),
        handler=_artifacts_json,
    ),
    "iris-jobs-json": Adapter(
        description=AdapterDescription(
            name="iris-jobs-json",
            description="Transform pre-exported Iris job summary JSON into reconcile jobs.",
            input_format="JSON list or object with jobs list",
            required_fields=["external_id", "status"],
            optional_fields=[
                "id",
                "run_id",
                "experiment_id",
                "name",
                "command",
                "launcher",
                "failure_reason",
                "started_at",
                "finished_at",
                "attrs",
            ],
            coercion_rules=[
                "status must be a Fieldbook job status",
                "timestamps must be UTC Z strings",
                "attrs keys must be lowercase dotted names",
            ],
            emits=["jobs", "sync_events"],
            failure_behavior=["malformed rows are skipped", "hard JSON parse failures emit no manifest"],
        ),
        handler=_iris_jobs_json,
    ),
    "metrics-csv": Adapter(
        description=AdapterDescription(
            name="metrics-csv",
            description="Transform local metric CSV snapshots into reconcile metrics.",
            input_format="UTF-8 CSV with a header row",
            required_fields=["run_id", "metric_name", "value"],
            optional_fields=["step", "split", "source_job_id", "source_artifact_id"],
            coercion_rules=[
                "value must parse as a finite float",
                "step is preserved as a string",
                "run_id must be a ledger run ID; external run IDs are not resolved",
            ],
            emits=["metrics"],
            failure_behavior=["malformed rows are skipped", "header parse failures emit no manifest"],
        ),
        handler=_metrics_csv,
    ),
    "wandb-runs-json": Adapter(
        description=AdapterDescription(
            name="wandb-runs-json",
            description="Transform pre-exported W&B run metadata JSON into reconcile runs.",
            input_format="JSON list or object with runs list",
            required_fields=["id or external_id", "name"],
            optional_fields=["description", "status", "url", "project", "entity", "state", "summary", "attrs"],
            coercion_rules=[
                "status, if supplied, must be a Fieldbook run status",
                "W&B state is stored as wandb.state attr",
                "W&B metadata is stored as namespaced attrs",
            ],
            emits=["runs", "sync_events"],
            failure_behavior=["malformed rows are skipped", "hard JSON parse failures emit no manifest"],
        ),
        handler=_wandb_runs_json,
    ),
}
