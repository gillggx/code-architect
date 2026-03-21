"""
File tools for the Code Edit Agent.

All operations are sandboxed to project_path.
"""

from __future__ import annotations

import glob as _glob
import os
from pathlib import Path
from typing import List

# Extensions that must never be written to disk.
_BLOCKED_EXTENSIONS = {".env", ".key", ".pem", ".p12", ".pfx", ".crt", ".cer"}
_BLOCKED_NAMES_GLOB = {"secrets.*"}
_MAX_WRITE_BYTES = 500 * 1024  # 500 KB


def _resolve(path: str, project_path: str) -> Path:
    """Resolve *path* relative to *project_path*, raising if it escapes the sandbox."""
    base = Path(os.path.abspath(project_path))
    resolved = Path(os.path.abspath(os.path.join(project_path, path)))
    if not str(resolved).startswith(str(base)):
        raise PermissionError(
            f"Path '{path}' resolves outside project root '{project_path}'"
        )
    return resolved


def _check_blocked(resolved: Path) -> None:
    """Raise if the file has a blocked extension or name pattern."""
    ext = resolved.suffix.lower()
    if ext in _BLOCKED_EXTENSIONS:
        raise PermissionError(f"Writing to '{resolved.name}' is blocked (extension {ext})")
    import fnmatch
    for pattern in _BLOCKED_NAMES_GLOB:
        if fnmatch.fnmatch(resolved.name, pattern):
            raise PermissionError(f"Writing to '{resolved.name}' is blocked (name pattern {pattern})")


def read_file(path: str, project_path: str, offset: int = 0, limit: int = 0) -> str:
    """Read a file within *project_path*, optionally scoped to a line range.

    Args:
        path: File path relative to project root.
        project_path: Absolute path of the project root (sandbox boundary).
        offset: 1-based line number to start reading from (0 = beginning).
        limit: Maximum number of lines to return (0 = all).

    Returns:
        File contents (possibly a slice) with a header showing line range.

    Raises:
        PermissionError: If *path* escapes the sandbox.
        FileNotFoundError: If the file does not exist.
    """
    resolved = _resolve(path, project_path)
    content = resolved.read_text(encoding="utf-8", errors="replace")

    if offset <= 0 and limit <= 0:
        return content

    all_lines = content.splitlines(keepends=True)
    total = len(all_lines)
    start = max(0, offset - 1) if offset > 0 else 0
    end = min(total, start + limit) if limit > 0 else total
    sliced = all_lines[start:end]

    header = f"[Lines {start + 1}–{start + len(sliced)} of {total}]\n"
    return header + "".join(sliced)


def write_file(path: str, content: str, project_path: str) -> str:
    """Write *content* to a file within *project_path*.

    Args:
        path: File path relative to project root.
        content: New file contents.
        project_path: Absolute path of the project root (sandbox boundary).

    Returns:
        Confirmation message.

    Raises:
        PermissionError: If *path* escapes the sandbox or has a blocked extension.
        ValueError: If *content* exceeds 500 KB.
    """
    resolved = _resolve(path, project_path)
    _check_blocked(resolved)

    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_WRITE_BYTES:
        raise ValueError(
            f"Content size {len(encoded)} bytes exceeds 500 KB limit"
        )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Written {len(encoded)} bytes to {path}"


def edit_file(path: str, old_str: str, new_str: str, project_path: str) -> str:
    """Replace *old_str* with *new_str* in a file.

    Args:
        path: File path relative to project root.
        old_str: Exact string to find and replace.
        new_str: Replacement string.
        project_path: Absolute path of the project root (sandbox boundary).

    Returns:
        Confirmation message with diff summary.

    Raises:
        PermissionError: If *path* escapes the sandbox or has a blocked extension.
        ValueError: If *old_str* is not found exactly once in the file.
    """
    resolved = _resolve(path, project_path)
    _check_blocked(resolved)

    original = resolved.read_text(encoding="utf-8", errors="replace")
    count = original.count(old_str)
    if count == 0:
        raise ValueError(
            f"old_str not found in '{path}'. "
            "Make sure the string matches exactly (including whitespace)."
        )
    if count > 1:
        raise ValueError(
            f"old_str appears {count} times in '{path}'. "
            "Provide a more specific string to uniquely identify the target."
        )

    modified = original.replace(old_str, new_str, 1)
    write_file(path, modified, project_path)
    return f"Edited '{path}': replaced 1 occurrence"


def list_files(glob_pattern: str, project_path: str) -> List[str]:
    """List files matching *glob_pattern* within *project_path*.

    Args:
        glob_pattern: Glob pattern relative to project root (e.g. "**/*.py").
        project_path: Absolute path of the project root (sandbox boundary).

    Returns:
        Sorted list of relative paths (using forward slashes).
    """
    base = os.path.abspath(project_path)
    full_pattern = os.path.join(base, glob_pattern)
    matches = _glob.glob(full_pattern, recursive=True)

    results: List[str] = []
    for m in sorted(matches):
        abs_m = os.path.abspath(m)
        # Only include paths inside the project root
        if abs_m.startswith(base):
            rel = os.path.relpath(abs_m, base)
            results.append(rel.replace(os.sep, "/"))

    return results


__all__ = ["read_file", "write_file", "edit_file", "list_files"]
