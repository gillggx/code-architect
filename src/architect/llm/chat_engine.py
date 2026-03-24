"""
Chat Engine — orchestrates RAG retrieval + LLM generation.

Flow:
  1. unified_search() pulls relevant code context from project memory
  2. Build system prompt with context + detected patterns
  3. Route to model via ModelRouter
  4. Stream response via LLMClient
  5. Conversation history kept in-session only (not persisted to memory)

Memory is read-only here — it stores code analysis results, not chat logs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, List, Optional, Dict, Any, Literal

from .client import LLMClient, create_llm_client, DEFAULT_MODEL
from .model_router import ModelRouter, create_model_router

logger = logging.getLogger(__name__)

# Max context chunks injected into the prompt
MAX_CONTEXT_CHUNKS = 8
# Max conversation turns kept in memory
MAX_HISTORY_TURNS = 10

# ---------------------------------------------------------------------------
# Query classification
# ---------------------------------------------------------------------------

QueryRoute = Literal["MAP_ONLY", "MAP_THEN_JIT", "FULL_CONTEXT"]

_MAP_ONLY_PATTERNS = re.compile(
    r"(影響|affect|depend|import|誰呼叫|who call|called by|uses|用到|"
    r"架構|architecture|pattern|模式|禁止|forbidden|規範|convention|"
    r"side effect|有沒有副作用|critical|核心路徑|overview|概覽|"
    r"what does .+ do|這個.*做什麼|purpose|用途)",
    re.IGNORECASE,
)

_FULL_CONTEXT_PATTERNS = re.compile(
    r"(整個流程|entire flow|end.to.end|從頭到尾|all files|所有檔案|"
    r"跨.*模組|across.*module|system.wide|全系統|"
    r"hardcode|hard.code|magic.number|hard.coded|寫死|硬編碼|"
    r"audit|scan all|grep.*all|列出所有|找出所有|有多少)",
    re.IGNORECASE,
)

_JIT_PATTERNS = re.compile(
    r"(怎麼實作|how.*implement|實作細節|implementation|邏輯|logic|"
    r"怎麼寫的|how is .+ written|細節|detail|具體|specific|"
    r"幫我.*改|幫我.*加|幫我.*修|add|edit|modify|fix|change|implement|"
    r"show me|讓我看|給我看|the code|程式碼)",
    re.IGNORECASE,
)


def _classify_query(query: str) -> QueryRoute:
    """
    Route the query to the appropriate context strategy:
      MAP_ONLY     — answer directly from L2 contract map (no file reads)
      MAP_THEN_JIT — use map to locate, then read targeted code snippet
      FULL_CONTEXT — need code from multiple files (rare)
    """
    if _FULL_CONTEXT_PATTERNS.search(query):
        return "FULL_CONTEXT"
    if _JIT_PATTERNS.search(query):
        return "MAP_THEN_JIT"
    if _MAP_ONLY_PATTERNS.search(query):
        return "MAP_ONLY"
    # Default: try map first; JIT if map has enough location info
    return "MAP_THEN_JIT"


@dataclass
class ChatMessage:
    role: str   # "user" | "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ChatSession:
    project_id: Optional[str]
    history: List[ChatMessage] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.history.append(ChatMessage(role=role, content=content))
        # Keep last N turns (each turn = user + assistant)
        if len(self.history) > MAX_HISTORY_TURNS * 2:
            self.history = self.history[-(MAX_HISTORY_TURNS * 2):]

    def to_openai_messages(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self.history]


class ChatEngine:
    """
    Main entry point for chat.

    Usage::

        engine = ChatEngine()
        async for chunk in engine.stream_chat(session, "How does auth work?"):
            print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        model_router: Optional[ModelRouter] = None,
        rag_integration=None,   # RAGMemoryIntegration | None
        memory=None,            # MemoryTier1 | None
    ) -> None:
        self.llm = llm_client or create_llm_client()
        self.router = model_router or create_model_router()
        self.rag = rag_integration
        self.memory = memory
        # project_id → list of module dicts from LLM analysis
        self._project_modules: Dict[str, List[Dict[str, Any]]] = {}

    def update_project_context(self, project_id: str, modules: List[Dict[str, Any]]) -> None:
        """Store analysis modules so they can be injected into chat context."""
        self._project_modules[project_id] = modules
        logger.info("ChatEngine: stored %d modules for project %s", len(modules), project_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        session: ChatSession,
        user_message: str,
        analysis_status: Optional[str] = None,
        recent_changes: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream LLM response for user_message.

        Retrieves code context from memory/RAG, builds prompt,
        routes to optimal model, and streams the reply.

        Yields:
            str text chunks from the LLM.
        """
        # 1. Retrieve context from code memory
        context = await self._retrieve_context(user_message, session.project_id)

        # 2. Build message list
        messages = self._build_messages(session, user_message, context, analysis_status=analysis_status, recent_changes=recent_changes)

        # 3. Route to model
        # Skip router when using custom/Ollama endpoints — they don't support
        # OpenRouter model IDs like "anthropic/claude-sonnet-4-5".
        if self.llm._use_custom or not self.llm._use_openrouter:
            model = self.llm.model
            logger.info("Chat → model=%s (custom/local endpoint, routing skipped)", model)
        else:
            decision = self.router.route(user_message)
            model = decision.primary_model
            logger.info("Chat → model=%s complexity=%s", model, decision.reason)

        # 4. Add user message to history before streaming
        session.add("user", user_message)

        # 5. Stream and accumulate assistant reply
        reply_chunks: list[str] = []
        async for chunk in self.llm.stream(messages, model=model):
            reply_chunks.append(chunk)
            yield chunk

        # 6. Store assistant reply in session history
        session.add("assistant", "".join(reply_chunks))

    async def complete_chat(
        self,
        session: ChatSession,
        user_message: str,
    ) -> str:
        """Non-streaming version — returns full response string. Used for A2A."""
        chunks: list[str] = []
        async for chunk in self.stream_chat(session, user_message):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream_chat_v2(
        self,
        session: ChatSession,
        user_message: str,
        project_path: str,
        analysis_status: Optional[str] = None,
        recent_changes: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Tool-use chat mode.

        Yields dicts with these shapes:
          {"type": "tool_thinking", "tool": str, "args": dict}
          {"type": "tool_result",   "tool": str, "result": str}
          {"type": "tool_edit",     "path": str, "diff": str, "result": str}
          {"type": "escalate",      "task": str, "reason": str}
          {"type": "chunk",         "data": str}
          {"type": "done"}
          {"type": "error",         "data": str}

        Phase 1: tool loop (non-streaming, max 8 rounds).
        Phase 2: stream final answer as "chunk" events.
        """
        from ..api.tools.chat_tools import CHAT_TOOLS, execute_chat_tool

        MAX_TOOL_ROUNDS = 8

        # 1. Retrieve context (same as stream_chat)
        context = await self._retrieve_context(user_message, session.project_id)

        # 2. Build initial messages with tool-aware system prompt
        system_prompt = self._build_system_prompt(
            session.project_id, context,
            analysis_status=analysis_status,
            recent_changes=recent_changes,
            tool_use=True,
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(session.to_openai_messages())
        messages.append({"role": "user", "content": user_message})

        # 3. Route model
        if self.llm._use_custom or not self.llm._use_openrouter:
            model = self.llm.model
        else:
            decision = self.router.route(user_message)
            model = decision.primary_model

        # 4. Add user turn to history
        session.add("user", user_message)

        edit_count = 0

        # Phase 1: tool loop
        for _round in range(MAX_TOOL_ROUNDS):
            msg = await self.llm.complete_with_tools(messages, CHAT_TOOLS, model=model)
            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # No more tool calls — move to streaming phase
                break

            # Execute each tool call
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                yield {"type": "tool_thinking", "tool": fn_name, "args": fn_args}

                result = execute_chat_tool(fn_name, fn_args, project_path)

                if result.get("escalate"):
                    yield {
                        "type": "escalate",
                        "task": result["task"],
                        "reason": result["reason"],
                    }
                    session.add("assistant", f"[Escalated to Edit Agent: {result['task']}]")
                    return

                if result.get("edited"):
                    edit_count += 1
                    yield {
                        "type": "tool_edit",
                        "path": result["path"],
                        "diff": result.get("diff", ""),
                        "result": result["result"],
                    }

                tool_content = result["result"] if result["ok"] else f"[Error: {result['error']}]"
                yield {"type": "tool_result", "tool": fn_name, "result": tool_content}

                # Check edit escalation threshold (>3 edits → suggest escalation)
                if edit_count > 3:
                    yield {
                        "type": "escalate",
                        "task": user_message,
                        "reason": f"Made {edit_count} file edits — complex change better handled by Edit Agent",
                    }
                    session.add("assistant", "[Auto-escalated after multiple edits]")
                    return

                # Append tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_content,
                })

        # Phase 2: stream final answer from last assistant message or a fresh call
        final_content = msg.get("content", "") if not msg.get("tool_calls") else ""
        if final_content:
            # LLM already produced a final answer in the last round
            reply_chunks: list[str] = []
            for chunk in _chunk_string(final_content, 64):
                reply_chunks.append(chunk)
                yield {"type": "chunk", "data": chunk}
            session.add("assistant", "".join(reply_chunks))
        else:
            # Need one more streaming call for the final answer
            reply_chunks = []
            async for chunk in self.llm.stream(messages, model=model):
                reply_chunks.append(chunk)
                yield {"type": "chunk", "data": chunk}
            session.add("assistant", "".join(reply_chunks))

        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _retrieve_context(
        self, query: str, project_id: Optional[str]
    ) -> Dict[str, Any]:
        """Pull relevant context from code memory, routed by query type."""
        route = _classify_query(query)
        logger.info("Query route: %s for: %s", route, query[:60])

        context: Dict[str, Any] = {
            "patterns": [],
            "semantic_chunks": [],
            "keyword_hits": [],
            "modules": [],
            "route": route,
            "jit_snippets": [],   # Phase 3: targeted code reads
        }

        # Inject stored LLM analysis modules for this project
        if project_id and project_id in self._project_modules:
            context["modules"] = self._project_modules[project_id]

        # Phase 3: JIT code retrieval — locate relevant symbols then read only those lines
        if route in ("MAP_THEN_JIT", "FULL_CONTEXT") and project_id:
            context["jit_snippets"] = self._jit_retrieve(query, project_id, route=route)

        if not self.rag and not self.memory:
            return context

        try:
            if self.rag and self.memory:
                results = await self.rag.unified_search(
                    query,
                    memory=self.memory,
                    top_k=MAX_CONTEXT_CHUNKS,
                    confidence_threshold=0.60,
                )
                context["keyword_hits"] = [
                    {"id": r.artifact_id, "type": r.artifact_type, "score": r.confidence}
                    for r in (results.get("keyword_results") or [])
                ]
                context["semantic_chunks"] = [
                    {"content": r.content, "score": r.score, "source": r.source}
                    for r in (results.get("semantic_results") or [])
                ]
                context["patterns"] = [
                    {"id": r.artifact_id, "score": r.confidence}
                    for r in (results.get("artifact_results") or [])
                ]
            elif self.memory:
                refs = self.memory.search(query, confidence_threshold=0.60)
                context["keyword_hits"] = [
                    {"id": r.artifact_id, "type": r.artifact_type, "score": r.confidence}
                    for r in refs
                ]
        except Exception as exc:
            logger.warning("Context retrieval failed: %s", exc)

        return context

    def _build_messages(
        self,
        session: ChatSession,
        user_message: str,
        context: Dict[str, Any],
        analysis_status: Optional[str] = None,
        recent_changes: Optional[str] = None,
    ) -> list[dict]:
        """Assemble the OpenAI-style message list for the LLM."""

        system_prompt = self._build_system_prompt(session.project_id, context, analysis_status=analysis_status, recent_changes=recent_changes)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Inject conversation history (without the current user turn)
        messages.extend(session.to_openai_messages())

        # Current user turn
        messages.append({"role": "user", "content": user_message})

        return messages

    def _jit_retrieve(self, query: str, project_id: str, route: str = "MAP_THEN_JIT") -> List[Dict[str, Any]]:
        """
        Phase 3 — JIT Code Retrieval.
        Use the contract map to locate relevant symbols, then read only those
        lines from disk. Returns a list of {file, symbol, lines, code} dicts.

        Priority: full_path > path (full_path is absolute, path may be relative).
        """
        modules = self._project_modules.get(project_id, [])
        if not modules:
            return []

        query_lower = query.lower()
        query_words = set(re.findall(r'\w+', query_lower))
        snippets: List[Dict[str, Any]] = []

        # FULL_CONTEXT or audit-style queries ("audit", "hardcode", "all files") —
        # scan all source files instead of trying to match keywords
        is_audit = route == "FULL_CONTEXT" or bool(re.search(
            r'(hardcode|hard.code|magic.number|literal|audit|所有檔案|全部|scan all|grep)',
            query_lower,
        ))
        max_snippets = 8 if is_audit else 4

        scored: List[tuple[int, dict]] = []
        for mod in modules:
            # Prefer absolute full_path; fall back to relative path
            path = mod.get("full_path") or mod.get("path", "")
            if not path or not os.path.isfile(path):
                continue

            # Skip non-source files for audit scans (skip docs, configs)
            ext = os.path.splitext(path)[1].lower()
            if is_audit and ext in ('.md', '.json', '.yml', '.yaml', '.toml', '.txt', '.lock'):
                continue

            mod_name = (mod.get("name") or "").lower()
            # Build a searchable string from module navigation fields
            combined = " ".join(filter(None, [
                mod_name,
                mod.get("purpose", ""),
                " ".join(mod.get("public_interface", [])),
            ])).lower()

            if is_audit:
                score = 1  # include everything for audit queries
            else:
                mod_words = set(re.findall(r'\w+', combined))
                overlap = query_words & mod_words
                score = len(overlap) + (5 if mod_name in query_lower else 0)
                if score == 0:
                    continue

            scored.append((score, mod, path))  # type: ignore[arg-type]

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, mod, path in scored:  # type: ignore[misc]
            symbols = mod.get("symbols", [])

            # Find matching symbol by name
            matched_syms = [
                s for s in symbols
                if s.get("name", "").lower() in query_lower
            ]

            if matched_syms and not is_audit:
                # Read only the matching function/class lines
                for sym in matched_syms[:2]:
                    start = max(0, sym.get("line_start", 1) - 1)
                    end = sym.get("line_end", start + 40)
                    code = self._read_lines(path, start, end)
                    if code:
                        snippets.append({
                            "file": path,
                            "symbol": sym.get("name"),
                            "lines": f"{start+1}-{end}",
                            "code": code,
                        })
            else:
                # Read first 60 lines (enough to spot hardcoded values)
                read_lines = 80 if is_audit else 50
                code = self._read_lines(path, 0, read_lines)
                if code:
                    snippets.append({
                        "file": path,
                        "symbol": None,
                        "lines": f"1-{read_lines}",
                        "code": code,
                    })

            if len(snippets) >= max_snippets:
                break

        return snippets

    @staticmethod
    def _read_lines(path: str, start: int, end: int) -> str:
        """Read lines [start, end) from a file. Returns empty string on error."""
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
            return "".join(all_lines[start:end])
        except OSError:
            return ""

    def _load_soul(self, project_id: Optional[str]) -> str:
        """Load SOUL.md for the current project."""
        from ..api.soul import load_soul, DEFAULT_SOUL
        if not project_id:
            return DEFAULT_SOUL
        path_file = os.path.join("architect_memory", project_id, "project_path.txt")
        try:
            with open(path_file) as f:
                project_path = f.read().strip()
            return load_soul(project_path)
        except OSError:
            return DEFAULT_SOUL

    def _build_system_prompt(
        self,
        project_id: Optional[str],
        context: Dict[str, Any],
        analysis_status: Optional[str] = None,
        recent_changes: Optional[str] = None,
        tool_use: bool = False,
    ) -> str:
        """Build system prompt with retrieved code context."""

        soul = self._load_soul(project_id)

        lines = [
            "You are Code Architect Agent — an expert in software architecture, design patterns, and code analysis.",
            "You answer questions about codebases that have been analyzed and stored in your memory system.",
            "Be precise, cite specific files/patterns when available, and acknowledge uncertainty.",
            "",
            "## Agent Soul & Personality",
            soul,
            "",
        ]

        if analysis_status:
            lines.append(f"## ⚠️ IMPORTANT: {analysis_status}")
            lines.append("")

        if recent_changes:
            lines.append("## Recent Git Activity (what was recently worked on)")
            lines.append(recent_changes)
            lines.append("")

        if project_id:
            lines.append(f"Current project: {project_id}")
            lines.append("")

        # Inject semantic context
        semantic = context.get("semantic_chunks", [])
        if semantic:
            lines.append("## Relevant Code Context (from memory)")
            for i, chunk in enumerate(semantic[:MAX_CONTEXT_CHUNKS], 1):
                src = chunk.get("source", "unknown")
                score = chunk.get("score", 0)
                content = chunk.get("content", "").strip()[:800]
                lines.append(f"\n### [{i}] {src} (relevance: {score:.2f})")
                lines.append(f"```\n{content}\n```")
            lines.append("")

        # Inject detected patterns
        patterns = context.get("patterns", [])
        if patterns:
            ids = ", ".join(p["id"] for p in patterns[:5])
            lines.append(f"## Detected Patterns in This Project\n{ids}\n")

        # Inject keyword hits summary
        kw_hits = context.get("keyword_hits", [])
        if kw_hits:
            hit_types = list({h["type"] for h in kw_hits})
            lines.append(f"## Memory Artifacts Referenced\nTypes found: {', '.join(hit_types)}\n")

        # Inject per-file module contracts from LLM analysis
        modules = context.get("modules", [])
        route = context.get("route", "MAP_THEN_JIT")

        if modules:
            if route == "MAP_ONLY":
                # MAP_ONLY: inject module summaries for navigation
                lines.append("## Architecture Map")
                for mod in modules[:30]:
                    name = mod.get("name") or mod.get("file", "unknown")
                    purpose = mod.get("purpose", "")
                    iface = mod.get("public_interface", [])
                    critical = mod.get("critical_path", False)
                    imported_by = mod.get("imported_by", [])
                    edit_hints = mod.get("edit_hints", "")

                    lines.append(f"\n### {name}{' [critical]' if critical else ''}")
                    lines.append(f"**Purpose:** {purpose}")
                    if iface:
                        lines.append(f"**Interface:** {', '.join(iface[:4])}")
                    if imported_by:
                        lines.append(f"**Used by:** {', '.join(imported_by[:4])}")
                    if edit_hints and edit_hints.lower() not in ("none", ""):
                        lines.append(f"**Edit hints:** {edit_hints}")
                lines.append("")

            else:
                # MAP_THEN_JIT / FULL_CONTEXT: compact map for navigation
                lines.append("## Architecture Map (use for navigation — read files for details)")
                for mod in modules[:30]:
                    name = mod.get("name") or mod.get("file", "unknown")
                    purpose = mod.get("purpose", "")
                    critical = mod.get("critical_path", False)
                    lines.append(f"- **{name}**{' [critical]' if critical else ''}: {purpose}")
                lines.append("")

        # Phase 3: inject JIT code snippets
        jit_snippets = context.get("jit_snippets", [])
        if jit_snippets:
            lines.append(
                "## Source Code (read directly from disk for this query)\n"
                "**IMPORTANT: Answer the question by analyzing the actual code below.**\n"
                "Do NOT ask the user to provide code — you already have it.\n"
            )
            for s in jit_snippets:
                sym_label = f" — `{s['symbol']}`" if s.get("symbol") else ""
                lines.append(f"\n### {s['file']}{sym_label} (lines {s['lines']})")
                lines.append(f"```\n{s['code'].strip()}\n```")
            lines.append("")
        elif route in ("MAP_THEN_JIT", "FULL_CONTEXT") and modules:
            # JIT retrieval ran but found nothing readable — tell LLM explicitly
            lines.append(
                "## Note on Source Code\n"
                "Source files could not be read for this query (files may have moved or be inaccessible). "
                "Answer from the architecture map above. If you cannot answer without code, say so clearly "
                "and tell the user which specific file(s) to share.\n"
            )

        if not semantic and not patterns and not kw_hits and not modules:
            lines.append(
                "Note: No project has been analyzed yet. "
                "Ask the user to run an analysis first, or answer from general knowledge."
            )

        if tool_use:
            lines.append(
                "\n## Tools Available\n"
                "You have tools to read and modify the codebase directly:\n\n"
                "- `read_file(path)` — Read a file. Use before answering implementation questions.\n"
                "- `search_files(query, directory?, file_pattern?)` — Grep across files.\n"
                "- `edit_file(path, old_str, new_str)` — Apply a targeted single-file edit.\n"
                "  - Use ONLY for simple changes: 1 file, <10 lines changed, straightforward fix.\n"
                "- `escalate_to_edit_agent(task, reason)` — Hand off to Edit Agent.\n"
                "  - Use when: 2+ files need changing, new files required, complex refactor.\n\n"
                "**Rules:**\n"
                "1. NEVER ask the user to share code — read files yourself.\n"
                "2. For write requests: assess complexity first.\n"
                "   - Simple (1 file, <10 lines): edit_file, then confirm what you changed.\n"
                "   - Complex (multi-file, architectural): escalate_to_edit_agent immediately.\n"
                "3. After reading files, answer directly without re-asking.\n"
            )

        lines.append(
            "\nAnswer concisely. Use markdown. Cite source files when available."
        )

        return "\n".join(lines)


