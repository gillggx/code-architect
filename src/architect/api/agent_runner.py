"""
AgentRunner — agentic loop for code editing tasks.

Uses OpenAI function-calling format via openai.AsyncOpenAI pointed at OpenRouter.
Supports three modes:

  dry_run     — collects FileChange objects, never writes to disk.
  apply       — writes immediately after each write_file / edit_file tool call.
  interactive — yields ApprovalRequired events, pauses until POST /api/agent/approve
                resumes execution.

Sessions
--------
A global dict `_agent_sessions` maps session_id → AgentSession.
In interactive mode the runner stores an asyncio.Event in the session; the
/api/agent/approve endpoint sets that event to resume.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / model config
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
AGENT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "anthropic/claude-sonnet-4-5")
CHUNK_SIZE = 12  # Max plan steps per execution phase
APPROVAL_TIMEOUT = 900  # 15 minutes
MAX_LINT_RETRIES = 3    # self-correction attempts per file
SUMMARY_THRESHOLD = 20   # messages before summarization kicks in
ACTIVE_FILE_LOOKBACK = 6  # recent iterations to scan for active files
MAX_HYDRATED_SYMBOLS = 15 # symbols per hydrated module
MAX_ITERATIONS = 50      # hard cap per phase — prevents infinite exploration loops
MAX_STALL_REPEATS = 3    # identical (tool, args) calls before stall warning is injected


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    file: str          # relative path
    action: str        # "create" | "edit" | "delete"
    content: str       # new file content (empty for delete)
    diff: str          # unified diff (empty for create)
    applied: bool = False


@dataclass
class ToolCallEvent:
    type: str                            # see EVENT_TYPES below
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    diff: Optional[str] = None
    content: Optional[str] = None
    approval_required: bool = False
    changes: Optional[List[FileChange]] = None
    summary: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type}
        if self.tool is not None:
            d["tool"] = self.tool
        if self.args is not None:
            d["args"] = self.args
        if self.result is not None:
            d["result"] = self.result
        if self.diff is not None:
            d["diff"] = self.diff
        if self.content is not None:
            d["content"] = self.content
        if self.approval_required:
            d["approval_required"] = True
        if self.changes is not None:
            d["changes"] = [
                {
                    "file": c.file,
                    "action": c.action,
                    "content": c.content,
                    "diff": c.diff,
                    "applied": c.applied,
                }
                for c in self.changes
            ]
        if self.summary is not None:
            d["summary"] = self.summary
        if self.error is not None:
            d["error"] = self.error
        return d


# EVENT_TYPES: "tool_call" | "tool_output" | "message" | "plan" | "done" | "error" | "approval_required" | "escalation"


@dataclass
class PlanStep:
    index: int
    description: str
    files_affected: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    variant: str           # "A" or "B"
    steps: List[PlanStep] = field(default_factory=list)
    confidence: float = 0.7
    rationale: str = ""
    risk_level: str = "low"  # "low" | "medium" | "high"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant": self.variant,
            "steps": [{"index": s.index, "description": s.description, "files_affected": s.files_affected} for s in self.steps],
            "confidence": self.confidence,
            "rationale": self.rationale,
            "risk_level": self.risk_level,
        }


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@dataclass
class AgentSession:
    session_id: str
    status: str = "running"          # "running" | "complete" | "stopped" | "error"
    approval_event: asyncio.Event = field(default_factory=asyncio.Event)
    approved_action: Optional[str] = None   # "apply" | "skip" | "stop" | "edit"
    edited_content: Optional[str] = None
    plan_a: Optional[Any] = None          # ExecutionPlan
    plan_b: Optional[Any] = None          # ExecutionPlan | None
    plan_approval_event: asyncio.Event = field(default_factory=asyncio.Event)
    plan_approved_action: Optional[str] = None  # "approve" | "reject" | "stop"
    plan_b_exhausted: bool = False
    escalation_event: asyncio.Event = field(default_factory=asyncio.Event)
    escalation_action: Optional[str] = None   # "alternative" | "manual_fix" | "stop"
    escalation_instruction: Optional[str] = None
    git_base_branch: Optional[str] = None
    git_task_branch: Optional[str] = None
    git_stash_created: bool = False


_agent_sessions: Dict[str, AgentSession] = {}


def get_session(session_id: str) -> Optional[AgentSession]:
    return _agent_sessions.get(session_id)


def create_session(session_id: str) -> AgentSession:
    sess = AgentSession(session_id=session_id)
    _agent_sessions[session_id] = sess
    return sess


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ToolExecutionError(Exception):
    """Raised when a tool call fails and escalation should be considered."""
    def __init__(self, fn_name: str, fn_args: Dict[str, Any], message: str):
        super().__init__(message)
        self.fn_name = fn_name
        self.fn_args = fn_args
        self.error_message = message


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from the project. Use offset+limit to read only the relevant "
                "section of a large file — especially when you know the symbol line number "
                "from the project memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to project root",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "1-based line number to start reading from (omit to read from beginning)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of lines to read (omit to read to end of file)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the project matching a glob pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "glob_pattern": {
                        "type": "string",
                        "description": "Glob pattern relative to project root (e.g. '**/*.py')",
                    }
                },
                "required": ["glob_pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a regex pattern in project files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression to search for",
                    },
                    "file_glob": {
                        "type": "string",
                        "description": "Optional file glob filter (e.g. '*.py')",
                        "default": "*",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the working tree status (git status --short)",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff, optionally for a specific file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional file path to scope the diff",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (create or overwrite) a file with given content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to project root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact string in a file with a new string",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to project root",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "Exact string to find and replace",
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
            "name": "run_command",
            "description": "Run an allowed shell command (tests, linters, git status/diff/log)",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "Command to run",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                        "default": 30,
                    },
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "syntax_lint",
            "description": "Check a file for syntax errors after editing. Returns 'Syntax OK' or a SyntaxError message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to project root",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": (
                "REQUIRED before every write_file or edit_file. "
                "Use this to reason explicitly about your next change. "
                "State what you know from reading, exactly what you will change, "
                "and why it is the minimum necessary change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "what_i_know": {
                        "type": "string",
                        "description": "Key facts learned from reading files relevant to this change",
                    },
                    "what_i_will_change": {
                        "type": "string",
                        "description": "Exact file path and specific lines/section to modify",
                    },
                    "minimum_justification": {
                        "type": "string",
                        "description": "Why this is the minimum change needed to satisfy the task",
                    },
                },
                "required": ["what_i_know", "what_i_will_change", "minimum_justification"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------

class AgentRunner:
    """
    Async generator-based agentic loop.

    Usage::

        runner = AgentRunner(task, project_path, project_modules, mode)
        async for event in runner.run():
            # event is a ToolCallEvent
            yield f"data: {json.dumps(event.to_dict())}\\n\\n"
    """

    def __init__(
        self,
        task: str,
        project_path: str,
        project_modules: List[Dict[str, Any]],
        mode: str = "dry_run",
        context: Optional[str] = None,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
        shell_unrestricted: bool = False,
        auto_approve: bool = False,
    ) -> None:
        self.task = task
        self.project_path = project_path
        self.project_modules = project_modules
        self.mode = mode  # "dry_run" | "apply" | "interactive"
        self.context = context
        self.session_id = session_id or str(uuid4())
        self.chat_history: List[Dict[str, str]] = chat_history or []
        self.shell_unrestricted = shell_unrestricted
        self.auto_approve = auto_approve

        self._changes: List[FileChange] = []
        self._plan: List[str] = []
        self._session: Optional[AgentSession] = None
        self._syntax_retries: Dict[str, int] = {}     # path → retry count
        self._files_read: set = set()                  # normalized paths read this session
        self._working_memory: Dict[str, str] = {}      # path → key facts snippet
        self._last_tool_was_think: bool = False        # think() called before last write?

        # Git checkpoint (Sprint 3.2)
        self._git_base_branch: Optional[str] = None
        self._git_task_branch: Optional[str] = None
        self._git_checkpoint_created: bool = False

        # Lazy-init openai client
        self._oai = None

        # Load soul
        from .soul import load_soul
        self._soul = load_soul(project_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> AsyncIterator[ToolCallEvent]:
        """Async generator that yields ToolCallEvent objects."""
        # Create session for interactive mode
        if self.mode == "interactive":
            self._session = create_session(self.session_id)

        try:
            async for event in self._agentic_loop():
                yield event
        except Exception as exc:
            logger.error("AgentRunner error: %s", exc, exc_info=True)
            yield ToolCallEvent(type="error", error=str(exc))
            if self._session:
                self._session.status = "error"

    @property
    def changes(self) -> List[FileChange]:
        return self._changes

    @property
    def plan(self) -> List[str]:
        return self._plan

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._oai is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError("openai package is required for agent mode") from exc

            if not OPENROUTER_API_KEY:
                raise RuntimeError(
                    "OPENROUTER_API_KEY is not set. Cannot run agent."
                )

            self._oai = AsyncOpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url=OPENROUTER_BASE_URL,
            )
        return self._oai

    @staticmethod
    def _lint_file(path: str, project_path: str) -> dict:
        """Run static syntax check on a file. Returns {ok, error?, line?, skipped?}."""
        from .tools.file_tools import _resolve
        try:
            resolved = _resolve(path, project_path)
            if not resolved.exists():
                return {"ok": True, "skipped": True}
            source = resolved.read_text(encoding="utf-8", errors="replace")
            suffix = resolved.suffix.lower()
            if suffix == ".py":
                try:
                    ast.parse(source)
                    return {"ok": True}
                except SyntaxError as exc:
                    return {"ok": False, "error": str(exc), "line": exc.lineno}
            elif suffix in (".ts", ".tsx", ".js", ".jsx"):
                try:
                    result = subprocess.run(
                        ["tsc", "--noEmit", "--allowJs", "--syntaxOnly", str(resolved)],
                        capture_output=True, text=True, timeout=15,
                    )
                    if result.returncode != 0:
                        err = (result.stdout + result.stderr).strip()[:500]
                        return {"ok": False, "error": err}
                    return {"ok": True}
                except FileNotFoundError:
                    return {"ok": True, "skipped": True}  # tsc not installed
                except subprocess.TimeoutExpired:
                    return {"ok": True, "skipped": True}
            else:
                return {"ok": True, "skipped": True}
        except Exception as exc:
            logger.warning("Lint check failed for %s: %s", path, exc)
            return {"ok": True, "skipped": True}

    @staticmethod
    def _backup_file(path: str, project_path: str) -> None:
        """Copy original file to .architect/backup/ before overwriting."""
        from .tools.file_tools import _resolve
        try:
            resolved = _resolve(path, project_path)
            if not resolved.exists():
                return
            backup_dir = Path(project_path) / ".architect" / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            # Count existing backups to enforce soft cap
            existing = list(backup_dir.glob("*"))
            if len(existing) >= 50:
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = str(Path(path).as_posix()).replace("/", "__")
            shutil.copy2(resolved, backup_dir / f"{safe_name}.{timestamp}")
        except Exception as exc:
            logger.warning("Backup failed for %s: %s", path, exc)

    @staticmethod
    def _score_relevance(task: str, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort modules by keyword relevance to the task (descending)."""
        task_words = set(task.lower().split())
        def _score(mod: Dict[str, Any]) -> int:
            text = " ".join([
                mod.get("name", ""),
                mod.get("path", ""),
                mod.get("purpose", ""),
                " ".join(mod.get("key_components", [])),
                " ".join(mod.get("patterns", [])),
            ]).lower()
            return sum(1 for w in task_words if len(w) > 3 and w in text)
        return sorted(modules, key=_score, reverse=True)

    def _build_system_prompt(self) -> str:
        lines = [
            "You are Code Architect Agent — an expert software engineer.",
            "You edit code to complete tasks using the tools provided.",
            "Work methodically: read files first, plan your changes, then apply them.",
            "Always verify your changes make sense before writing.",
            "",
            f"Project path: {self.project_path}",
            "",
        ]

        if self.project_modules:
            ranked = self._score_relevance(self.task, self.project_modules)
            top = ranked[:6]
            rest = ranked[6:]

            lines.append("## Most relevant files for this task")
            for mod in top:
                name = mod.get("name", "unknown")
                path = mod.get("path", "")
                purpose = mod.get("purpose", "")
                edit_hints = mod.get("edit_hints") or mod.get("notes", "")
                symbols = mod.get("symbols", [])
                imported_by = mod.get("imported_by", [])

                lines.append(f"\n### {name}  `{path}`")
                lines.append(f"**Purpose:** {purpose}")
                if edit_hints and edit_hints.lower() not in ("none", "none.", ""):
                    lines.append(f"**Edit hints:** {edit_hints}")
                if symbols:
                    sym_lines = []
                    for s in symbols[:12]:
                        sym_lines.append(
                            f"  - `{s['name']}` line {s['line_start']}–{s['line_end']}: {s['signature']}"
                        )
                    lines.append("**Symbols (use for read_file offset):**")
                    lines.extend(sym_lines)
                if imported_by:
                    lines.append(f"**Imported by:** {', '.join(imported_by[:5])}")

            if rest:
                lines.append("\n## Other project modules")
                for mod in rest[:34]:
                    name = mod.get("name") or mod.get("file", "unknown")
                    purpose = mod.get("purpose", "")
                    patterns_list = mod.get("patterns", [])
                    entry = f"- **{name}**: {purpose}"
                    if patterns_list:
                        entry += f" [{', '.join(patterns_list[:2])}]"
                    lines.append(entry)
            lines.append("")

        if self.context:
            lines.append("## Additional context")
            lines.append(self.context)
            lines.append("")

        lines += [
            "## Agent Soul & Personality",
            self._soul,
            "",
            "## Operational Rules (MANDATORY — violations cause incorrect output)",
            "",
            "### Explore First",
            "- Before making ANY edit, you MUST call list_files or read_file at least once.",
            "- Never jump directly to write_file or edit_file without reading context.",
            "",
            "### No Guessing",
            "- NEVER guess variable names, function signatures, or import paths.",
            "- If unsure, call search_code or read_file to verify. Always.",
            "",
            "### Incremental Edits",
            "- Prefer edit_file (targeted replacement) over write_file (full overwrite).",
            "- Make one logical change at a time and verify before the next.",
            "- Use write_file only for new files or when a full rewrite is clearly needed.",
            "",
            "### Dependency Awareness",
            "- Before changing a function/class, call search_code to find all callers.",
            "- Consider side-effects on dependent modules before applying changes.",
            "",
            "### Syntax Verification",
            "- After every edit_file or write_file, call syntax_lint on the modified file.",
            "- If syntax_lint reports an error, fix it immediately before continuing.",
            "",
            "### Task Scope — YAGNI (CRITICAL)",
            "- ONLY create or modify files DIRECTLY required by the user's request.",
            "- NEVER create analysis files, recommendation files, documentation files,",
            "  TODO files, or summary reports unless the user explicitly asked for them.",
            "- If unsure whether a file is needed: do NOT create it.",
            "- The task is complete when the user's request is satisfied. Stop immediately.",
            "- Count your changes. More than 3 files changed for a simple request = you over-scoped.",
            "",
            "### Before Every Edit (MANDATORY SEQUENCE)",
            "1. read_file(path) — read the target file",
            "2. think(what_i_know, what_i_will_change, minimum_justification) — reason explicitly",
            "3. edit_file(path, old_str, new_str) — make the targeted change",
            "This sequence is ENFORCED. Skipping any step will be blocked.",
            "",
            "### Security",
            "- Never write to .env, .key, .pem, secrets.*, or any file outside project root.",
            "",
            "### Allowed shell commands (run_command allowlist)",
            "Only the following commands are permitted. Using anything else will be rejected:",
            "  Tests:       pytest, python -m pytest, npm test, npm run test, yarn test",
            "  Linters:     ruff, mypy, eslint, tsc, pyright, npm run lint, yarn lint",
            "  Build:       npm run build, yarn build, pnpm build, cargo build, go build",
            "  Install:     pip install, npm install, npm ci, uv pip, poetry install",
            "  Git (read):  git status, git diff, git log, git show, git blame",
            "  Filesystem:  ls, find, cat, head, tail, grep, wc, mkdir",
            "  Other:       go test, cargo test, bun test",
            "  All of the above also accept: cd <path> && <cmd>",
            "",
            "### Completion",
            "- When done, provide a concise summary of what changed and why.",
        ]

        return "\n".join(lines)

    async def _generate_plans(self) -> tuple[ExecutionPlan, Optional[ExecutionPlan]]:
        """Call LLM to generate Plan A and optional Plan B."""
        client = self._get_client()

        # Build a concise context for planning (no full tool defs)
        module_summary = ""
        if self.project_modules:
            lines = []
            for mod in self.project_modules[:20]:
                name = mod.get("name", "unknown")
                purpose = mod.get("purpose", "")
                lines.append(f"- {name}: {purpose}")
            module_summary = "\n".join(lines)

        # Truncate task to avoid token overflow in planning call
        task_summary = self.task[:800] if len(self.task) > 800 else self.task

        system_msg = (
            "You are a software engineering planner. "
            "You always respond with valid JSON only. No markdown, no explanation."
        )
        user_msg = f"""Task: {task_summary}

Relevant modules: {module_summary[:400] if module_summary else "unknown"}

Respond with JSON exactly like this example:
{{
  "plan_a": {{
    "steps": [
      {{"index": 1, "description": "Read the target file to understand current structure", "files_affected": ["src/foo.ts"]}},
      {{"index": 2, "description": "Edit the function to add the new behaviour", "files_affected": ["src/foo.ts"]}},
      {{"index": 3, "description": "Run tests to verify", "files_affected": []}}
    ],
    "confidence": 0.85,
    "rationale": "Direct approach with minimal risk",
    "risk_level": "low"
  }}
}}

Now generate the real plan for the task above. You may include plan_b if there is a meaningfully different alternative approach. Keep steps concrete."""

        try:
            try:
                response = await client.chat.completions.create(
                    model=AGENT_MODEL,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=1024,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
            except Exception:
                # Model doesn't support response_format — retry without it
                response = await client.chat.completions.create(
                    model=AGENT_MODEL,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=1024,
                    temperature=0.2,
                )
            raw = response.choices[0].message.content or ""
            logger.debug("Plan LLM raw response: %s", raw[:500])
            # Extract JSON — find the outermost { } block robustly
            import re as _re
            data = None
            # Try code-fence first: ```json ... ```
            fence = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, _re.DOTALL)
            if fence:
                data = json.loads(fence.group(1))
            else:
                # Walk char by char to find balanced { }
                start = raw.find('{')
                if start != -1:
                    depth, end = 0, -1
                    for i, ch in enumerate(raw[start:], start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end = i
                                break
                    if end != -1:
                        data = json.loads(raw[start:end + 1])
            if data is None:
                data = json.loads(raw)

            def _parse_plan(d: dict, variant: str) -> ExecutionPlan:
                steps = [
                    PlanStep(
                        index=s.get("index", i+1),
                        description=s.get("description", ""),
                        files_affected=s.get("files_affected", []),
                    )
                    for i, s in enumerate(d.get("steps", []))
                ]
                return ExecutionPlan(
                    variant=variant,
                    steps=steps,
                    confidence=float(d.get("confidence", 0.7)),
                    rationale=d.get("rationale", ""),
                    risk_level=d.get("risk_level", "low"),
                )

            plan_a = _parse_plan(data["plan_a"], "A")
            plan_b = _parse_plan(data["plan_b"], "B") if data.get("plan_b") else None
            return plan_a, plan_b

        except Exception as exc:
            logger.warning("Plan generation failed: %s — raw was: %r — using default plan", exc, locals().get('raw', '')[:300])
            default_plan = ExecutionPlan(
                variant="A",
                steps=[PlanStep(index=1, description=self.task, files_affected=[])],
                confidence=0.5,
                rationale="Could not generate structured plan; proceeding directly.",
                risk_level="medium",
            )
            return default_plan, None

    async def _run_planning_stage(self) -> AsyncIterator[ToolCallEvent]:
        """Stage 2: Generate Plan A/B, optionally wait for user approval."""
        yield ToolCallEvent(type="message", content="Generating execution plan...")

        plan_a, plan_b = await self._generate_plans()

        if self._session:
            self._session.plan_a = plan_a
            self._session.plan_b = plan_b

        confidence_gap = plan_a.confidence - (plan_b.confidence if plan_b else 0.0)
        needs_confirmation = plan_b is not None and confidence_gap < 0.30

        # Emit plan event
        plan_payload = {
            "plan_a": plan_a.to_dict(),
            "plan_b": plan_b.to_dict() if plan_b else None,
            "needs_confirmation": needs_confirmation,
            "confidence_gap": round(confidence_gap, 3),
            "session_id": self.session_id,
        }
        yield ToolCallEvent(
            type="plan",
            content=json.dumps(plan_payload),
            summary=f"Plan A ({int(plan_a.confidence*100)}% confidence, {len(plan_a.steps)} steps)" +
                    (f" | Plan B ({int(plan_b.confidence*100)}% confidence)" if plan_b else ""),
        )

        # If needs confirmation, pause and wait
        if needs_confirmation and self._session and self.mode == "interactive":
            self._session.plan_approval_event.clear()
            try:
                await asyncio.wait_for(
                    self._session.plan_approval_event.wait(),
                    timeout=APPROVAL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                yield ToolCallEvent(type="error", error="Plan approval timeout — agent stopped.")
                if self._session:
                    self._session.status = "stopped"
                return

            action = self._session.plan_approved_action
            if action == "stop":
                yield ToolCallEvent(type="done", content="Stopped at planning stage.", changes=[])
                if self._session:
                    self._session.status = "stopped"
                return
            if action == "reject":
                yield ToolCallEvent(type="message", content="Plan rejected by user. Stopping.")
                if self._session:
                    self._session.status = "stopped"
                return
            # "approve" or plan_b chosen — continue

    async def _run_escalation(
        self, exc: "ToolExecutionError", iteration: int
    ) -> AsyncIterator[ToolCallEvent]:
        """Stage 4: Handle tool failure — try Plan B, then escalate to user."""

        # Try Plan B auto-recovery first
        if (self._session and
            self._session.plan_b is not None and
            not self._session.plan_b_exhausted):

            yield ToolCallEvent(
                type="message",
                content=f"⚡ {exc.fn_name} failed. Attempting Plan B auto-recovery...",
            )

            # Find matching Plan B step (by iteration index)
            plan_b = self._session.plan_b
            step_index = min(iteration, len(plan_b.steps) - 1)
            if plan_b.steps:
                step_desc = plan_b.steps[step_index].description
                yield ToolCallEvent(
                    type="message",
                    content=f"Plan B step {step_index + 1}: {step_desc}",
                )

            self._session.plan_b_exhausted = True
            # We don't re-execute here; we inject a message so the LLM retries with plan B context
            # The actual retry happens by returning from this generator without stopping
            return  # Let the main loop continue with Plan B context injected

        # Plan B not available or already exhausted → escalate to user
        suggested_options = [
            "Try an alternative approach",
            "I'll fix it manually — continue after",
            "Stop execution",
        ]

        escalation_payload = {
            "failed_tool": exc.fn_name,
            "failed_args": exc.fn_args,
            "error_message": exc.error_message,
            "iteration": iteration,
            "plan_b_attempted": self._session.plan_b_exhausted if self._session else False,
            "suggested_options": suggested_options,
            "session_id": self.session_id,
        }

        yield ToolCallEvent(
            type="escalation",
            content=json.dumps(escalation_payload),
            error=exc.error_message,
            summary=f"Tool '{exc.fn_name}' failed: {exc.error_message[:100]}",
        )

        if not self._session or self.mode != "interactive":
            return  # Non-interactive: just continue

        # Wait for user decision
        self._session.escalation_event.clear()
        try:
            await asyncio.wait_for(
                self._session.escalation_event.wait(),
                timeout=APPROVAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            yield ToolCallEvent(type="error", error="Escalation timeout — agent stopped.")
            if self._session:
                self._session.status = "stopped"

    def _get_active_file_context(self, messages: List[Dict]) -> str:
        """Build focused ## Active Context block for files recently touched by tool calls."""
        recent = messages[-ACTIVE_FILE_LOOKBACK * 2:]
        active_stems: set = set()
        for msg in recent:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    if fn.get("name") in ("read_file", "write_file", "edit_file"):
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                            path = args.get("path", "")
                            if path:
                                active_stems.add(Path(path).stem.lower())
                        except Exception:
                            pass
        if not active_stems or not self.project_modules:
            return ""

        active_modules: List[Dict] = []
        seen_paths: set = set()

        for mod in self.project_modules:
            mod_stem = Path(mod.get("path", "")).stem.lower()
            if mod_stem in active_stems and mod.get("path") not in seen_paths:
                active_modules.append(mod)
                seen_paths.add(mod.get("path", ""))
                # Include first-degree imported_by
                for dep_stem in mod.get("imported_by", []):
                    for dep_mod in self.project_modules:
                        dep_path = dep_mod.get("path", "")
                        if Path(dep_path).stem.lower() == dep_stem.lower() and dep_path not in seen_paths:
                            active_modules.append(dep_mod)
                            seen_paths.add(dep_path)
                # Include first-degree dependencies
                for dep_name in mod.get("dependencies", []):
                    for dep_mod in self.project_modules:
                        dep_path = dep_mod.get("path", "")
                        if dep_mod.get("name", "").lower() == dep_name.lower() and dep_path not in seen_paths:
                            active_modules.append(dep_mod)
                            seen_paths.add(dep_path)

        if not active_modules:
            return ""

        lines = ["## Active Context (files recently in play)"]
        for mod in active_modules[:8]:
            name = mod.get("name", "unknown")
            path = mod.get("path", "")
            purpose = mod.get("purpose", "")
            edit_hints = mod.get("edit_hints") or mod.get("notes", "")
            symbols = mod.get("symbols", [])
            imported_by = mod.get("imported_by", [])

            lines.append(f"\n### {name}  `{path}`")
            lines.append(f"**Purpose:** {purpose}")
            if edit_hints and edit_hints.lower() not in ("none", "none.", ""):
                lines.append(f"**Edit hints:** {edit_hints}")
            if symbols:
                lines.append("**Symbols:**")
                for s in symbols[:MAX_HYDRATED_SYMBOLS]:
                    lines.append(
                        f"  - `{s['name']}` line {s['line_start']}–{s['line_end']}: {s['signature']}"
                    )
            if imported_by:
                lines.append(f"**Imported by:** {', '.join(imported_by[:5])}")
        return "\n".join(lines)

    async def _maybe_summarize(self, messages: List[Dict]) -> List[Dict]:
        """If messages exceed SUMMARY_THRESHOLD, summarize old turns into a Technical State Summary."""
        if len(messages) <= SUMMARY_THRESHOLD:
            return messages

        client = self._get_client()
        preserve_tail = messages[-4:]
        to_summarize = messages[1:-4]

        if not to_summarize:
            return messages

        summary_content = "\n\n".join(
            f"{m['role'].upper()}: {str(m.get('content', ''))[:500]}"
            for m in to_summarize
            if m.get("content")
        )

        try:
            resp = await client.chat.completions.create(
                model=AGENT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a technical summarizer. Be concise and factual."},
                    {"role": "user", "content": (
                        "Summarize this technical session as a Technical State Summary. "
                        "Include: decisions made, files changed, current state, open problems.\n\n"
                        + summary_content[:6000]
                    )},
                ],
                max_tokens=800,
                temperature=0.1,
            )
            summary = resp.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Summarization failed: %s", exc)
            return messages

        logger.info("Summarized %d messages → 1 summary block", len(to_summarize))
        return [
            messages[0],  # system prompt
            {"role": "system", "content": f"## Technical State Summary\n{summary}"},
            *preserve_tail,
        ]

    async def _init_git_checkpoint(self) -> None:
        """Create architect/task-{id} branch as a checkpoint before first mutating tool."""
        if self._git_checkpoint_created:
            return
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_path, capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return  # Not a git repo

            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_path, capture_output=True, text=True, timeout=5,
            )
            base_branch = branch_result.stdout.strip() or "main"

            # Stash dirty working tree before branching (named stash for safe pop later)
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_path, capture_output=True, text=True, timeout=5,
            )
            has_changes = bool(status_result.stdout.strip())
            if has_changes:
                subprocess.run(
                    ["git", "stash", "push", "--include-untracked",
                     "-m", f"Architect pre-task backup {self.session_id[:8]}"],
                    cwd=self.project_path, capture_output=True, text=True, timeout=10,
                )

            task_branch = f"architect/task-{self.session_id[:8]}"
            checkout_result = subprocess.run(
                ["git", "checkout", "-b", task_branch],
                cwd=self.project_path, capture_output=True, text=True, timeout=10,
            )

            if has_changes:
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=self.project_path, capture_output=True, text=True, timeout=10,
                )

            if checkout_result.returncode != 0:
                logger.warning("Git checkpoint failed: %s", checkout_result.stderr.strip())
                return

            self._git_base_branch = base_branch
            self._git_task_branch = task_branch
            self._git_checkpoint_created = True

            if self._session:
                self._session.git_base_branch = base_branch
                self._session.git_task_branch = task_branch
                self._session.git_stash_created = has_changes

            logger.info("Git checkpoint: created branch %s from %s (stash: %s)", task_branch, base_branch, has_changes)
        except Exception as exc:
            logger.warning("Git checkpoint creation failed: %s", exc)

    async def _agentic_loop(self) -> AsyncIterator[ToolCallEvent]:
        client = self._get_client()
        system_prompt = self._build_system_prompt()

        # Stage 2: Planning (interactive mode only)
        if self.mode == "interactive" and self._session:
            async for evt in self._run_planning_stage():
                yield evt
            if self._session and self._session.status in ("stopped", "error"):
                return

        # Split plan into chunks so large tasks don't hit MAX_ITERATIONS
        plan_a = self._session.plan_a if self._session else None
        all_steps = plan_a.steps if plan_a else []
        chunks: List[List[Any]] = (
            [all_steps[i:i + CHUNK_SIZE] for i in range(0, len(all_steps), CHUNK_SIZE)]
            if all_steps else [[]]
        )
        total_chunks = len(chunks)

        if total_chunks > 1:
            yield ToolCallEvent(
                type="message",
                content=f"Large task ({len(all_steps)} steps) — splitting into {total_chunks} phases.",
            )

        prev_summary = ""

        # Emit one-time task briefing before execution starts (pure string — no LLM call)
        if plan_a and plan_a.steps:
            step_lines = "\n".join(
                f"  {s.index}. {s.description}"
                + (f"  [{', '.join(s.files_affected[:2])}]" if s.files_affected else "")
                for s in plan_a.steps
            )
            briefing = (
                f"🚀 Task: {self.task[:120]}\n\n"
                f"Execution plan — {len(plan_a.steps)} step{'s' if len(plan_a.steps) != 1 else ''}"
                f" ({int(plan_a.confidence * 100)}% confidence, {plan_a.risk_level} risk):\n"
                f"{step_lines}\n\n"
                f"▶ Starting Step 1..."
            )
        else:
            briefing = f"🚀 Starting: {self.task[:120]}"
        yield ToolCallEvent(type="message", content=briefing)

        for chunk_idx, chunk_steps in enumerate(chunks):
            if self._session and self._session.status in ("stopped", "error"):
                return

            if total_chunks > 1:
                step_range = f"{chunk_steps[0].index}–{chunk_steps[-1].index}" if chunk_steps else "?"
                phase_desc = chunk_steps[0].description if chunk_steps else ""
                yield ToolCallEvent(
                    type="message",
                    content=f"▶ Phase {chunk_idx + 1}/{total_chunks} — steps {step_range}: {phase_desc}",
                )

            # Build task message for this chunk
            if chunk_steps:
                step_list = "\n".join(f"{s.index}. {s.description}" for s in chunk_steps)
                if total_chunks > 1:
                    prefix = f"Previous phase summary:\n{prev_summary}\n\n" if prev_summary else ""
                    task_with_plan = (
                        f"{prefix}Task: {self.task}\n\n"
                        f"Execute ONLY these steps (phase {chunk_idx + 1}/{total_chunks}):\n{step_list}"
                    )
                else:
                    task_with_plan = f"{self.task}\n\nExecute this approved plan step by step:\n{step_list}"
            else:
                task_with_plan = self.task

            messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

            # Inject chat history only on first chunk
            if chunk_idx == 0:
                for hist_msg in self.chat_history:
                    if hist_msg.get("role") in ("user", "assistant") and hist_msg.get("content"):
                        messages.append({"role": hist_msg["role"], "content": hist_msg["content"]})

            messages.append({"role": "user", "content": task_with_plan})

            chunk_completed = False
            iteration = 0
            _stall_counts: Dict[str, int] = {}  # stall detection: "fn:args_hash" → count

            while True:
                iteration += 1
                logger.info("Phase %d/%d iteration %d", chunk_idx + 1, total_chunks, iteration)

                if iteration > MAX_ITERATIONS:
                    yield ToolCallEvent(
                        type="error",
                        error=(
                            f"Phase {chunk_idx + 1} hit the iteration limit ({MAX_ITERATIONS}) "
                            "without completing. The agent may be stuck in an exploration loop. "
                            "Stopping to prevent runaway execution."
                        ),
                    )
                    if self._session:
                        self._session.status = "error"
                    return

                # Check if session was stopped
                if self._session and self._session.status == "stopped":
                    yield ToolCallEvent(type="done", content="Stopped by user.", changes=self._changes)
                    return

                # Summarize if messages exceed threshold (Sprint 3.1)
                messages = await self._maybe_summarize(messages)

                # Inject working memory + active context as system messages before LLM call
                call_messages = list(messages)
                injections = []
                if self._working_memory:
                    mem_lines = [f"  - {p}: {s[:150]}" for p, s in self._working_memory.items()]
                    injections.append("## Files read this session (key facts):\n" + "\n".join(mem_lines))
                active_ctx = self._get_active_file_context(messages)
                if active_ctx:
                    injections.append(active_ctx)
                if injections:
                    call_messages.insert(1, {"role": "system", "content": "\n\n".join(injections)})

                # Force tool use on first iteration so agent doesn't just output analysis text
                tc_mode = "required" if iteration == 1 else "auto"

                try:
                    response = await client.chat.completions.create(
                        model=AGENT_MODEL,
                        messages=call_messages,
                        tools=TOOL_DEFINITIONS,
                        tool_choice=tc_mode,
                        max_tokens=4096,
                    )
                except Exception as exc:
                    logger.error("LLM call failed: %s", exc)
                    yield ToolCallEvent(type="error", error=f"LLM error: {exc}")
                    return

                msg = response.choices[0].message
                tool_calls = msg.tool_calls or []

                if not tool_calls:
                    # Phase complete — collect summary for next chunk
                    prev_summary = msg.content or ""
                    yield ToolCallEvent(type="message", content=prev_summary)
                    chunk_completed = True
                    if chunk_idx == total_chunks - 1:
                        # Last chunk — emit final done
                        yield ToolCallEvent(
                            type="done",
                            content=prev_summary,
                            changes=self._changes,
                            summary=prev_summary,
                        )
                        if self._session:
                            self._session.status = "complete"
                        return
                    break  # Move to next chunk

                # Append assistant message with tool_calls
                messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]})

                # Execute each tool call
                for tc in tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    yield ToolCallEvent(type="tool_call", tool=fn_name, args=fn_args)

                    # Stall detection: repeated identical (tool, args) calls signal a stuck loop
                    _stall_key = f"{fn_name}:{hash(tc.function.arguments)}"
                    _stall_counts[_stall_key] = _stall_counts.get(_stall_key, 0) + 1
                    if _stall_counts[_stall_key] >= MAX_STALL_REPEATS:
                        _stall_msg = (
                            f"STALL DETECTED: '{fn_name}' called with identical arguments "
                            f"{_stall_counts[_stall_key]} times without making progress. "
                            "You are stuck in a loop. You MUST either: "
                            "(1) make a concrete code change using edit_file or write_file, "
                            "(2) call think() to reassess your approach and try something different, "
                            "or (3) report that the task cannot be completed and explain why."
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": _stall_msg})
                        yield ToolCallEvent(type="tool_output", tool=fn_name, result=_stall_msg)
                        continue

                    # Validate required args before approval — short-circuit if missing
                    _arg_error: Optional[str] = None
                    if fn_name == "write_file" and not fn_args.get("path", "").strip():
                        _arg_error = "Error: write_file requires a 'path' argument — please specify the file path."
                    elif fn_name == "edit_file" and not fn_args.get("path", "").strip():
                        _arg_error = "Error: edit_file requires a 'path' argument — please specify the file path."
                    elif fn_name == "edit_file" and not fn_args.get("old_str", ""):
                        _arg_error = "Error: edit_file requires an 'old_str' argument — the exact string to replace."
                    elif fn_name == "run_command" and not fn_args.get("cmd", "").strip():
                        _arg_error = "Error: run_command requires a 'cmd' argument — please specify the command."
                    if _arg_error:
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": _arg_error})
                        yield ToolCallEvent(type="tool_output", tool=fn_name, result=_arg_error)
                        continue

                    # ── Read-before-write enforcement ─────────────────────────
                    if fn_name in ("write_file", "edit_file"):
                        _norm = Path(fn_args.get("path", "")).as_posix()
                        _target = Path(self.project_path) / _norm
                        if _target.exists() and _norm not in self._files_read:
                            _rbw_err = (
                                f"BLOCKED: You have not read '{_norm}' yet. "
                                f"Call read_file(path='{_norm}') first, then retry."
                            )
                            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _rbw_err})
                            yield ToolCallEvent(type="tool_output", tool=fn_name, result=_rbw_err)
                            continue

                    # ── write_file hard block on existing large files ──────────
                    if fn_name == "write_file":
                        _norm = Path(fn_args.get("path", "")).as_posix()
                        _target = Path(self.project_path) / _norm
                        if _target.exists():
                            try:
                                _line_count = len(_target.read_text(encoding="utf-8", errors="replace").splitlines())
                            except Exception:
                                _line_count = 0
                            if _line_count > 20:
                                _wf_err = (
                                    f"HARD BLOCK: '{_norm}' already exists ({_line_count} lines). "
                                    "write_file is not allowed on existing files. "
                                    "Use edit_file(path, old_str, new_str) for targeted changes. "
                                    "Read the file first if needed, then use edit_file."
                                )
                                messages.append({"role": "tool", "tool_call_id": tc.id, "content": _wf_err})
                                yield ToolCallEvent(type="tool_output", tool=fn_name, result=_wf_err)
                                continue

                    # ── think-before-write enforcement ───────────────────────
                    if fn_name in ("write_file", "edit_file") and not self._last_tool_was_think:
                        _think_err = (
                            f"BLOCKED: You must call think() before {fn_name}. "
                            "State what_i_know, what_i_will_change, and minimum_justification, "
                            "then retry the edit."
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": _think_err})
                        yield ToolCallEvent(type="tool_output", tool=fn_name, result=_think_err)
                        continue

                    # For mutating tools in interactive mode: request approval
                    is_mutating = fn_name in ("write_file", "edit_file", "run_command")

                    # Create git checkpoint on first mutating tool (Sprint 3.2)
                    if self.mode == "interactive" and is_mutating and not self._git_checkpoint_created:
                        await self._init_git_checkpoint()
                        if self._git_checkpoint_created:
                            yield ToolCallEvent(
                                type="message",
                                content=f"🔒 Workspace locked — task branch `{self._git_task_branch}` created. Use Rollback to undo all changes.",
                            )

                    if self.mode == "interactive" and is_mutating and self._session and not self.auto_approve:
                        # Compute preview diff for file operations
                        preview_diff = ""
                        if fn_name in ("write_file", "edit_file"):
                            preview_diff = self._compute_preview_diff(fn_name, fn_args)

                        yield ToolCallEvent(
                            type="approval_required",
                            tool=fn_name,
                            args=fn_args,
                            diff=preview_diff,
                            approval_required=True,
                        )

                        # Reset event and wait
                        self._session.approval_event.clear()
                        try:
                            await asyncio.wait_for(
                                self._session.approval_event.wait(),
                                timeout=APPROVAL_TIMEOUT,
                            )
                        except asyncio.TimeoutError:
                            yield ToolCallEvent(type="error", error="Approval timeout — agent stopped.")
                            self._session.status = "stopped"
                            return

                        action = self._session.approved_action
                        if action == "stop":
                            yield ToolCallEvent(type="done", content="Stopped by user.", changes=self._changes)
                            self._session.status = "stopped"
                            return
                        if action == "skip":
                            tool_result = "skipped by user"
                            if fn_name in ("write_file", "edit_file"):
                                pass
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": tool_result,
                            })
                            yield ToolCallEvent(type="tool_output", tool=fn_name, result=tool_result)
                            continue
                        if action == "edit" and self._session.edited_content is not None:
                            if fn_name in ("write_file", "edit_file"):
                                fn_args = dict(fn_args)
                                fn_args["content"] = self._session.edited_content
                                if fn_name == "edit_file":
                                    fn_name = "write_file"

                    # Execute tool (with escalation on failure for mutating tools)
                    file_change = None
                    try:
                        tool_result, file_change = await self._execute_tool(fn_name, fn_args)
                    except ToolExecutionError as tool_exc:
                        plan_b_msg = ""
                        if self._session and self._session.plan_b and not self._session.plan_b_exhausted:
                            plan_b = self._session.plan_b
                            plan_b_msg = f"\n\nPlan B is available. Switching approach: {plan_b.rationale}"

                        async for evt in self._run_escalation(tool_exc, iteration):
                            yield evt

                        if self._session and self._session.status in ("stopped", "error"):
                            return

                        escalation_action = self._session.escalation_action if self._session else None
                        if escalation_action == "stop":
                            yield ToolCallEvent(type="done", content="Stopped after escalation.", changes=self._changes)
                            if self._session:
                                self._session.status = "stopped"
                            return
                        elif escalation_action == "manual_fix":
                            tool_result = f"User applied manual fix for {tool_exc.fn_name}. Continuing."
                        elif self._session and self._session.escalation_instruction:
                            messages.append({
                                "role": "user",
                                "content": f"Previous attempt failed. User instruction: {self._session.escalation_instruction}{plan_b_msg}",
                            })
                            tool_result = f"Escalated — user provided alternative instruction."
                            self._session.escalation_instruction = None
                        else:
                            tool_result = f"Tool failed (escalated): {tool_exc.error_message}.{plan_b_msg}"

                    if file_change:
                        self._changes.append(file_change)

                    # Architecture lint after successful write/edit (Sprint 4.2)
                    if (
                        file_change
                        and file_change.applied
                        and fn_name in ("write_file", "edit_file")
                    ):
                        try:
                            from .arch_linter import check_file_violations
                            arch_violations = check_file_violations(
                                file_change.file, file_change.content, self.project_path
                            )
                            if arch_violations:
                                enriched_parts = []
                                for v in arch_violations:
                                    msg = v.format_message()
                                    # Auto-fix Prompt: search memory for a suitable alternative (Gemini suggestion)
                                    if v.kind == "forbidden":
                                        # Extract the forbidden import path from the violation detail
                                        import re as _re2
                                        m = _re2.search(r"import from '?([^'\"]+)'?", v.detail)
                                        if m:
                                            alt = self._find_memory_alternative(m.group(1))
                                            if alt:
                                                msg += f"\n  Memory suggestion: {alt}"
                                    enriched_parts.append(msg)
                                violation_msgs = "\n\n".join(enriched_parts)
                                tool_result = f"{tool_result}\n\n{violation_msgs}\n\nFix these architecture violations before continuing."
                                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
                                yield ToolCallEvent(type="tool_output", tool=fn_name, result=tool_result)
                                continue
                        except Exception as _linter_exc:
                            logger.debug("Arch linter error (non-fatal): %s", _linter_exc)

                    # Auto-lint after successful write/edit
                    if (
                        file_change
                        and file_change.applied
                        and fn_name in ("write_file", "edit_file")
                    ):
                        lint = AgentRunner._lint_file(file_change.file, self.project_path)
                        if not lint.get("skipped"):
                            if lint["ok"]:
                                lint_msg = f"Syntax OK: {file_change.file}"
                                tool_result = f"{tool_result} | {lint_msg}"
                            else:
                                err = lint.get("error", "unknown")
                                line = lint.get("line")
                                line_info = f" at line {line}" if line else ""
                                lint_msg = f"SyntaxError{line_info}: {err}"
                                retry_count = self._syntax_retries.get(file_change.file, 0) + 1
                                self._syntax_retries[file_change.file] = retry_count
                                if retry_count >= MAX_LINT_RETRIES:
                                    yield ToolCallEvent(
                                        type="error",
                                        error=f"Syntax fix failed after {MAX_LINT_RETRIES} attempts on {file_change.file}: {err}",
                                    )
                                    if self._session:
                                        self._session.status = "error"
                                    return
                                tool_result = (
                                    f"{tool_result} | LINT FAILED (attempt {retry_count}/{MAX_LINT_RETRIES}): "
                                    f"{lint_msg}. Fix the syntax error before continuing."
                                )

                    # Sticky Context: update module edit_hints after successful write/edit
                    if file_change and file_change.applied and fn_name in ("write_file", "edit_file"):
                        self._update_module_edit_hints(fn_name, fn_args, file_change)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })
                    yield ToolCallEvent(
                        type="tool_output",
                        tool=fn_name,
                        result=tool_result,
                        diff=file_change.diff if file_change else None,
                    )


    def _find_memory_alternative(self, forbidden_import: str) -> Optional[str]:
        """Search project_modules for a suitable alternative to a forbidden import path.

        For example: forbidden 'src/models/user' → find 'src/services/user_service.py'.
        Returns a suggestion string or None.
        """
        if not self.project_modules:
            return None
        # Extract resource keyword from the forbidden path (last path segment, strip wildcards)
        import re as _re
        keyword = _re.sub(r'[*\[\]{}]', '', forbidden_import).rstrip("/").split("/")[-1].lower()
        if len(keyword) < 3:
            return None

        # Prefer service/handler/facade modules over raw model/db modules
        preferred_tiers = ("service", "handler", "facade", "controller", "use_case", "usecase", "repository")
        candidates = []
        for mod in self.project_modules:
            mod_name = mod.get("name", "").lower()
            mod_path = mod.get("path", "").lower()
            if keyword in mod_name or keyword in mod_path:
                tier_score = sum(1 for t in preferred_tiers if t in mod_path or t in mod_name)
                candidates.append((tier_score, mod))
        if not candidates:
            return None
        # Pick highest tier score
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_mod = candidates[0][1]
        return f"Consider using `{best_mod['path']}` ({best_mod.get('purpose', '')[:80]})"

    def _update_module_edit_hints(self, fn_name: str, fn_args: Dict[str, Any], fc: FileChange) -> None:
        """Sticky Context (Gemini): after a successful write/edit, patch that module's edit_hints
        so future active-context hydration reflects the latest mental model."""
        path_norm = Path(fc.file).as_posix()
        ts = datetime.now().strftime("%H:%M")
        if fn_name == "edit_file":
            old_snippet = (fn_args.get("old_str", "") or "")[:60].replace("\n", "↵")
            new_snippet = (fn_args.get("new_str", "") or "")[:60].replace("\n", "↵")
            note = f"[{ts}] edited: «{old_snippet}» → «{new_snippet}»"
        else:
            note = f"[{ts}] write_file: {len(fc.content)} chars"

        for mod in self.project_modules:
            mod_path = mod.get("path", "")
            if mod_path == path_norm or mod_path.endswith(path_norm) or path_norm.endswith(mod_path):
                existing = (mod.get("edit_hints") or "").strip()
                # Prepend newest note; keep total under 400 chars
                updated = f"{note}\n{existing}" if existing else note
                mod["edit_hints"] = updated[:400]
                logger.debug("Sticky context updated edit_hints for %s", mod_path)
                break

    def _compute_preview_diff(self, fn_name: str, fn_args: Dict[str, Any]) -> str:
        """Compute a preview diff for write_file / edit_file without writing to disk."""
        from .diff import make_diff
        from .tools.file_tools import _resolve

        try:
            path = fn_args.get("path", "")
            resolved = _resolve(path, self.project_path)

            if fn_name == "write_file":
                new_content = fn_args.get("content", "")
                original = ""
                if resolved.exists():
                    original = resolved.read_text(encoding="utf-8", errors="replace")
                return make_diff(original, new_content, path)

            elif fn_name == "edit_file":
                old_str = fn_args.get("old_str", "")
                new_str = fn_args.get("new_str", "")
                if resolved.exists():
                    original = resolved.read_text(encoding="utf-8", errors="replace")
                    modified = original.replace(old_str, new_str, 1)
                    return make_diff(original, modified, path)
        except Exception as exc:
            logger.warning("Could not compute preview diff: %s", exc)

        return ""

    async def _execute_tool(
        self,
        fn_name: str,
        fn_args: Dict[str, Any],
    ) -> tuple[str, Optional[FileChange]]:
        """Execute a single tool call.

        Returns (result_str, FileChange | None).
        FileChange is only set for write_file / edit_file.
        In dry_run mode, file writes are simulated (not applied to disk).
        """
        from .tools.file_tools import read_file, write_file, edit_file, list_files
        from .tools.search_tools import search_code
        from .tools.shell_tools import run_command
        from .tools.git_tools import git_status, git_diff
        from .diff import make_diff

        pp = self.project_path

        try:
            # Reset think gate for every tool that is not think itself
            if fn_name != "think":
                self._last_tool_was_think = False

            if fn_name == "read_file":
                path = fn_args["path"]
                offset = int(fn_args.get("offset") or 0)
                limit = int(fn_args.get("limit") or 0)
                content = read_file(path, pp, offset=offset, limit=limit)
                # Record as read (for read-before-write enforcement)
                normalized = Path(path).as_posix()
                self._files_read.add(normalized)
                # Store first 400 chars as working memory snippet
                snippet = content[:400].replace('\n', ' ').strip()
                if snippet:
                    self._working_memory[normalized] = snippet
                # Truncate for messages to avoid token blow-up (only if no slice requested)
                if offset <= 0 and limit <= 0 and len(content) > 8000:
                    content = content[:8000] + "\n... (truncated — use offset+limit to read more)"
                return content, None

            elif fn_name == "list_files":
                pattern = fn_args.get("glob_pattern", "**/*")
                files = list_files(pattern, pp)
                return json.dumps(files), None

            elif fn_name == "search_code":
                pattern = fn_args["pattern"]
                fg = fn_args.get("file_glob", "*")
                results = search_code(pattern, pp, fg)
                return json.dumps(results[:50]), None

            elif fn_name == "git_status":
                return git_status(pp), None

            elif fn_name == "git_diff":
                path = fn_args.get("path")
                return git_diff(pp, path), None

            elif fn_name == "write_file":
                path = fn_args.get("path", "").strip()
                new_content = fn_args.get("content", "")
                if not path:
                    return "Error: write_file requires a 'path' argument — please specify the file path.", None

                # Compute diff
                from .tools.file_tools import _resolve
                resolved = _resolve(path, pp)
                original = ""
                if resolved.exists():
                    original = resolved.read_text(encoding="utf-8", errors="replace")
                    action = "edit"
                else:
                    action = "create"

                diff_str = make_diff(original, new_content, path)

                fc = FileChange(
                    file=path,
                    action=action,
                    content=new_content,
                    diff=diff_str,
                    applied=False,
                )

                if self.mode in ("apply", "interactive"):
                    AgentRunner._backup_file(path, pp)
                    write_file(path, new_content, pp)
                    fc.applied = True
                    return f"Written {path}", fc

                # dry_run — do not touch disk
                return f"[dry_run] Would write {path} ({len(new_content)} chars)", fc

            elif fn_name == "edit_file":
                path = fn_args.get("path", "").strip()
                old_str = fn_args.get("old_str", "")
                new_str = fn_args.get("new_str", "")
                if not path:
                    return "Error: edit_file requires a 'path' argument — please specify the file path.", None
                if not old_str:
                    return "Error: edit_file requires an 'old_str' argument — the exact string to replace.", None
                if old_str == new_str:
                    return (
                        "Error: old_str and new_str are identical — no change would be made. "
                        "Revise your edit so the new content is actually different from the original.",
                        None,
                    )

                from .tools.file_tools import _resolve
                resolved = _resolve(path, pp)
                original = resolved.read_text(encoding="utf-8", errors="replace")
                modified = original.replace(old_str, new_str, 1)
                diff_str = make_diff(original, modified, path)

                fc = FileChange(
                    file=path,
                    action="edit",
                    content=modified,
                    diff=diff_str,
                    applied=False,
                )

                if self.mode in ("apply", "interactive"):
                    AgentRunner._backup_file(path, pp)
                    edit_file(path, old_str, new_str, pp)
                    fc.applied = True
                    return f"Edited {path}", fc

                return f"[dry_run] Would edit {path}", fc

            elif fn_name == "think":
                # Reset flag for all other tools (non-think resets the gate)
                what_i_know = fn_args.get("what_i_know", "")
                what_i_will_change = fn_args.get("what_i_will_change", "")
                minimum_justification = fn_args.get("minimum_justification", "")
                if not (what_i_know and what_i_will_change and minimum_justification):
                    return "Error: think() requires all three fields: what_i_know, what_i_will_change, minimum_justification.", None
                self._last_tool_was_think = True
                return (
                    f"Thought recorded. Proceed with your change.\n"
                    f"Know: {what_i_know[:200]}\n"
                    f"Will change: {what_i_will_change[:200]}\n"
                    f"Justification: {minimum_justification[:200]}"
                ), None

            elif fn_name == "syntax_lint":
                path = fn_args["path"]
                lint_result = AgentRunner._lint_file(path, pp)
                if lint_result.get("skipped"):
                    return f"Lint skipped (unsupported file type or linter not installed): {path}", None
                if lint_result["ok"]:
                    return f"Syntax OK: {path}", None
                err = lint_result.get("error", "unknown error")
                line = lint_result.get("line")
                line_info = f" at line {line}" if line else ""
                return f"SyntaxError{line_info}: {err}", None

            elif fn_name == "run_command":
                cmd = fn_args.get("cmd", "").strip()
                if not cmd:
                    return "Error: run_command requires a 'cmd' argument — please specify the command to run.", None
                timeout = fn_args.get("timeout", 30)

                if self.mode == "dry_run":
                    return f"[dry_run] Would run: {cmd}", None

                result = run_command(cmd, pp, timeout=timeout, shell_unrestricted=self.shell_unrestricted)
                output = (
                    f"returncode: {result['returncode']}\n"
                    f"stdout:\n{result['stdout']}\n"
                    f"stderr:\n{result['stderr']}"
                )
                return output, None

            else:
                return f"Unknown tool: {fn_name}", None

        except Exception as exc:
            logger.warning("Tool %s failed: %s", fn_name, exc)
            if fn_name in ("write_file", "edit_file", "run_command"):
                raise ToolExecutionError(fn_name, fn_args, str(exc))
            return f"Error in {fn_name}: {exc}", None


# ---------------------------------------------------------------------------
# Helper: collect all changes from a completed run
# ---------------------------------------------------------------------------

async def run_agent(
    task: str,
    project_path: str,
    project_modules: List[Dict[str, Any]],
    mode: str = "dry_run",
    context: Optional[str] = None,
) -> tuple[List[ToolCallEvent], List[FileChange]]:
    """Run the agent to completion and return all events + file changes.

    Convenience wrapper for non-streaming (dry_run / apply) modes.
    """
    runner = AgentRunner(task, project_path, project_modules, mode=mode, context=context)
    events: List[ToolCallEvent] = []
    async for event in runner.run():
        events.append(event)
    return events, runner.changes


__all__ = [
    "AgentRunner",
    "FileChange",
    "ToolCallEvent",
    "AgentSession",
    "ExecutionPlan",
    "PlanStep",
    "ToolExecutionError",
    "get_session",
    "create_session",
    "_agent_sessions",
    "run_agent",
    "TOOL_DEFINITIONS",
]
