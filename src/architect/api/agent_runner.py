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

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional, Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / model config
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
AGENT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "anthropic/claude-sonnet-4-5")
MAX_ITERATIONS = 40
CHUNK_SIZE = 12  # Max plan steps per execution phase
APPROVAL_TIMEOUT = 300  # 5 minutes


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
            "description": "Read a file from the project",
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
    ) -> None:
        self.task = task
        self.project_path = project_path
        self.project_modules = project_modules
        self.mode = mode  # "dry_run" | "apply" | "interactive"
        self.context = context
        self.session_id = session_id or str(uuid4())
        self.chat_history: List[Dict[str, str]] = chat_history or []

        self._changes: List[FileChange] = []
        self._plan: List[str] = []
        self._session: Optional[AgentSession] = None

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
            lines.append("## Project modules (from analysis)")
            for mod in self.project_modules[:40]:
                name = mod.get("name") or mod.get("file", "unknown")
                purpose = mod.get("purpose") or mod.get("summary", "")
                patterns_list = mod.get("patterns", [])
                line = f"- **{name}**: {purpose}"
                if patterns_list:
                    line += f" [patterns: {', '.join(patterns_list[:3])}]"
                lines.append(line)
            lines.append("")

        if self.context:
            lines.append("## Additional context")
            lines.append(self.context)
            lines.append("")

        lines += [
            "## Agent Soul & Personality",
            self._soul,
            "",
            "## Rules",
            "- Read files before editing them.",
            "- Use edit_file for targeted changes, write_file for new files or rewrites.",
            "- Run tests/linters after making changes to verify correctness.",
            "- When done, provide a concise summary of what you changed and why.",
            "- Never write to .env, .key, .pem files or files matching secrets.*",
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

        for chunk_idx, chunk_steps in enumerate(chunks):
            if self._session and self._session.status in ("stopped", "error"):
                return

            if total_chunks > 1:
                step_range = f"{chunk_steps[0].index}–{chunk_steps[-1].index}" if chunk_steps else "?"
                yield ToolCallEvent(
                    type="message",
                    content=f"Phase {chunk_idx + 1}/{total_chunks} — steps {step_range}",
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

            for iteration in range(MAX_ITERATIONS):
                logger.info("Phase %d/%d iteration %d/%d", chunk_idx + 1, total_chunks, iteration + 1, MAX_ITERATIONS)

                # Check if session was stopped
                if self._session and self._session.status == "stopped":
                    yield ToolCallEvent(type="done", content="Stopped by user.", changes=self._changes)
                    return

                # Force tool use on first iteration so agent doesn't just output analysis text
                tc_mode = "required" if iteration == 0 else "auto"

                try:
                    response = await client.chat.completions.create(
                        model=AGENT_MODEL,
                        messages=messages,
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

                    # For mutating tools in interactive mode: request approval
                    is_mutating = fn_name in ("write_file", "edit_file", "run_command")
                    if self.mode == "interactive" and is_mutating and self._session:
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

            # Chunk hit MAX_ITERATIONS — continue to next chunk with summary
            if not chunk_completed:
                prev_summary = f"Completed {len(self._changes)} file changes so far (hit iteration limit on phase {chunk_idx + 1})."
                if chunk_idx == total_chunks - 1:
                    yield ToolCallEvent(
                        type="done",
                        content=f"Reached maximum iterations ({MAX_ITERATIONS}).",
                        changes=self._changes,
                        summary=f"Completed {len(self._changes)} file changes.",
                    )
                    if self._session:
                        self._session.status = "complete"
                    return

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
            if fn_name == "read_file":
                path = fn_args["path"]
                content = read_file(path, pp)
                # Truncate for messages to avoid token blow-up
                if len(content) > 8000:
                    content = content[:8000] + "\n... (truncated)"
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
                path = fn_args["path"]
                new_content = fn_args["content"]

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
                    write_file(path, new_content, pp)
                    fc.applied = True
                    return f"Written {path}", fc

                # dry_run — do not touch disk
                return f"[dry_run] Would write {path} ({len(new_content)} chars)", fc

            elif fn_name == "edit_file":
                path = fn_args["path"]
                old_str = fn_args["old_str"]
                new_str = fn_args["new_str"]

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
                    edit_file(path, old_str, new_str, pp)
                    fc.applied = True
                    return f"Edited {path}", fc

                return f"[dry_run] Would edit {path}", fc

            elif fn_name == "run_command":
                cmd = fn_args["cmd"]
                timeout = fn_args.get("timeout", 30)

                if self.mode == "dry_run":
                    return f"[dry_run] Would run: {cmd}", None

                result = run_command(cmd, pp, timeout=timeout)
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
