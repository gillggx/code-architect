"""
Shell tools for the Code Edit Agent.

Only commands matching the ALLOWED_COMMANDS allowlist may be executed.
"""

from __future__ import annotations

import re
import subprocess
from typing import Dict, Any, List

# ---------------------------------------------------------------------------
# Allowlist: each entry is a regex that the *full* command string must match
# (anchored at start). Commands are validated after stripping leading whitespace.
# ---------------------------------------------------------------------------
ALLOWED_COMMANDS: List[str] = [
    r"pytest(\s|$)",
    r"python\s+-m\s+pytest(\s|$)",
    r"python3\s+-m\s+pytest(\s|$)",
    r"npm\s+test(\s|$)",
    r"npm\s+run\s+test(\s|$)",
    r"npm\s+run\s+lint(\s|$)",
    r"npm\s+run\s+build(\s|$)",
    r"npm\s+lint(\s|$)",
    r"npm\s+build(\s|$)",
    r"cargo\s+test(\s|$)",
    r"go\s+test(\s|$)",
    r"ruff\s+check(\s|$)",
    r"ruff(\s|$)",
    r"mypy(\s|$)",
    r"git\s+status(\s|$)",
    r"git\s+diff(\s|$)",
    r"git\s+log(\s|$)",
]

_COMPILED: List[re.Pattern] = [re.compile(p) for p in ALLOWED_COMMANDS]


def _is_allowed(cmd: str) -> bool:
    """Return True if *cmd* matches at least one pattern in ALLOWED_COMMANDS."""
    stripped = cmd.strip()
    return any(p.match(stripped) for p in _COMPILED)


def run_command(
    cmd: str,
    project_path: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Run *cmd* in *project_path* if it matches the allowlist.

    Args:
        cmd: Shell command string to run.
        project_path: Working directory (project root).
        timeout: Maximum seconds before timeout (default 30).

    Returns:
        Dict with keys: stdout (str), stderr (str), returncode (int).

    Raises:
        PermissionError: If *cmd* does not match ALLOWED_COMMANDS.
        subprocess.TimeoutExpired: Wrapped in the return dict (returncode=-1).
    """
    if not _is_allowed(cmd):
        raise PermissionError(
            f"Command not allowed: '{cmd}'. "
            "Only test runners, linters and git status/diff/log are permitted."
        )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "returncode": -1,
        }


__all__ = ["run_command", "ALLOWED_COMMANDS"]
