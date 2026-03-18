"""
Git tools for the Code Edit Agent.
"""

from __future__ import annotations

import subprocess
from typing import Optional

_MAX_DIFF_CHARS = 10_000


def git_status(project_path: str) -> str:
    """Run `git status --short` in *project_path*.

    Args:
        project_path: Absolute path of the project root.

    Returns:
        Output of `git status --short` as a string.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout or "(no changes)"
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"git status failed: {exc}"


def git_diff(project_path: str, path: Optional[str] = None) -> str:
    """Run `git diff` in *project_path*, optionally scoped to *path*.

    Args:
        project_path: Absolute path of the project root.
        path: Optional file path to limit the diff.

    Returns:
        Diff output (truncated to 10 000 chars if necessary).
    """
    cmd = ["git", "diff"]
    if path:
        cmd.extend(["--", path])

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout
        if len(output) > _MAX_DIFF_CHARS:
            output = output[:_MAX_DIFF_CHARS] + "\n... (truncated)"
        return output or "(no diff)"
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"git diff failed: {exc}"


__all__ = ["git_status", "git_diff"]
