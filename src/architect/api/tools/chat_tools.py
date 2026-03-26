"""
Chat Tool definitions and executor for Chat Tool-Use mode.

Four tools available during interactive chat:
  read_file               — read a file from the project
  search_files            — grep across files by pattern
  edit_file               — targeted single-file edit
  escalate_to_edit_agent  — hand off complex tasks to Edit Agent
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

CHAT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the content of a file in the project. "
                "Use this to inspect implementation details before answering. "
                "Never ask the user to share code — read it directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to project root or absolute)",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional: first line to read (1-indexed, default 1)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional: last line to read inclusive (default: up to 200 lines)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search for a regex or literal pattern across source files. "
                "Returns matching lines with file paths and line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Regex or literal search pattern",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional subdirectory to search in (relative to project root)",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional glob to filter files, e.g. '*.py' or '*.ts'",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Apply a targeted edit to a single file: replace old_str with new_str. "
                "Use ONLY for simple changes: 1 file, fewer than 10 lines changed. "
                "For complex or multi-file changes, use escalate_to_edit_agent instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "Exact string to replace (must appear exactly once in the file)",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Replacement string",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_edit_agent",
            "description": (
                "Hand off a complex task to the full Edit Agent. "
                "Use when the task requires: modifying multiple files, creating new files, "
                "running shell commands, or any architectural change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Full description of what needs to be done",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why escalation is needed (e.g. 'requires changes in 3 files')",
                    },
                },
                "required": ["task", "reason"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

MAX_READ_LINES = 400       # lines returned by read_file tool (user can override with end_line)
MAX_SEARCH_RESULTS = 50   # max grep results shown per search_files call


def execute_chat_tool(
    tool_name: str,
    args: Dict[str, Any],
    project_path: str,
) -> Dict[str, Any]:
    """
    Execute a chat tool call.

    Returns one of:
      {"ok": True, "result": str}                                   — success
      {"ok": False, "error": str}                                   — failure
      {"ok": True, "escalate": True, "task": str, "reason": str}   — escalation
      {"ok": True, "result": str, "edited": True, "path": str, "diff": str}  — file edit
    """
    try:
        if tool_name == "read_file":
            return _read_file(args, project_path)
        elif tool_name == "search_files":
            return _search_files(args, project_path)
        elif tool_name == "edit_file":
            return _edit_file(args, project_path)
        elif tool_name == "escalate_to_edit_agent":
            return {
                "ok": True,
                "escalate": True,
                "task": args.get("task", ""),
                "reason": args.get("reason", ""),
            }
        else:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    except Exception as exc:
        logger.error("Tool %s failed: %s", tool_name, exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _resolve_path(path: str, project_path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(project_path, path)


def _read_file(args: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    path = _resolve_path(args["path"], project_path)

    # If caller passed a directory, return file listing instead of failing silently
    if os.path.isdir(path):
        try:
            entries = sorted(os.listdir(path))
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            dirs = [e + "/" for e in entries if os.path.isdir(os.path.join(path, e))]
            listing = "\n".join(dirs + files)
            rel = os.path.relpath(path, project_path)
            return {
                "ok": False,
                "error": (
                    f"`{rel}` is a directory, not a file. "
                    f"Pick a specific file and call read_file again.\n\nContents:\n{listing}"
                ),
            }
        except OSError as exc:
            return {"ok": False, "error": f"Cannot list directory: {exc}"}

    if not os.path.isfile(path):
        return {"ok": False, "error": f"File not found: {path}"}

    start = max(0, args.get("start_line", 1) - 1)
    end = args.get("end_line")

    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if end is not None:
            selected = lines[start:end]
        else:
            selected = lines[start: start + MAX_READ_LINES]

        total = len(lines)
        content = "".join(selected)
        truncated = end is None and total > start + MAX_READ_LINES
        note = f"\n[... {total - start - MAX_READ_LINES} more lines — use start_line/end_line to read more]" if truncated else ""

        rel_path = os.path.relpath(path, project_path)
        line_range = f"lines {start + 1}-{start + len(selected)}/{total}"
        return {"ok": True, "result": f"# {rel_path} ({line_range})\n```\n{content.rstrip()}{note}\n```"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def _search_files(args: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    query = args["query"]
    directory = args.get("directory", "")
    file_pattern = args.get("file_pattern", "")

    search_root = os.path.join(project_path, directory) if directory else project_path

    cmd = ["grep", "-rn", query, search_root]
    if file_pattern:
        cmd = ["grep", "-rn", f"--include={file_pattern}", query, search_root]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        raw_lines = proc.stdout.strip().splitlines()

        if not raw_lines:
            return {"ok": True, "result": f"No matches found for: `{query}`"}

        truncated = len(raw_lines) > MAX_SEARCH_RESULTS
        display = raw_lines[:MAX_SEARCH_RESULTS]

        # Make paths relative to project_path
        rel_lines = []
        for line in display:
            if line.startswith(project_path):
                line = line[len(project_path):].lstrip("/")
            rel_lines.append(line)

        result = "\n".join(rel_lines)
        if truncated:
            result += f"\n... (showing {MAX_SEARCH_RESULTS} of {len(raw_lines)} matches)"

        return {"ok": True, "result": result}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Search timed out (>10s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _edit_file(args: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    path = _resolve_path(args["path"], project_path)
    old_str: str = args["old_str"]
    new_str: str = args["new_str"]

    if not os.path.isfile(path):
        return {"ok": False, "error": f"File not found: {path}"}

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        if old_str not in content:
            return {"ok": False, "error": f"`old_str` not found in {os.path.relpath(path, project_path)}"}

        count = content.count(old_str)
        if count > 1:
            return {"ok": False, "error": f"`old_str` appears {count} times — must be unique"}

        new_content = content.replace(old_str, new_str, 1)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        rel_path = os.path.relpath(path, project_path)
        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        diff = "\n".join(
            [f"-{l}" for l in old_lines] + [f"+{l}" for l in new_lines]
        )

        return {
            "ok": True,
            "edited": True,
            "path": rel_path,
            "result": f"Edited `{rel_path}`: -{len(old_lines)} lines / +{len(new_lines)} lines",
            "diff": diff,
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
