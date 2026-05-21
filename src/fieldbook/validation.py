import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fieldbook.errors import ValidationError


JOB_STATUSES = {
    "planned",
    "submitting",
    "unknown_submit",
    "queued",
    "running",
    "succeeded",
    "failed",
    "killed",
    "skipped",
    "unknown",
}
EXPERIMENT_STATUSES = {"active", "archived"}
RUN_STATUSES = {"active", "archived"}
ARTIFACT_TYPES = {
    "checkpoint",
    "eval-result",
    "metric-table",
    "validation-report",
    "plot",
    "report",
    "log",
    "wandb-run",
    "manifest",
    "other",
}
NOTE_TYPES = {"research", "debug", "handoff", "next-action", "decision", "checkpoint"}
NOTE_STATUSES = {"open", "resolved", "superseded"}
NOTE_BODY_FORMATS = {"markdown", "plain"}
SYNC_EVENT_STATUSES = {"pending", "synced", "failed", "skipped"}
ENTITY_TYPES = {"experiment", "run", "job", "artifact", "metric"}
VALIDATION_STATUSES = {"pass", "fail", "warning", "unknown"}
MAX_NOTE_TITLE_CHARS = 120
MAX_NOTE_BODY_BYTES = 64 * 1024

UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
ATTR_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def require_choice(value: str, choices: set[str], label: str) -> str:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValidationError(f"invalid {label} {value!r}; expected one of: {allowed}")
    return value


def validate_note_title(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValidationError("note title must not be empty")
    if len(normalized) > MAX_NOTE_TITLE_CHARS:
        raise ValidationError(f"note title must be at most {MAX_NOTE_TITLE_CHARS} characters")
    return normalized


def validate_note_body(value: str) -> str:
    if value == "":
        raise ValidationError("note body must not be empty")
    size = len(value.encode("utf-8"))
    if size > MAX_NOTE_BODY_BYTES:
        raise ValidationError(
            f"note body is {size} bytes; store material over {MAX_NOTE_BODY_BYTES} bytes as an artifact"
        )
    return value


def validate_utc_z(value: str | None, label: str = "timestamp") -> str | None:
    if value is None:
        return None
    if not UTC_Z_RE.match(value):
        raise ValidationError(f"{label} must be a UTC timestamp ending in Z")
    normalized = value[:-1] + "+00:00"
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(f"{label} is not a valid ISO timestamp: {value}") from exc
    return value


def validate_content_hash(value: str | None) -> str | None:
    if value is None:
        return None
    if not SHA256_RE.match(value):
        raise ValidationError("content hash must match sha256:<64 hex characters>")
    return value.lower()


def validate_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not IDEMPOTENCY_KEY_RE.match(value):
        raise ValidationError("idempotency key must match ^[a-z0-9][a-z0-9._-]{0,127}$")
    return value


def parse_attrs(pairs: list[str] | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValidationError(f"attribute must use key=value syntax: {pair!r}")
        key, raw_value = pair.split("=", 1)
        if key.startswith("fieldbook."):
            raise ValidationError("fieldbook.* attributes are reserved")
        if not ATTR_KEY_RE.match(key):
            raise ValidationError(
                f"attribute key {key!r} must be lowercase dotted namespace, e.g. marin.scale"
            )
        attrs[key] = parse_attr_value(raw_value)
    return attrs


def validate_attrs_dict(attrs: dict[str, Any]) -> dict[str, Any]:
    for key in attrs:
        if key.startswith("fieldbook."):
            raise ValidationError("fieldbook.* attributes are reserved")
        if not ATTR_KEY_RE.match(key):
            raise ValidationError(
                f"attribute key {key!r} must be lowercase dotted namespace, e.g. marin.scale"
            )
    return attrs


def parse_attr_value(raw_value: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def attrs_json(attrs: dict[str, Any]) -> str:
    return json.dumps(attrs, sort_keys=True, separators=(",", ":"))


def load_attrs(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValidationError("attrs_json must decode to an object")
    return value


def normalize_tag(tag: str) -> str:
    value = tag.strip().lower()
    if not value:
        raise ValidationError("tag cannot be empty")
    if any(char.isspace() for char in value):
        raise ValidationError("tag cannot contain whitespace")
    return value


def validate_metric_value(raw_value: str) -> float:
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValidationError(f"metric value must be numeric: {raw_value!r}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
