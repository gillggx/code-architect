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

import asyncio
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

        MAX_TOOL_ROUNDS = 12
        # Rough token budget: stop adding more context when estimate exceeds this
        # (1 char ≈ 0.25 tokens; 80k tokens ≈ 320k chars)
        TOKEN_CHAR_BUDGET = 280_000
        MAX_SEARCH_CALLS = 3  # prevent search-loop with weak models

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

        logger.info("stream_chat_v2 start: model=%s project=%s", model, session.project_id)

        # 4. Add user turn to history
        session.add("user", user_message)

        # Strategy B: identify files the model SHOULD read first
        # Pull from jit_snippets (already matched by keyword) + top modules
        suggested_paths: list[str] = []
        for s in context.get("jit_snippets", [])[:3]:
            p = s.get("file", "")
            if p and p not in suggested_paths:
                suggested_paths.append(p)
        if not suggested_paths:
            for mod in context.get("modules", [])[:2]:
                p = mod.get("full_path") or mod.get("path", "")
                if p and p not in suggested_paths:
                    suggested_paths.append(p)

        edit_count = 0
        search_count = 0

        # Phase 1: tool loop
        for _round in range(MAX_TOOL_ROUNDS):
            # Context size guard — estimate tokens before calling LLM
            ctx_chars = sum(len(str(m.get("content") or "")) for m in messages)
            logger.info(
                "Tool round %d/%d — ctx≈%dk chars (~%dk tokens) model=%s",
                _round + 1, MAX_TOOL_ROUNDS,
                ctx_chars // 1000,
                ctx_chars // 4000,
                model,
            )
            if ctx_chars > TOKEN_CHAR_BUDGET:
                logger.warning(
                    "stream_chat_v2: context budget exceeded (%d chars), stopping tool loop early",
                    ctx_chars,
                )
                yield {
                    "type": "error",
                    "data": f"Context too large ({ctx_chars // 4000}k tokens estimated) — stopping tool loop. Partial answer below.",
                }
                break

            # Strategy B: force read_file on round 0 if we have relevant files
            if _round == 0 and suggested_paths:
                forced_tool_choice: Any = {"type": "function", "function": {"name": "read_file"}}
                logger.info("Round 0: forcing tool_choice=read_file, suggested=%s", suggested_paths)
            else:
                forced_tool_choice = "auto"

            msg = await self.llm.complete_with_tools(
                messages, CHAT_TOOLS, model=model, tool_choice=forced_tool_choice
            )

            # Token limit hit — surface to user and stop
            if msg.get("__token_limit__"):
                logger.error("stream_chat_v2: token limit hit at round %d", _round + 1)
                yield {
                    "type": "error",
                    "data": "Token limit reached. The conversation context is too large. Try starting a fresh chat or asking a more specific question.",
                }
                session.add("assistant", "[Token limit reached]")
                yield {"type": "done"}
                return

            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # No more tool calls — move to streaming phase
                logger.info("Tool loop ended at round %d (no tool calls)", _round + 1)
                break

            # Execute each tool call
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                logger.info(
                    "  → %s(%s)",
                    fn_name,
                    ", ".join(f"{k}={repr(v)[:60]}" for k, v in fn_args.items()),
                )
                yield {"type": "tool_thinking", "tool": fn_name, "args": fn_args}

                # Track search calls to prevent loops
                if fn_name == "search_files":
                    search_count += 1
                    if search_count > MAX_SEARCH_CALLS:
                        logger.warning(
                            "search_files called %d times — injecting anti-loop guidance",
                            search_count,
                        )
                        tool_content = (
                            f"[search_files call #{search_count} blocked] "
                            "You have already searched multiple times. "
                            "Stop searching and answer based on what you've found, "
                            "or call read_file on a specific file you identified."
                        )
                        yield {"type": "tool_result", "tool": fn_name, "result": tool_content}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_content,
                        })
                        continue

                result = execute_chat_tool(fn_name, fn_args, project_path)
                logger.info("  ← %s: ok=%s result_len=%d", fn_name, result.get("ok"), len(str(result.get("result", ""))))

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

    async def stream_chat_direct(
        self,
        session: ChatSession,
        user_message: str,
        project_path: str,
        analysis_status: Optional[str] = None,
        recent_changes: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Direct mode — Python-driven pipeline. No LLM tool loop.

        Flow:
          1. Python: keyword-match Architecture Map → find relevant files
          2. Python: read those files directly (emit tool_thinking events for UI)
          3. LLM: single streaming call with full context → answer

        Works well with weak models. No tool-use required.
        Yields same event shapes as stream_chat_v2 (chunk, done, error).
        """
        # Token budget constants (model context = 128k tokens = 512k chars)
        # Reserve 80k chars for system prompt + arch map + response buffer
        MODEL_CONTEXT_CHARS = 512_000
        OVERHEAD_CHARS      = 80_000
        FILE_CHAR_BUDGET    = MODEL_CONTEXT_CHARS - OVERHEAD_CHARS  # 432k chars ≈ 108k tokens
        MAPREDUCE_THRESHOLD = FILE_CHAR_BUDGET                       # single-pass if under this
        MAX_FILE_CHARS      = 20_000  # per-file cap (≈5k tokens, ~500 lines)

        # 1. Retrieve context + identify relevant files
        context = await self._retrieve_context(user_message, session.project_id)

        # Hardcode-specific: magic numbers, credentials, hardcoded values
        _hardcode_re = re.compile(
            r"(hardcode|hard.code|magic.number|hard.coded|寫死|硬編碼|audit|grep|列出所有|找出所有|所有檔案|scan)",
            re.IGNORECASE,
        )
        # General scan: code review, problem-finding, quality check
        _review_re = re.compile(
            r"(問題|有什麼問題|哪些問題|架構問題|code.quality|code.smell|"
            r"improvement|what.*wrong|any.*issue|review|檢查|掃描)",
            re.IGNORECASE,
        )
        is_hardcode_query = bool(_hardcode_re.search(user_message))
        is_wide_scan      = bool(_review_re.search(user_message))
        is_audit_query    = is_hardcode_query or is_wide_scan   # controls file loading

        # 2a. Audit queries: read ALL source files, auto-switch to MapReduce if too large
        # 2b. Normal queries: load only relevant files (JIT-matched)
        _source_exts = {'.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', '.java', '.kt', '.cs', '.rb'}
        _skip_dirs = {'/node_modules/', '/dist/', '/.git/', '/build/', '/__pycache__/'}

        loaded_files: list[Dict[str, str]] = []
        ctx_chars = 0

        if is_audit_query:
            yield {"type": "mode_note", "data": "Direct mode (per-file deep analysis)"}

            # Collect ALL source files from Architecture Map
            all_source_paths: list[str] = []
            for mod in context.get("modules", []):
                p = mod.get("full_path") or mod.get("path", "")
                if not p or not os.path.isfile(p):
                    continue
                if any(skip in p for skip in _skip_dirs):
                    continue
                if os.path.splitext(p)[1].lower() in _source_exts and p not in all_source_paths:
                    all_source_paths.append(p)

            logger.info(
                "stream_chat_direct per-file: %d source files, scan_type=%s",
                len(all_source_paths), "hardcode" if is_hardcode_query else "review",
            )

            model = self.llm.model if (self.llm._use_custom or not self.llm._use_openrouter) \
                else self.router.route(user_message).primary_model
            session.add("user", user_message)
            scan_type = "hardcode" if is_hardcode_query else "review"
            async for event in self._per_file_analysis(
                all_source_paths, project_path, model, session,
                user_message, scan_type=scan_type, max_file_chars=MAX_FILE_CHARS,
            ):
                yield event
            return
        else:
            # Normal query: load JIT-matched files only
            MAX_FILES = 4
            candidate_paths: list[str] = []
            for s in context.get("jit_snippets", [])[:MAX_FILES]:
                p = s.get("file", "")
                if p and p not in candidate_paths:
                    candidate_paths.append(p)
            if not candidate_paths and context.get("modules"):
                _skip_exts = {'.md', '.mdx', '.txt', '.rst', '.yml', '.yaml', '.toml', '.lock'}
                for mod in context["modules"][:MAX_FILES * 2]:
                    p = mod.get("full_path") or mod.get("path", "")
                    if not p or not os.path.isfile(p) or p in candidate_paths:
                        continue
                    ext = os.path.splitext(p)[1].lower()
                    fname = os.path.basename(p).lower()
                    if ext in _skip_exts:
                        continue
                    if ext == '.json' and fname != 'package.json':
                        continue
                    candidate_paths.append(p)
                    if len(candidate_paths) >= MAX_FILES:
                        break

            for path in candidate_paths:
                if ctx_chars >= FILE_CHAR_BUDGET:
                    break
                yield {"type": "tool_thinking", "tool": "read_file", "args": {"path": path}}
                try:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        content = f.read(MAX_FILE_CHARS)
                    if len(content) == MAX_FILE_CHARS:
                        content += "\n... [truncated]"
                    loaded_files.append({"path": path, "content": content})
                    ctx_chars += len(content)
                except OSError as e:
                    logger.warning("  could not read %s: %s", path, e)

        logger.info(
            "stream_chat_direct single-pass: model=%s hardcode=%s wide_scan=%s files_loaded=%d ctx_chars=%d",
            self.llm.model, is_hardcode_query, is_wide_scan, len(loaded_files), ctx_chars,
        )

        # 3. Build system prompt + inject all loaded file contents
        system_prompt = self._build_system_prompt(
            session.project_id, context,
            analysis_status=analysis_status,
            recent_changes=recent_changes,
            tool_use=False,
        )

        if loaded_files:
            if is_hardcode_query:
                scan_note = (
                    "\nAnalyze each file carefully. Distinguish between:\n"
                    "- TRUE hardcode problems: magic numbers, business logic values, credentials, URLs that should be configurable\n"
                    "- NORMAL defaults: reasonable default values for props/params, standard config like `outDir: 'dist'`\n"
                    "Only report TRUE hardcode problems with file path and line number.\n"
                )
            elif is_wide_scan:
                scan_note = (
                    "\nDo a thorough code review. Report ALL types of problems:\n"
                    "- Bugs: incorrect behavior, crashes, wrong output, data loss\n"
                    "- Missing features: error boundaries, input validation, error handling\n"
                    "- Logic errors: edge cases not handled, incorrect algorithms\n"
                    "- Design issues: violated patterns, tight coupling, unclear responsibilities\n"
                    "- Documentation mismatches: comments/JSDoc that contradict actual code\n"
                    "For each issue: cite exact file path + line number + quote the relevant code.\n"
                    "Separate TRUE bugs from design improvement opportunities.\n"
                )
            else:
                scan_note = ""
            file_section = [f"\n## Source Code (all project source files){scan_note}"]
            for lf in loaded_files:
                rel = os.path.relpath(lf["path"], project_path) if project_path else lf["path"]
                file_section.append(f"\n### {rel}\n```\n{lf['content']}\n```")
            system_prompt += "\n" + "\n".join(file_section)
        else:
            system_prompt += "\n\n## Note\nCould not read source files. Answer from Architecture Map above."

        # Build messages
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(session.to_openai_messages())
        messages.append({"role": "user", "content": user_message})

        # Route model (same logic as v2)
        if self.llm._use_custom or not self.llm._use_openrouter:
            model = self.llm.model
        else:
            decision = self.router.route(user_message)
            model = decision.primary_model

        # 4. Add user turn to history
        session.add("user", user_message)

        # 5. Single streaming LLM call
        reply_chunks: list[str] = []
        async for chunk in self.llm.stream(messages, model=model):
            reply_chunks.append(chunk)
            yield {"type": "chunk", "data": chunk}

        session.add("assistant", "".join(reply_chunks))
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Per-file deep analysis helper
    # ------------------------------------------------------------------

    async def _per_file_analysis(
        self,
        all_source_paths: list,
        project_path: str,
        model: str,
        session: "ChatSession",
        user_message: str,
        scan_type: str,
        max_file_chars: int,
    ):
        """
        Per-file deep analysis: each source file gets its own dedicated LLM call.

        Phase 1 (Map):    for each file → LLM extracts findings as JSON
        Phase 2 (Reduce): consolidation call → stream final formatted report
        """
        if not all_source_paths:
            yield {"type": "chunk", "data": "No source files found to analyze."}
            session.add("assistant", "No source files found to analyze.")
            yield {"type": "done"}
            return

        # Build per-file prompts based on scan_type
        if scan_type == "hardcode":
            def _make_file_prompt(rel_path: str, content: str) -> str:
                return (
                    f"Analyze this file for hardcoded values: {rel_path}\n\n"
                    "Find ALL hardcoded values that should be configurable.\n"
                    "Return ONLY a JSON array — no prose, no markdown wrapper.\n"
                    "Each item: {\"file\": str, \"line\": int, \"value\": str, \"type\": str, \"severity\": str, \"reason\": str}\n"
                    "Types: magic_number | hardcoded_string | hardcoded_url | hardcoded_credential | business_logic_constant\n"
                    "Severity: critical | high | medium | low\n"
                    "SKIP: reasonable prop/param defaults, standard build config (outDir, port 5173, es2020), test fixtures.\n"
                    "If nothing found, return []\n\n"
                    f"```\n{content}\n```"
                )
        else:  # review
            def _make_file_prompt(rel_path: str, content: str) -> str:
                return (
                    f"Do a thorough code review of this file: {rel_path}\n\n"
                    "Report ALL problems you find with MANDATORY code quotes.\n"
                    "Return ONLY a JSON array — no prose, no markdown wrapper.\n"
                    "Each item: {\n"
                    "  \"file\": str,\n"
                    "  \"line\": int,\n"
                    "  \"category\": str,\n"
                    "  \"severity\": str,\n"
                    "  \"description\": str,\n"
                    "  \"code_quote\": str,\n"
                    "  \"suggestion\": str\n"
                    "}\n"
                    "Categories: bug | logic_error | missing_validation | error_handling | design_issue | doc_mismatch\n"
                    "Severity: critical | high | medium | low\n"
                    "MANDATORY: code_quote must contain the EXACT lines that prove the issue. "
                    "If you cannot quote the code, do NOT include the item.\n"
                    "Separate TRUE bugs from design improvement opportunities via category.\n"
                    "If nothing found, return []\n\n"
                    f"```\n{content}\n```"
                )

        total = len(all_source_paths)
        all_findings: list = []

        async def _collect_stream(msgs: list, mdl: str) -> str:
            result = ""
            async for chunk in self.llm.stream(msgs, model=mdl):
                result += chunk
            return result

        # ── Phase 1: Per-file LLM calls ───────────────────────────────
        for idx, path in enumerate(all_source_paths):
            rel = os.path.relpath(path, project_path) if project_path else path
            yield {
                "type": "mode_note",
                "data": f"Analyzing {idx + 1}/{total}: {rel}",
            }
            yield {"type": "tool_thinking", "tool": "read_file", "args": {"path": path}}

            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read(max_file_chars)
                if len(content) == max_file_chars:
                    content += "\n... [truncated]"
            except OSError as e:
                logger.warning("_per_file_analysis: cannot read %s: %s", path, e)
                continue

            file_prompt = _make_file_prompt(rel, content)
            file_messages = [
                {"role": "system", "content": file_prompt},
                {"role": "user", "content": "Analyze and return findings as JSON array."},
            ]

            try:
                raw = ""
                raw = await asyncio.wait_for(_collect_stream(file_messages, model), timeout=60.0)

                # Strip markdown code fence if LLM wrapped the JSON
                stripped = raw.strip()
                if stripped.startswith("```"):
                    lines_raw = stripped.splitlines()
                    inner = lines_raw[1:-1] if lines_raw[-1].strip() == "```" else lines_raw[1:]
                    stripped = "\n".join(inner)

                file_findings = json.loads(stripped)
                if isinstance(file_findings, list):
                    # Ensure file field is set correctly
                    for item in file_findings:
                        if isinstance(item, dict):
                            item.setdefault("file", rel)
                    all_findings.extend(file_findings)
                    logger.info("_per_file_analysis [%d/%d] %s: %d findings", idx + 1, total, rel, len(file_findings))
            except asyncio.TimeoutError:
                logger.warning("_per_file_analysis: timeout on %s, skipping", rel)
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning("_per_file_analysis: parse error on %s: %s", rel, exc)
                # Keep raw in findings for consolidation phase to surface
                if raw.strip():
                    all_findings.append({"_raw": raw[:500], "_file": rel, "_parse_error": str(exc)})

        # ── Phase 2: Consolidation ────────────────────────────────────
        yield {"type": "mode_note", "data": f"Consolidating {len(all_findings)} findings across {total} files…"}

        if not all_findings:
            msg = "No issues found across all source files."
            yield {"type": "chunk", "data": msg}
            session.add("assistant", msg)
            yield {"type": "done"}
            return

        findings_json = json.dumps(all_findings, ensure_ascii=False, indent=2)

        if scan_type == "hardcode":
            reduce_instructions = (
                "Group findings by severity: Critical (credentials/URLs) > High (business logic) > Medium (magic numbers) > Low.\n"
                "For each issue: file path, line number, the hardcoded value, fix suggestion.\n"
                "Also note any patterns (e.g., timeouts hardcoded across multiple files).\n"
                "Summarise what was correctly treated as normal defaults."
            )
        else:
            reduce_instructions = (
                "Group findings into two sections:\n"
                "## True Bugs (must fix)\n"
                "  - Categories: bug, logic_error, missing_validation, error_handling\n"
                "  - Sort by severity (critical first)\n"
                "## Design Improvements (should fix)\n"
                "  - Categories: design_issue, doc_mismatch\n"
                "For each item: file path + line + quoted code + description + suggestion.\n"
                "At the end: a brief executive summary of overall code health."
            )

        reduce_prompt = (
            f"Original question: {user_message}\n\n"
            f"Below are findings extracted individually from {total} source files.\n"
            "Format them into a clear, well-structured report in the same language as the original question.\n"
            f"{reduce_instructions}\n\n"
            f"Findings:\n```json\n{findings_json}\n```"
        )
        reduce_messages = [
            {"role": "system", "content": reduce_prompt},
            {"role": "user", "content": user_message},
        ]

        reply_chunks: list = []
        async for chunk in self.llm.stream(reduce_messages, model=model, max_tokens=16384):
            reply_chunks.append(chunk)
            yield {"type": "chunk", "data": chunk}

        session.add("assistant", "".join(reply_chunks))
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Audit MapReduce helper (legacy — kept for reference)
    # ------------------------------------------------------------------

    async def _audit_mapreduce(
        self,
        all_source_paths: list[str],
        project_path: str,
        model: str,
        session: "ChatSession",
        user_message: str,
        max_file_chars: int,
    ):
        """
        MapReduce audit for large projects that exceed single-pass context budget.

        Phase 1 (Map):    split files into batches → LLM extracts hardcodes as JSON per batch
        Phase 2 (Reduce): consolidate all JSON findings → stream final formatted report
        """
        MAPREDUCE_BATCH_CHARS = 300_000  # safe per-batch file budget

        # Build batches
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_chars = 0
        for path in all_source_paths:
            try:
                estimated = min(os.path.getsize(path), max_file_chars)
            except OSError:
                estimated = max_file_chars
            if current_chars + estimated > MAPREDUCE_BATCH_CHARS and current_batch:
                batches.append(current_batch)
                current_batch = [path]
                current_chars = estimated
            else:
                current_batch.append(path)
                current_chars += estimated
        if current_batch:
            batches.append(current_batch)

        yield {
            "type": "mode_note",
            "data": f"MapReduce mode: {len(all_source_paths)} files → {len(batches)} batches",
        }
        logger.info("_audit_mapreduce: %d files, %d batches", len(all_source_paths), len(batches))

        # ── Phase 1: Map ──────────────────────────────────────────────
        all_findings: list[dict] = []

        for batch_idx, batch_paths in enumerate(batches):
            yield {
                "type": "mode_note",
                "data": f"Scanning batch {batch_idx + 1}/{len(batches)} ({len(batch_paths)} files)…",
            }

            batch_files: list[dict] = []
            for path in batch_paths:
                yield {"type": "tool_thinking", "tool": "read_file", "args": {"path": path}}
                try:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        content = f.read(max_file_chars)
                    if len(content) == max_file_chars:
                        content += "\n... [truncated]"
                    batch_files.append({"path": path, "content": content})
                except OSError as e:
                    logger.warning("MapReduce batch %d: cannot read %s: %s", batch_idx + 1, path, e)

            if not batch_files:
                continue

            file_section = "\n\n".join(
                f"### {os.path.relpath(lf['path'], project_path) if project_path else lf['path']}\n```\n{lf['content']}\n```"
                for lf in batch_files
            )
            extraction_prompt = (
                "You are a code auditor. Find ALL hardcoded values in the files below.\n"
                "Return ONLY a JSON array — no prose, no markdown wrapper.\n"
                "Each item: {\"file\": str, \"line\": int, \"value\": str, \"type\": str, \"reason\": str}\n"
                "Types: magic_number | hardcoded_string | hardcoded_url | hardcoded_credential | business_logic_constant\n"
                "SKIP: reasonable prop/param defaults, standard build config (outDir, port 5173, es2020), test fixtures.\n"
                "If nothing found, return []\n\n"
                + file_section
            )
            map_messages = [
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": "Extract hardcodes as JSON array."},
            ]

            try:
                raw = ""
                async for chunk in self.llm.stream(map_messages, model=model):
                    raw += chunk

                # Strip markdown code fence if LLM wrapped the JSON
                stripped = raw.strip()
                if stripped.startswith("```"):
                    lines = stripped.splitlines()
                    inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                    stripped = "\n".join(inner)

                batch_findings = json.loads(stripped)
                if isinstance(batch_findings, list):
                    all_findings.extend(batch_findings)
                    logger.info("MapReduce batch %d: %d findings", batch_idx + 1, len(batch_findings))
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning("MapReduce batch %d parse error: %s", batch_idx + 1, exc)
                all_findings.append({"_raw": raw, "_batch": batch_idx + 1, "_parse_error": str(exc)})

        # ── Phase 2: Reduce ───────────────────────────────────────────
        yield {"type": "mode_note", "data": f"Consolidating {len(all_findings)} findings…"}

        if not all_findings:
            yield {"type": "chunk", "data": "No hardcode issues found across all source files."}
            session.add("assistant", "No hardcode issues found across all source files.")
            yield {"type": "done"}
            return

        findings_json = json.dumps(all_findings, ensure_ascii=False, indent=2)
        reduce_prompt = (
            f"Original question: {user_message}\n\n"
            "Below are hardcode findings extracted from all source files in batches.\n"
            "Format them into a clear, well-structured report in the same language as the original question.\n"
            "Group by severity: Critical (credentials/URLs) > High (business logic) > Medium (magic numbers) > Low (style defaults).\n"
            "For each issue: file path, line number, the hardcoded value, fix suggestion.\n"
            "Also summarise what was correctly treated as normal defaults.\n\n"
            f"Findings:\n```json\n{findings_json}\n```"
        )
        reduce_messages = [
            {"role": "system", "content": reduce_prompt},
            {"role": "user", "content": user_message},
        ]

        reply_chunks: list[str] = []
        async for chunk in self.llm.stream(reduce_messages, model=model):
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
            r'(hardcode|hard.code|magic.number|literal|audit|所有檔案|全部|scan all|grep|'
            r'問題|有什麼問題|哪些問題|架構問題|code.quality|code.smell|'
            r'improvement|what.*wrong|any.*issue|review|檢查|掃描)',
            query_lower,
        ))
        max_snippets = 12 if is_audit else 4

        scored: List[tuple[int, dict]] = []
        for mod in modules:
            # Prefer absolute full_path; fall back to relative path
            path = mod.get("full_path") or mod.get("path", "")
            if not path or not os.path.isfile(path):
                continue

            ext = os.path.splitext(path)[1].lower()
            fname = os.path.basename(path).lower()

            # Always skip docs and config files — they are stale or not ground truth.
            # Exception: package.json is useful for dependency questions.
            _always_skip_exts = {'.md', '.mdx', '.txt', '.rst'}
            _config_exts = {'.json', '.yml', '.yaml', '.toml', '.lock'}
            if ext in _always_skip_exts:
                continue
            if ext in _config_exts and fname != 'package.json':
                continue

            mod_name = (mod.get("name") or "").lower()
            # Build a searchable string from module navigation fields
            combined = " ".join(filter(None, [
                mod_name,
                mod.get("purpose", ""),
                " ".join(mod.get("public_interface", [])),
            ])).lower()

            SOURCE_EXTS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', '.java', '.kt', '.swift', '.cs', '.cpp', '.c', '.rb', '.php'}
            is_source = ext in SOURCE_EXTS

            if is_audit:
                score = 1  # include everything for audit queries
            else:
                mod_words = set(re.findall(r'\w+', combined))
                overlap = query_words & mod_words
                score = len(overlap) + (5 if mod_name in query_lower else 0)
                if score == 0:
                    continue
                if is_source:
                    score += 3

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
        suggested_paths: Optional[List[str]] = None,
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

        # --- Tool behavior rules go FIRST (before context) so they are not buried ---
        if tool_use:
            lines.append(
                "## How to Use Your Tools — FOLLOW THIS SEQUENCE EVERY TIME\n"
                "\n"
                "**STEP 1 — Look at the Architecture Map below.**\n"
                "  Find the module most relevant to the question. Each entry shows the EXACT file path.\n"
                "\n"
                "**STEP 2 — Call `read_file(path)` using that path.**\n"
                "  Read the file before answering any implementation question. Do NOT guess from memory.\n"
                "\n"
                "**STEP 3 — Answer based on the actual code you read.**\n"
                "  Cite file + line numbers. Be specific.\n"
                "\n"
                "**`search_files` is a last resort.** Use it ONLY when the Architecture Map has no\n"
                "matching file path for the question. Limit: max 2 calls per response.\n"
                "After every search, you MUST call `read_file` on the best result before searching again.\n"
                "\n"
                "**Edit rules:**\n"
                "- Simple change (1 file, <10 lines): use `edit_file`, then confirm what changed.\n"
                "- Complex change (2+ files, new files, refactor): use `escalate_to_edit_agent` immediately.\n"
                "- NEVER ask the user to paste code — read it yourself with `read_file`.\n"
                "\n"
                "**Example of correct flow:**\n"
                "```\n"
                "User: 'How does the auth middleware work?'\n"
                "→ Check map: auth_middleware → /project/src/middleware/auth.py\n"
                "→ Call: read_file('/project/src/middleware/auth.py')\n"
                "→ Answer from the code\n"
                "```\n"
                "\n"
                "**Anti-hallucination rules (CRITICAL):**\n"
                "- If read_file returns an error or says 'is a directory', do NOT guess the file content.\n"
                "  Pick a specific file from the listing and call read_file again.\n"
                "- If search_files returns 'No matches found', do NOT invent results.\n"
                "  Try a different query or state clearly that nothing was found.\n"
                "- NEVER fabricate code examples. Only quote code you have actually read with read_file.\n"
                "- If you cannot read the required file, say so explicitly instead of guessing.\n"
                "\n"
                "**Citation requirement — MANDATORY:**\n"
                "- For EVERY problem or issue you report, you MUST quote the exact lines of code that prove it.\n"
                "- Format: `filename:line_number` followed by the quoted code.\n"
                "- If you cannot find or quote the specific code, do NOT report it as a problem.\n"
                "- Do not report issues based on absence of something unless you have read the full file.\n"
                "\n"
                "**Bug vs Design choice — report them separately:**\n"
                "- TRUE bugs: incorrect behavior, crashes, wrong output, data loss, security issues.\n"
                "- Design choices / improvement opportunities: valid patterns that could be better.\n"
                "- Never escalate a design choice to 'critical' or 'P0'. Keep severity accurate.\n"
                "\n"
                "**Source code vs documentation priority:**\n"
                "- `.md` files marked [doc] in the Architecture Map are documentation — they describe\n"
                "  what the code *should* do, but may be outdated. They are NOT ground truth.\n"
                "- When asked about bugs, problems, code quality, or implementation details:\n"
                "  1. FIRST read source files (.ts, .py, .js, etc.) to see what the code actually does.\n"
                "  2. THEN read [doc] files only for background context if needed.\n"
                "- Never answer a code question by only reading documentation files.\n"
                "\n"
                "**Files you must NEVER read (unless explicitly asked):**\n"
                "- `.md`, `.mdx`, `.txt`, `.rst` — documentation files. They may be stale or opinionated.\n"
                "- `.json` (except `package.json`), `.yml`, `.yaml`, `.toml`, `.lock` — config/data files.\n"
                "  Exception: if the user explicitly asks about README, CHANGELOG, or config files, you may read them.\n"
                "- If the Architecture Map shows REPORT, RECOMMENDATION, SUMMARY, COMPLETION in the filename — skip it entirely.\n"
            )

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
                # MAP_THEN_JIT / FULL_CONTEXT: compact map for navigation with full paths
                # Only source files listed with paths — doc files shown as a name-only summary
                lines.append("## Architecture Map (use for navigation — read files for details)")
                lines.append("Source code files only. Do NOT read documentation files unless the user asks.\n")
                _doc_exts = {'.md', '.mdx', '.txt', '.rst'}
                _skip_map_exts = {'.json', '.yml', '.yaml', '.toml', '.lock'}
                _source_mods = []
                _doc_names = []
                for mod in modules[:40]:
                    fp = mod.get("full_path") or mod.get("path", "")
                    ext = os.path.splitext(fp)[1].lower() if fp else ""
                    fname = os.path.basename(fp).lower() if fp else ""
                    if ext in _doc_exts:
                        _doc_names.append(mod.get("name") or fname)
                    elif ext in _skip_map_exts and fname != 'package.json':
                        pass  # skip config/data files entirely
                    else:
                        _source_mods.append(mod)
                for mod in _source_mods[:25]:
                    name = mod.get("name") or mod.get("file", "unknown")
                    purpose = mod.get("purpose", "")
                    critical = mod.get("critical_path", False)
                    full_path = mod.get("full_path") or mod.get("path", "")
                    path_label = f" → `{full_path}`" if full_path else ""
                    lines.append(f"- **{name}**{' [critical]' if critical else ''}{path_label}: {purpose}")
                if _doc_names:
                    lines.append(f"\nDocumentation files (do not read unless asked): {', '.join(_doc_names[:10])}")
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
