import json
from collections.abc import Iterable, Mapping
from typing import Any


def emit(payload: Any, *, json_output: bool, text: str | None = None) -> None:
    if json_output:
        print(json.dumps(payload, sort_keys=True))
        return
    if text is not None:
        print(text)
        return
    if isinstance(payload, list):
        print_table(payload)
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            print(f"{key}: {value}")
        return
    print(payload)


def print_table(rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        print("(none)")
        return
    keys = list(rows[0].keys())
    widths = {
        key: max(len(str(key)), *(len(_format_value(row.get(key))) for row in rows))
        for key in keys
    }
    print("  ".join(str(key).ljust(widths[key]) for key in keys))
    print("  ".join("-" * widths[key] for key in keys))
    for row in rows:
        print("  ".join(_format_value(row.get(key)).ljust(widths[key]) for key in keys))


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    text = str(value).replace("\n", "\\n")
    if len(text) > 100:
        return text[:99] + "…"
    return text


def compact_count_rows(counts: Mapping[str, int]) -> list[dict[str, Any]]:
    return [{"key": key, "count": value} for key, value in sorted(counts.items())]
