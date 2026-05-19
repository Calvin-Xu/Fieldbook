import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fieldbook.errors import NotFoundError, ValidationError


DEFAULT_LEDGER_RELATIVE_PATH = Path(".experiments") / "ledger.sqlite"
FIELDBOOK_CONFIG_NAME = ".fieldbook"
SESSION_MARKER_NAME = ".fieldbook.session"


@dataclass(frozen=True)
class LedgerResolution:
    path: Path | None
    resolved_via: str | None
    cwd: Path
    git_root: Path | None
    git_worktree_dir: Path | None
    git_branch: str | None
    marker_root: Path
    config_path: Path | None = None
    would_init_at: Path | None = None


def parents_inclusive(path: Path) -> list[Path]:
    resolved = path.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    return [resolved, *resolved.parents]


def find_git_root(start: Path) -> Path | None:
    for candidate in parents_inclusive(start):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_init_location(
    start: Path | None = None,
    ledger: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> LedgerResolution:
    resolution = resolve_ledger_location(start=start, ledger=ledger, env=env, require_exists=False)
    if resolution.path is not None:
        return resolution
    assert resolution.would_init_at is not None
    return LedgerResolution(
        path=resolution.would_init_at,
        resolved_via="cwd-walk",
        cwd=resolution.cwd,
        git_root=resolution.git_root,
        git_worktree_dir=resolution.git_worktree_dir,
        git_branch=resolution.git_branch,
        marker_root=_marker_root_for_ledger(resolution.would_init_at),
        would_init_at=resolution.would_init_at,
    )


def resolve_ledger_location(
    start: Path | None = None,
    ledger: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    *,
    require_exists: bool = True,
) -> LedgerResolution:
    env = os.environ if env is None else env
    cwd = (Path.cwd() if start is None else start).resolve()
    git_root = find_git_root(cwd)
    git_worktree_dir = git_root
    git_branch = _git_branch(git_root)

    if ledger is not None:
        path = Path(ledger).expanduser().resolve()
        _require_existing_ledger(path, require_exists=require_exists)
        return LedgerResolution(
            path=path,
            resolved_via="--ledger",
            cwd=cwd,
            git_root=git_root,
            git_worktree_dir=git_worktree_dir,
            git_branch=git_branch,
            marker_root=_marker_root_for_ledger(path),
        )

    env_ledger = env.get("FIELDBOOK_LEDGER")
    if env_ledger:
        path = Path(env_ledger).expanduser().resolve()
        _require_existing_ledger(path, require_exists=require_exists)
        return LedgerResolution(
            path=path,
            resolved_via="FIELDBOOK_LEDGER",
            cwd=cwd,
            git_root=git_root,
            git_worktree_dir=git_worktree_dir,
            git_branch=git_branch,
            marker_root=_marker_root_for_ledger(path),
        )

    config_path = _find_fieldbook_config(cwd)
    if config_path is not None:
        path = _read_fieldbook_ledger(config_path)
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
        else:
            path = path.resolve()
        _require_existing_ledger(path, require_exists=require_exists)
        return LedgerResolution(
            path=path,
            resolved_via=".fieldbook",
            cwd=cwd,
            git_root=git_root,
            git_worktree_dir=git_worktree_dir,
            git_branch=git_branch,
            marker_root=config_path.parent.resolve(),
            config_path=config_path,
        )

    for candidate in parents_inclusive(cwd):
        path = candidate / DEFAULT_LEDGER_RELATIVE_PATH
        if path.exists():
            return LedgerResolution(
                path=path.resolve(),
                resolved_via="cwd-walk",
                cwd=cwd,
                git_root=git_root,
                git_worktree_dir=git_worktree_dir,
                git_branch=git_branch,
                marker_root=candidate.resolve(),
            )

    would_init_root = git_root or cwd
    would_init_at = (would_init_root / DEFAULT_LEDGER_RELATIVE_PATH).resolve()
    if require_exists:
        raise NotFoundError("no Fieldbook ledger found; run `fieldbook init` first")
    return LedgerResolution(
        path=None,
        resolved_via=None,
        cwd=cwd,
        git_root=git_root,
        git_worktree_dir=git_worktree_dir,
        git_branch=git_branch,
        marker_root=would_init_root.resolve(),
        would_init_at=would_init_at,
    )


def session_marker_path(resolution: LedgerResolution) -> Path:
    return resolution.marker_root / SESSION_MARKER_NAME


def ledger_id(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'ledger_id'").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None
    return str(row[0]) if row else None


def db_where_payload(resolution: LedgerResolution) -> dict[str, str | int | None]:
    return {
        "envelope_version": 1,
        "ledger_path": str(resolution.path) if resolution.path is not None else None,
        "ledger_id": ledger_id(resolution.path) if resolution.path is not None else None,
        "cwd": str(resolution.cwd),
        "git_root": str(resolution.git_root) if resolution.git_root is not None else None,
        "git_worktree_dir": str(resolution.git_worktree_dir) if resolution.git_worktree_dir is not None else None,
        "git_branch": resolution.git_branch,
        "resolved_via": resolution.resolved_via,
        "would_init_at": str(resolution.would_init_at) if resolution.path is None and resolution.would_init_at else None,
    }


def ensure_marker_gitignore(marker_path: Path) -> None:
    gitignore = marker_path.parent / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if SESSION_MARKER_NAME in existing:
        return
    with gitignore.open("a", encoding="utf-8") as handle:
        if existing and existing[-1] != "":
            handle.write("\n")
        handle.write(f"{SESSION_MARKER_NAME}\n")


def _find_fieldbook_config(cwd: Path) -> Path | None:
    for candidate in parents_inclusive(cwd):
        config = candidate / FIELDBOOK_CONFIG_NAME
        if config.exists():
            return config.resolve()
    return None


def _read_fieldbook_ledger(config_path: Path) -> Path:
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValidationError(f"cannot read .fieldbook config: {config_path}") from exc
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValidationError(f"malformed .fieldbook config line: {raw_line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key != "ledger":
            raise ValidationError(f"unsupported .fieldbook key: {key}")
        if not value:
            raise ValidationError(".fieldbook ledger value must not be empty")
        values[key] = value
    if "ledger" not in values:
        raise ValidationError(".fieldbook config requires a ledger key")
    return Path(values["ledger"]).expanduser()


def _require_existing_ledger(path: Path, *, require_exists: bool) -> None:
    if require_exists and not path.exists():
        raise NotFoundError(f"Fieldbook ledger not found: {path}")


def _marker_root_for_ledger(path: Path) -> Path:
    if path.name == "ledger.sqlite" and path.parent.name == ".experiments":
        return path.parent.parent.resolve()
    return path.parent.resolve()


def _git_branch(git_root: Path | None) -> str | None:
    if git_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=git_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    branch = result.stdout.strip()
    return branch or None
