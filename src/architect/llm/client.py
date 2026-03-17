"""
LLM Client — OpenRouter (primary) with Ollama fallback.

Supports streaming via Server-Sent Events.
Model IDs follow OpenRouter convention: "provider/model-name".

Environment variables:
    OPENROUTER_API_KEY  — required for OpenRouter
    OPENROUTER_BASE_URL — default https://openrouter.ai/api/v1
    OLLAMA_BASE_URL     — default http://localhost:11434
    DEFAULT_LLM_MODEL   — default anthropic/claude-opus-4-5
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "anthropic/claude-opus-4-5")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class LLMClient:
    """
    Unified LLM client.

    Priority:
      1. OpenRouter  (if OPENROUTER_API_KEY set)
      2. Ollama      (local fallback)

    All public methods are async generators that yield text chunks so the
    caller can stream the response straight to the client (SSE / WebSocket).
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._api_key = os.getenv("OPENROUTER_API_KEY", "")
        self._use_openrouter = bool(self._api_key)

        if self._use_openrouter:
            logger.info("LLMClient: using OpenRouter (%s)", model)
        else:
            logger.info("LLMClient: no OPENROUTER_API_KEY — falling back to Ollama")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a chat completion, yielding text chunks.

        Args:
            messages: OpenAI-style message list
                      [{"role": "system"|"user"|"assistant", "content": "..."}]
            model: Override default model for this call.

        Yields:
            str text chunks as they arrive from the API.
        """
        chosen_model = model or self.model

        if self._use_openrouter:
            async for chunk in self._stream_openrouter(messages, chosen_model):
                yield chunk
        else:
            async for chunk in self._stream_ollama(messages, chosen_model):
                yield chunk

    async def complete(
        self,
        messages: list[dict],
        model: Optional[str] = None,
    ) -> str:
        """
        Non-streaming completion — collects all chunks and returns full string.
        Useful for A2A calls where you need the full response at once.
        """
        chunks: list[str] = []
        async for chunk in self.stream(messages, model=model):
            chunks.append(chunk)
        return "".join(chunks)

    # ------------------------------------------------------------------
    # OpenRouter (OpenAI-compatible)
    # ------------------------------------------------------------------

    async def _stream_openrouter(
        self, messages: list[dict], model: str
    ) -> AsyncIterator[str]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("openai package not installed — pip install openai")
            yield "[Error: openai package missing]"
            return

        client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=OPENROUTER_BASE_URL,
        )

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                extra_headers={
                    "HTTP-Referer": "https://github.com/code-architect-agent",
                    "X-Title": "Code Architect Agent",
                },
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            logger.error("OpenRouter error: %s", exc)
            yield f"[LLM Error: {exc}]"

    # ------------------------------------------------------------------
    # Ollama (local fallback)
    # ------------------------------------------------------------------

    async def _stream_ollama(
        self, messages: list[dict], model: str
    ) -> AsyncIterator[str]:
        """Stream from Ollama using its OpenAI-compatible endpoint."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("openai package not installed")
            yield "[Error: openai package missing]"
            return

        # Ollama exposes OpenAI-compatible endpoint at /v1
        client = AsyncOpenAI(
            api_key="ollama",
            base_url=f"{OLLAMA_BASE_URL}/v1",
        )

        # Map OpenRouter model IDs to Ollama model names
        ollama_model = _to_ollama_model(model)

        try:
            stream = await client.chat.completions.create(
                model=ollama_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            logger.error("Ollama error: %s", exc)
            yield f"[LLM Error: {exc}]"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _to_ollama_model(openrouter_id: str) -> str:
    """
    Map OpenRouter model IDs to Ollama model names.
    Falls back to the last segment of the ID.

    Examples:
        anthropic/claude-opus-4-5 → llama3  (no Claude in Ollama)
        qwen/qwen2.5-72b          → qwen2.5:72b
        openai/gpt-4o             → llama3
    """
    mapping: dict[str, str] = {
        "anthropic/claude-opus-4-5": "llama3",
        "anthropic/claude-sonnet-4-5": "llama3",
        "qwen/qwen2.5-72b-instruct": "qwen2.5:72b",
        "qwen/qwen3-235b-a22b": "qwen2.5:72b",
        "openai/gpt-4o": "llama3",
        "openai/gpt-4": "llama3",
    }
    return mapping.get(openrouter_id, openrouter_id.split("/")[-1])


def create_llm_client(
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> LLMClient:
    """Factory function — returns configured LLMClient."""
    return LLMClient(model=model, temperature=temperature)


__all__ = ["LLMClient", "create_llm_client", "DEFAULT_MODEL"]
