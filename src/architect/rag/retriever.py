"""
Retriever

High-level async API that orchestrates:
1. MarkdownChunker → split documents into chunks
2. EmbeddingManager → embed chunks
3. HybridSearch → BM25 + vector search
4. Result formatting → SearchResult Pydantic models

Supports:
- Index a list of Markdown files
- Index raw text (e.g., memory tier-2 files)
- Semantic + lexical query
- Fast re-indexing on file changes
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Chunk, SearchResult
from .chunker import MarkdownChunker, RawChunk, chunk_id_for
from .embeddings import EmbeddingManager
from .hybrid_search import HybridSearch, HybridResult

logger = logging.getLogger(__name__)


class Retriever:
    """
    High-level retrieval engine combining chunking, embedding, and hybrid search.

    Args:
        chunker: MarkdownChunker instance (created with defaults if omitted).
        embedder: EmbeddingManager instance (auto-detects OpenAI/TF-IDF).
        alpha: BM25 weight in hybrid score (default 0.4).
        max_results: Default maximum results (overridden per-query).
    """

    def __init__(
        self,
        chunker: Optional[MarkdownChunker] = None,
        embedder: Optional[EmbeddingManager] = None,
        alpha: float = 0.4,
        max_results: int = 5,
    ) -> None:
        self.chunker = chunker or MarkdownChunker()
        self.embedder = embedder or EmbeddingManager()
        self.search_engine = HybridSearch(alpha=alpha)
        self.max_results = max_results

        # chunk_id → full text (for result assembly)
        self._chunk_texts: Dict[str, str] = {}
        self._chunk_sources: Dict[str, str] = {}
        self._chunk_headers: Dict[str, Optional[str]] = {}
        self._indexed_files: set[str] = set()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_files(self, file_paths: List[str]) -> int:
        """
        Chunk and index a list of Markdown (or plain text) files.

        Args:
            file_paths: List of absolute paths.

        Returns:
            Total number of chunks indexed.
        """
        all_chunks: List[RawChunk] = []
        for path in file_paths:
            chunks = self.chunker.chunk_file(path)
            all_chunks.extend(chunks)
            self._indexed_files.add(path)

        return await self._index_chunks(all_chunks)

    async def index_text(
        self,
        text: str,
        source: str = "memory",
        extra_metadata: Optional[dict] = None,
    ) -> int:
        """
        Chunk and index a raw text string.

        Args:
            text: Markdown or plain text content.
            source: Logical source identifier (stored in metadata).
            extra_metadata: Extra metadata attached to all chunks.

        Returns:
            Number of chunks indexed.
        """
        chunks = self.chunker.chunk_text(text, source_file=source, extra_metadata=extra_metadata)
        return await self._index_chunks(chunks)

    async def reindex_file(self, file_path: str) -> int:
        """Remove existing chunks for a file and re-index from scratch."""
        # Remove old chunks for this file
        to_remove = [
            cid for cid, src in self._chunk_sources.items()
            if src == file_path
        ]
        for cid in to_remove:
            self.search_engine.remove_document(cid)
            self._chunk_texts.pop(cid, None)
            self._chunk_sources.pop(cid, None)
            self._chunk_headers.pop(cid, None)

        chunks = self.chunker.chunk_file(file_path)
        indexed = await self._index_chunks(chunks)
        self._indexed_files.add(file_path)
        return indexed

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def query(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        min_score: float = 0.0,
        source_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Run a hybrid search query.

        Args:
            query_text: User query string.
            top_k: Max results (defaults to self.max_results).
            min_score: Minimum final score threshold.
            source_filter: If set, only return results from this source file.

        Returns:
            List of SearchResult Pydantic models sorted by score descending.
        """
        if self.search_engine.document_count == 0:
            logger.warning("Retriever index is empty; no results")
            return []

        k = top_k or self.max_results
        t0 = time.perf_counter()

        # Embed query
        query_vec = await self.embedder.embed_single(query_text)

        # Run hybrid search
        raw_results = self.search_engine.search(
            query=query_text,
            query_embedding=query_vec,
            top_k=k * 2 if source_filter else k,  # fetch more if filtering
            min_score=min_score,
        )

        # Filter by source if requested
        if source_filter:
            raw_results = [r for r in raw_results if r.source_file == source_filter]

        # Convert to Pydantic SearchResult
        results = [self._to_search_result(r) for r in raw_results[:k]]

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "Query '%s' → %d results in %.1f ms",
            query_text[:50], len(results), elapsed_ms,
        )
        return results

    async def query_bm25(self, query_text: str, top_k: Optional[int] = None) -> List[SearchResult]:
        """Lexical-only BM25 search (no embedding computation)."""
        k = top_k or self.max_results
        raw = self.search_engine.bm25_only(query_text, top_k=k)
        return [self._to_search_result(r) for r in raw]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def indexed_count(self) -> int:
        """Total number of indexed chunks."""
        return self.search_engine.document_count

    @property
    def indexed_files(self) -> set:
        return self._indexed_files

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _index_chunks(self, chunks: List[RawChunk]) -> int:
        """Embed and add chunks to the search engine."""
        if not chunks:
            return 0

        # Ensure fallback embedder is fitted if needed
        if not self.embedder.is_ready:
            corpus = [c.content for c in chunks]
            await self.embedder.fit_fallback(corpus)

        # Embed all chunks
        texts = [c.content for c in chunks]
        embeddings = await self.embedder.embed_texts(texts)

        # Register in search engine and text stores
        chunk_ids = [chunk_id_for(c) for c in chunks]

        self.search_engine.add_documents_batch(
            chunk_ids=chunk_ids,
            texts=texts,
            embeddings=embeddings,
            source_files=[c.source_file for c in chunks],
            section_headers=[c.section_header for c in chunks],
            metadata_list=[c.metadata for c in chunks],
        )

        for cid, chunk in zip(chunk_ids, chunks):
            self._chunk_texts[cid] = chunk.content
            self._chunk_sources[cid] = chunk.source_file
            self._chunk_headers[cid] = chunk.section_header

        self.search_engine.rebuild_index()
        logger.info("Indexed %d chunks", len(chunks))
        return len(chunks)

    @staticmethod
    def _to_search_result(r: HybridResult) -> SearchResult:
        """Convert a HybridResult to a Pydantic SearchResult."""
        return SearchResult(
            chunk=Chunk(
                id=r.chunk_id,
                text=r.text,
                metadata={"source_file": r.source_file, "header": r.section_header or ""},
                tokens=max(1, len(r.text) // 4),
            ),
            relevance_score=min(1.0, r.final_score),
            source_confidence=min(1.0, r.vector_score),
            search_method="hybrid",
            explanation=f"BM25={r.bm25_score:.3f} Vector={r.vector_score:.3f}",
        )


__all__ = ["Retriever"]
