import subprocess
from pathlib import Path


def current_git_revision(start: Path | None = None) -> tuple[str | None, int]:
    cwd = start or Path.cwd()
    commit = _git(["rev-parse", "HEAD"], cwd)
    if commit is None:
        return None, 0
    dirty = 1 if _git(["status", "--porcelain"], cwd) else 0
    return commit, dirty


def _git(args: list[str], cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()