# ------------------------------------------------------------------
# Session registry (in-process, not persisted)
# ------------------------------------------------------------------

_sessions: Dict[str, ChatSession] = {}


def get_or_create_session(
    session_id: str,
    project_id: Optional[str] = None,
) -> ChatSession:
    """Get existing session or create a new one."""
    if session_id not in _sessions:
        _sessions[session_id] = ChatSession(project_id=project_id)
    elif project_id and _sessions[session_id].project_id != project_id:
        # Project switched — start fresh
        _sessions[session_id] = ChatSession(project_id=project_id)
    return _sessions[session_id]


def create_chat_engine(
    rag_integration=None,
    memory=None,
    model: str = DEFAULT_MODEL,
) -> ChatEngine:
    """Factory — returns a configured ChatEngine."""
    return ChatEngine(
        llm_client=create_llm_client(model=model),
        model_router=create_model_router(),
        rag_integration=rag_integration,
        memory=memory,
    )


def _chunk_string(text: str, size: int):
    """Yield text in chunks of up to `size` chars (for simulating streaming)."""
    for i in range(0, len(text), size):
        yield text[i: i + size]


__all__ = [
    "ChatEngine",
    "ChatSession",
    "ChatMessage",
    "create_chat_engine",
    "get_or_create_session",
]
