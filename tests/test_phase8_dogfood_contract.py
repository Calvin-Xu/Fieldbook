import json
import re
from pathlib import Path


DOGFOOD_DIR = Path("openspec/changes/marin-dogfood-stabilization/dogfood")
ALLOWED_DISPOSITIONS = {"fix-in-phase", "follow-on-spec", "dashboard-prerequisite", "wontfix"}
PRIVATE_PATTERNS = [
    re.compile(r"/Users/[^`\s]+"),
    re.compile(r"/home/[^`\s]+"),
    re.compile(r"wandb\.ai/", re.IGNORECASE),
    re.compile(r"gs://", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"bearer\s+", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
REQUIRED_REPORT_HEADINGS = [
    "## Summary",
    "## Provenance",
    "## Ledger Contents",
    "## Exercised Workflows",
    "## Doctor",
    "## Snapshot",
    "## Exports",
    "## Findings",
    "## Interpretation",
]


def test_dogfood_issue_list_schema_and_redaction():
    issues = json.loads((DOGFOOD_DIR / "issues.json").read_text())
    assert issues["envelope_version"] == 1
    assert issues["items"]

    for item in issues["items"]:
        assert {"id", "title", "evidence", "proposed_shape", "disposition"}.issubset(item)
        assert item["disposition"] in ALLOWED_DISPOSITIONS
        if item["disposition"] == "fix-in-phase":
            assert item.get("fixed_by_commit")

    raw = (DOGFOOD_DIR / "issues.json").read_text() + (DOGFOOD_DIR / "report.md").read_text()
    for pattern in PRIVATE_PATTERNS:
        assert not pattern.search(raw)


def test_dogfood_report_shape_and_redaction():
    report = (DOGFOOD_DIR / "report.md").read_text()
    for heading in REQUIRED_REPORT_HEADINGS:
        assert heading in report

    for pattern in PRIVATE_PATTERNS:
        assert not pattern.search(report)


def test_dogfood_spec_uses_placeholder_checkout_paths():
    spec_text = "\n".join(
        path.read_text()
        for path in Path("openspec/changes/marin-dogfood-stabilization").rglob("*.md")
    )
    assert "/Users/" not in spec_text
    assert "/home/" not in spec_text
    assert "<FIELDBOOK_CHECKOUT>" in spec_text
