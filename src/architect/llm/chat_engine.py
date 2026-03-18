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

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, List, Optional, Dict, Any

from .client import LLMClient, create_llm_client, DEFAULT_MODEL
from .model_router import ModelRouter, create_model_router

logger = logging.getLogger(__name__)

# Max context chunks injected into the prompt
MAX_CONTEXT_CHUNKS = 8
# Max conversation turns kept in memory
MAX_HISTORY_TURNS = 10


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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _retrieve_context(
        self, query: str, project_id: Optional[str]
    ) -> Dict[str, Any]:
        """Pull relevant context from code memory."""
        context: Dict[str, Any] = {
            "patterns": [],
            "semantic_chunks": [],
            "keyword_hits": [],
            "modules": [],
        }

        # Inject stored LLM analysis modules for this project
        if project_id and project_id in self._project_modules:
            context["modules"] = self._project_modules[project_id]

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

        # Inject per-file module summaries from LLM analysis
        modules = context.get("modules", [])
        if modules:
            lines.append("## Analyzed Files (from last analysis run)")
            for mod in modules[:30]:  # cap to avoid token overflow
                name = mod.get("name") or mod.get("file", "unknown")
                purpose = mod.get("purpose") or mod.get("summary", "")
                patterns_in = mod.get("patterns", [])
                line = f"- **{name}**: {purpose}"
                if patterns_in:
                    line += f" [patterns: {', '.join(patterns_in[:3])}]"
                lines.append(line)
            lines.append("")

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


__all__ = [
    "ChatEngine",
    "ChatSession",
    "ChatMessage",
    "create_chat_engine",
    "get_or_create_session",
]
