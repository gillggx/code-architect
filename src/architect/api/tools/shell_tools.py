"""
Shell tools for the Code Edit Agent.

Only commands matching the ALLOWED_COMMANDS allowlist may be executed.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, Any, List

# Set AGENT_SHELL_UNRESTRICTED=true in .env to bypass the allowlist (dev only)
SHELL_UNRESTRICTED = os.getenv("AGENT_SHELL_UNRESTRICTED", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Allowlist: each entry is a regex that the *full* command string must match
# (anchored at start). Commands are validated after stripping leading whitespace.
# ---------------------------------------------------------------------------
ALLOWED_COMMANDS: List[str] = [
    # Python test runners
    r"pytest(\s|$)",
    r"python\s+-m\s+pytest(\s|$)",
    r"python3\s+-m\s+pytest(\s|$)",
    # Node test / lint / build (npm, yarn, pnpm, bun)
    r"npm\s+(test|run\s+(test|lint|build|check|typecheck|format))(\s|$)",
    r"yarn\s+(test|run\s+(test|lint|build|check|typecheck|format)|lint|build)(\s|$)",
    r"pnpm\s+(test|run\s+(test|lint|build|check|typecheck|format)|lint|build)(\s|$)",
    r"bun\s+(test|run\s+(test|lint|build))(\s|$)",
    # Other language test runners
    r"cargo\s+test(\s|$)",
    r"go\s+test(\s|$)",
    # Linters / type checkers
    r"ruff(\s|$)",
    r"mypy(\s|$)",
    r"eslint(\s|$)",
    r"tsc(\s|$)",
    r"pyright(\s|$)",
    # Dependency installation
    r"npm\s+install(\s|$)",
    r"npm\s+ci(\s|$)",
    r"pip\s+install(\s|$)",
    r"pip3\s+install(\s|$)",
    r"python\s+-m\s+pip(\s|$)",
    r"python3\s+-m\s+pip(\s|$)",
    r"python\s+-m\s+venv(\s|$)",
    r"python3\s+-m\s+venv(\s|$)",
    r"uv\s+(pip|venv|sync|add|run)(\s|$)",
    r"poetry\s+(install|add|run)(\s|$)",
    r"pnpm\s+install(\s|$)",
    r"yarn\s+install(\s|$)",
    r"bun\s+install(\s|$)",
    r"cargo\s+build(\s|$)",
    r"go\s+(mod|get|build)(\s|$)",
    # Git (read-only + init)
    r"git\s+init(\s|$)",
    r"git\s+(status|diff|log|show|blame)(\s|$)",
    # Directory / file operations
    r"mkdir(\s|$)",
    r"chmod(\s|$)",        # Ubuntu: make scripts executable
    r"touch(\s|$)",
    # File exploration (read-only)
    r"find(\s|$)",
    r"ls(\s|$)",
    r"cat(\s|$)",
    r"head(\s|$)",
    r"tail(\s|$)",
    r"wc(\s|$)",
    r"grep(\s|$)",
    r"echo(\s|$)",
    # Tool discovery (Ubuntu needs these to locate binaries)
    r"which(\s|$)",
    r"command\s+-v(\s|$)",
    r"type(\s|$)",
    # Venv activation (POSIX: `. path/activate`)
    r"\.\s+\S+",           # `. venv/bin/activate`
    r"source(\s|$)",       # `source venv/bin/activate` (bash)
    # OS info
    r"uname(\s|$)",
    r"python3?\s+--version(\s|$)",
    r"node\s+--version(\s|$)",
    r"npm\s+--version(\s|$)",
]

# Commands allowed when prefixed with "cd <path> && <cmd>"
# Supports quoted paths: cd "/path/with spaces" && cmd
# and unquoted paths:    cd /simple/path && cmd
_CD_PREFIX = re.compile(r'^cd\s+(?:"[^"]*"|\'[^\']*\'|\S+)\s*&&\s*(.+)$')
_COMPILED: List[re.Pattern] = [re.compile(p) for p in ALLOWED_COMMANDS]


def _is_allowed(cmd: str) -> bool:
    """Return True if *cmd* (or its cd-prefix variant) matches ALLOWED_COMMANDS."""
    if SHELL_UNRESTRICTED:
        return True
    stripped = cmd.strip()
    # Strip optional "cd <path> && " prefix so agent can run commands in subdirs
    m = _CD_PREFIX.match(stripped)
    effective = m.group(1).strip() if m else stripped
    # Also strip pipe suffixes like "| head -100" for matching purposes
    effective_base = re.split(r"\s*[|;&]\s*", effective)[0].strip()
    return any(p.match(effective_base) for p in _COMPILED)


def run_command(
    cmd: str,
    project_path: str,
    timeout: int = 60,
    shell_unrestricted: bool = False,
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
    if not shell_unrestricted and not _is_allowed(cmd):
        raise PermissionError(
            f"Command not allowed: '{cmd}'. "
            "Only test runners, linters and git status/diff/log are permitted."
        )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",   # use bash (not dash) so `source` works on Ubuntu
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
