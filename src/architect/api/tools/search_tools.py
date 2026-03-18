"""
Search tools for the Code Edit Agent.

Provides code search via ripgrep (preferred) or grep fallback.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import List, Dict, Any

_MAX_RESULTS = 50


def search_code(
    pattern: str,
    project_path: str,
    file_glob: str = "*",
) -> List[Dict[str, Any]]:
    """Search for *pattern* (regex) within *project_path*.

    Uses ripgrep if available, otherwise falls back to grep -r.

    Args:
        pattern: Regular expression to search for.
        project_path: Absolute path of the project root.
        file_glob: File glob filter (e.g. "*.py", "*.ts"). Default: all files.

    Returns:
        List of dicts with keys: file (relative), line (int), content (str).
        Maximum 50 results.
    """
    base = os.path.abspath(project_path)

    results: List[Dict[str, Any]] = []

    # Try ripgrep first
    rg_path = _find_executable("rg")
    if rg_path:
        results = _search_with_rg(rg_path, pattern, base, file_glob)
    else:
        results = _search_with_grep(pattern, base, file_glob)

    return results[:_MAX_RESULTS]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_executable(name: str) -> str | None:
    """Return full path to *name* if available on PATH, else None."""
    import shutil
    return shutil.which(name)


def _search_with_rg(
    rg_path: str,
    pattern: str,
    base: str,
    file_glob: str,
) -> List[Dict[str, Any]]:
    cmd = [
        rg_path,
        "--line-number",
        "--no-heading",
        "--color=never",
        "--glob", file_glob,
        "--max-count", "1",   # 1 match per file per occurrence shown separately
        pattern,
        base,
    ]
    # Use -m 1 per file is wrong here; we want all matches. Remove max-count.
    cmd = [
        rg_path,
        "--line-number",
        "--no-heading",
        "--color=never",
        "--glob", file_glob,
        pattern,
        base,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return _parse_rg_output(proc.stdout, base)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _parse_rg_output(output: str, base: str) -> List[Dict[str, Any]]:
    """Parse rg --line-number --no-heading output."""
    results: List[Dict[str, Any]] = []
    for raw_line in output.splitlines():
        # Format: /absolute/path/file.py:42:matched content
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        abs_file, line_str, content = parts[0], parts[1], parts[2]
        try:
            line_num = int(line_str)
        except ValueError:
            continue
        abs_file = os.path.abspath(abs_file)
        if not abs_file.startswith(base):
            continue
        rel = os.path.relpath(abs_file, base).replace(os.sep, "/")
        results.append({"file": rel, "line": line_num, "content": content.rstrip()})
        if len(results) >= _MAX_RESULTS:
            break
    return results


def _search_with_grep(
    pattern: str,
    base: str,
    file_glob: str,
) -> List[Dict[str, Any]]:
    """Fallback to grep -r."""
    include_arg = f"--include={file_glob}" if file_glob != "*" else None
    cmd = ["grep", "-r", "-n", "--color=never", "-E", pattern, base]
    if include_arg:
        cmd.insert(4, include_arg)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return _parse_rg_output(proc.stdout, base)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


__all__ = ["search_code"]
