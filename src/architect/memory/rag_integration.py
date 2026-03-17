"""
RAG ↔ Memory Integration

Connects the Tier 1/2 memory system to the RAG retrieval engine.

Responsibilities:
1. On project analysis completion, index all Tier-2 Markdown files into RAG.
2. Augment QA responses with RAG context from memory files.
3. Keep the RAG index consistent with memory: re-index on write.
4. Provide a unified search interface (memory keyword + RAG semantic).

Usage::

    integration = RAGMemoryIntegration(retriever, vector_index, memory_root)
    await integration.index_project_memory("my-project")
    results = await integration.unified_search("singleton pattern", top_k=5)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tier1 import MemoryTier1, SearchResultRef
from .vector_index import VectorIndex
from ..rag.retriever import Retriever
from ..models import SearchResult

logger = logging.getLogger(__name__)

# Tier-2 Markdown files that should be indexed
_MEMORY_FILES = [
    "PROJECT.md",
    "PATTERNS.md",
    "EDGE_CASES.md",
    "INDEX.md",
]


class RAGMemoryIntegration:
    """
    Bridges RAG retrieval and the 3-tier memory system.

    Args:
        retriever: RAG Retriever instance.
        vector_index: VectorIndex for semantic artifact search.
        memory_root: Root directory of Tier-2 persistent storage.
    """

    def __init__(
        self,
        retriever: Retriever,
        vector_index: VectorIndex,
        memory_root: str = "/architect_memory",
    ) -> None:
        self.retriever = retriever
        self.vector_index = vector_index
        self.memory_root = memory_root

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_project_memory(self, project_id: str) -> int:
        """
        Index all Tier-2 Markdown files for a project into RAG.

        Args:
            project_id: The project directory name under memory_root.

        Returns:
            Total number of chunks indexed.
        """
        memory_dir = os.path.join(self.memory_root, project_id)
        if not os.path.isdir(memory_dir):
            logger.warning("Memory directory not found: %s", memory_dir)
            return 0

        files_to_index = []
        for fname in _MEMORY_FILES:
            fpath = os.path.join(memory_dir, fname)
            if os.path.exists(fpath):
                files_to_index.append(fpath)

        # Also index per-module markdown files in modules/ subdirectory
        modules_dir = os.path.join(memory_dir, "modules")
        if os.path.isdir(modules_dir):
            for fname in os.listdir(modules_dir):
                if fname.endswith(".md"):
                    files_to_index.append(os.path.join(modules_dir, fname))

        if not files_to_index:
            logger.info("No memory files found for project %s", project_id)
            return 0

        total = await self.retriever.index_files(files_to_index)
        logger.info(
            "Indexed %d chunks from %d files for project %s",
            total, len(files_to_index), project_id,
        )
        return total

    async def index_memory_tier1(self, memory: MemoryTier1) -> int:
        """
        Embed Tier-1 memory artifacts into the VectorIndex.

        Args:
            memory: Loaded Tier-1 memory instance.

        Returns:
            Number of artifacts embedded.
        """
        return await self.vector_index.embed_memory(memory)

    async def on_memory_updated(
        self,
        memory: MemoryTier1,
        project_id: str,
        changed_files: Optional[List[str]] = None,
    ) -> None:
        """
        Hook called when memory is updated (incremental refresh).

        Re-indexes changed Tier-2 files and updates VectorIndex.

        Args:
            memory: Updated Tier-1 memory.
            project_id: Project identifier.
            changed_files: If provided, only re-index these files.
        """
        memory_dir = os.path.join(self.memory_root, project_id)

        if changed_files:
            for fpath in changed_files:
                if os.path.exists(fpath) and fpath.endswith(".md"):
                    await self.retriever.reindex_file(fpath)
                    logger.debug("Re-indexed changed file: %s", fpath)
        else:
            await self.index_project_memory(project_id)

        # Update VectorIndex with fresh artifacts
        await self.vector_index.embed_memory(memory)

        # Save updated vector index
        await self.vector_index.save(memory_dir)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[SearchResult]:
        """
        Semantic search over indexed memory documents.

        Returns:
            List of SearchResult models from RAG retriever.
        """
        return await self.retriever.query(query, top_k=top_k, min_score=min_score)

    async def artifact_search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[SearchResultRef]:
        """
        Semantic search over memory artifacts (patterns, edge cases).

        Returns:
            List of SearchResultRef with artifact IDs and types.
        """
        return await self.vector_index.search(query, top_k=top_k, min_score=min_score)

    async def unified_search(
        self,
        query: str,
        memory: MemoryTier1,
        top_k: int = 5,
        confidence_threshold: float = 0.70,
    ) -> Dict[str, Any]:
        """
        Combined keyword (Tier-1) + semantic (RAG) search.

        Args:
            query: Search query.
            memory: Tier-1 memory to keyword-search.
            top_k: Max results per search method.
            confidence_threshold: Min confidence for keyword results.

        Returns:
            Dict with keys 'keyword_results', 'semantic_results', 'artifact_results'.
        """
        # Run all three searches concurrently
        keyword_task = asyncio.ensure_future(
            asyncio.coroutine(lambda: memory.search(query, confidence_threshold))()
            if False else _run_sync(memory.search, query, confidence_threshold)
        )
        semantic_task = asyncio.ensure_future(
            self.semantic_search(query, top_k=top_k)
        )
        artifact_task = asyncio.ensure_future(
            self.artifact_search(query, top_k=top_k)
        )

        keyword_results, semantic_results, artifact_results = await asyncio.gather(
            keyword_task, semantic_task, artifact_task,
            return_exceptions=True,
        )

        return {
            "keyword_results": keyword_results if not isinstance(keyword_results, Exception) else [],
            "semantic_results": semantic_results if not isinstance(semantic_results, Exception) else [],
            "artifact_results": artifact_results if not isinstance(artifact_results, Exception) else [],
        }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def save_index(self, project_id: str) -> None:
        """Save the vector index to the project's memory directory."""
        memory_dir = os.path.join(self.memory_root, project_id)
        await self.vector_index.save(memory_dir)

    async def load_index(self, project_id: str) -> bool:
        """Load vector index from the project's memory directory."""
        memory_dir = os.path.join(self.memory_root, project_id)
        return await self.vector_index.load(memory_dir)


async def _run_sync(fn, *args):
    """Run a synchronous function as a coroutine (no thread overhead for fast ops)."""
    return fn(*args)


__all__ = ["RAGMemoryIntegration"]
