"""
Diff utility for the Code Edit Agent.

Produces unified diffs for display in the web UI.
"""

from __future__ import annotations

import difflib


def make_diff(original: str, modified: str, filename: str) -> str:
    """Return a unified diff string.

    Args:
        original: Original file content.
        modified: Modified file content.
        filename: File name to display in the diff header.

    Returns:
        Unified diff as a string.  Empty string if there are no changes.
    """
    lines_a = original.splitlines(keepends=True)
    lines_b = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)


__all__ = ["make_diff"]
