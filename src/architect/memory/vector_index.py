"""
Vector Index for Memory

Bridges the Tier 1/2 memory system with the RAG vector store.
Stores embeddings alongside memory artifacts (patterns, edge cases)
so that semantic search can operate on memory contents.

Design:
- Each memory artifact (pattern, edge_case, module) is serialised to text,
  embedded, and stored in a VectorStore instance.
- On load from Tier 2, the index is rebuilt from stored embeddings if present,
  or re-embedded if the stored embeddings are stale/missing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .tier1 import MemoryTier1, SearchResultRef
from ..rag.vector_store import VectorStore
from ..rag.embeddings import EmbeddingManager

logger = logging.getLogger(__name__)

_EMBED_VERSION = "v1"          # Bump to force re-embedding on schema change
_INDEX_FILENAME = "VECTOR_INDEX.json"


def _artifact_to_text(artifact_id: str, artifact: Dict[str, Any]) -> str:
    """Convert a memory artifact dict to searchable text."""
    parts: List[str] = []
    if name := artifact.get("name"):
        parts.append(f"Pattern: {name}")
    if desc := artifact.get("description"):
        parts.append(desc)
    for ev in artifact.get("evidence", []):
        if isinstance(ev, str):
            parts.append(ev)
        elif isinstance(ev, dict):
            if snippet := ev.get("code_snippet"):
                parts.append(snippet)
    if handling := artifact.get("handling"):
        parts.append(f"Handling: {handling}")
    return " | ".join(parts) or artifact_id


class VectorIndex:
    """
    Semantic search index for Tier-1 memory artifacts.

    Wraps a VectorStore and an EmbeddingManager to provide:
    - embed_memory()  – index all artifacts in a MemoryTier1
    - search()        – semantic nearest-neighbour search
    - save() / load() – persist index to/from disk
    """

    def __init__(
        self,
        embedder: Optional[EmbeddingManager] = None,
        store: Optional[VectorStore] = None,
    ) -> None:
        self.embedder = embedder or EmbeddingManager()
        self.store = store or VectorStore()
        self._text_map: Dict[str, str] = {}  # id → text (for retrieval)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def embed_memory(self, memory: MemoryTier1) -> int:
        """
        Embed all patterns and edge cases in a MemoryTier1 instance.

        Returns:
            Number of artifacts indexed.
        """
        artifacts: List[Tuple[str, Dict[str, Any]]] = []
        for pid, pattern in memory.patterns.items():
            artifacts.append((f"pattern:{pid}", pattern))
        for eid, ec in memory.edge_cases.items():
            artifacts.append((f"edge_case:{eid}", ec))

        if not artifacts:
            logger.debug("No artifacts to embed")
            return 0

        ids = [a[0] for a in artifacts]
        texts = [_artifact_to_text(a[0], a[1]) for a in artifacts]

        # Ensure embedder is ready
        if not self.embedder.is_ready:
            await self.embedder.fit_fallback(texts)

        vectors = await self.embedder.embed_texts(texts)

        for cid, text, vec in zip(ids, texts, vectors):
            self.store.add(cid, vec)
            self._text_map[cid] = text

        logger.info("VectorIndex: embedded %d memory artifacts", len(artifacts))
        return len(artifacts)

    async def add_artifact(
        self,
        artifact_id: str,
        artifact: Dict[str, Any],
        artifact_type: str = "pattern",
    ) -> None:
        """Incrementally add/update a single artifact."""
        full_id = f"{artifact_type}:{artifact_id}"
        text = _artifact_to_text(artifact_id, artifact)

        if not self.embedder.is_ready:
            await self.embedder.fit_fallback([text])

        vec = await self.embedder.embed_single(text)
        self.store.add(full_id, vec)
        self._text_map[full_id] = text

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[SearchResultRef]:
        """
        Semantic search over indexed artifacts.

        Args:
            query: Natural language query.
            top_k: Max results.
            min_score: Minimum cosine similarity.

        Returns:
            List of SearchResultRef ordered by descending similarity.
        """
        if self.store.size == 0:
            return []

        if not self.embedder.is_ready:
            logger.warning("VectorIndex: embedder not ready, skipping semantic search")
            return []

        query_vec = await self.embedder.embed_single(query)
        raw = self.store.search(query_vec, top_k=top_k, min_score=min_score)

        results: List[SearchResultRef] = []
        for chunk_id, score, _meta in raw:
            # Parse "type:id" format
            if ":" in chunk_id:
                artifact_type, artifact_id = chunk_id.split(":", 1)
            else:
                artifact_type, artifact_id = "unknown", chunk_id

            results.append(SearchResultRef(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                confidence=score,
                relevance=score,
                source_file="",
            ))

        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save(self, directory: str) -> None:
        """Save vector index to a JSON file in directory."""
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, _INDEX_FILENAME)
        data = {
            "version": _EMBED_VERSION,
            "model": self.embedder.model_name,
            "text_map": self._text_map,
            "store": self.store.to_dict(),
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_json, path, data)
        logger.info("VectorIndex saved to %s", path)

    async def load(self, directory: str) -> bool:
        """
        Load vector index from directory.

        Returns True if loaded successfully, False if not found/incompatible.
        """
        path = os.path.join(directory, _INDEX_FILENAME)
        if not os.path.exists(path):
            return False

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, _read_json, path)
        except Exception as exc:
            logger.error("Failed to read vector index: %s", exc)
            return False

        if data.get("version") != _EMBED_VERSION:
            logger.warning("Vector index version mismatch; will re-embed")
            return False

        self._text_map = data.get("text_map", {})
        self.store = VectorStore.from_dict(data.get("store", {}))
        logger.info("VectorIndex loaded from %s (%d vectors)", path, self.store.size)
        return True

    @property
    def size(self) -> int:
        return self.store.size


# ---------------------------------------------------------------------------
# I/O helpers (run in executor)
# ---------------------------------------------------------------------------

def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, default=str)


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


__all__ = ["VectorIndex"]
