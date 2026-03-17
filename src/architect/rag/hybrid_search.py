"""
Hybrid Search

Combines BM25 (lexical relevance) and vector similarity (semantic relevance)
with linear interpolation, plus optional cross-encoder style reranking.

Score formula:
    final = alpha * bm25_norm + (1 - alpha) * vector_score

where:
- bm25_norm = BM25 score normalised to [0, 1] via softmax-like scaling
- vector_score = cosine similarity in [0, 1] (shifted from [-1,1])
- alpha = configurable weight (default 0.4 for BM25, 0.6 for vector)

Results are sorted by final score descending.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


@dataclass
class SearchDoc:
    """A document registered in the search index."""
    chunk_id: str
    text: str
    source_file: str
    section_header: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class HybridResult:
    """A ranked result from hybrid search."""
    chunk_id: str
    text: str
    source_file: str
    section_header: Optional[str]
    bm25_score: float
    vector_score: float
    final_score: float
    metadata: dict = field(default_factory=dict)


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + lowercase tokeniser for BM25."""
    return text.lower().split()


def _normalize_bm25(scores: np.ndarray) -> np.ndarray:
    """Normalise BM25 scores to [0, 1] using min-max with epsilon guard."""
    min_s = scores.min()
    max_s = scores.max()
    if max_s - min_s < 1e-9:
        return np.zeros_like(scores)
    return (scores - min_s) / (max_s - min_s)


def _vector_to_01(score: float) -> float:
    """Map cosine similarity from [-1, 1] to [0, 1]."""
    return (score + 1.0) / 2.0


class HybridSearch:
    """
    BM25 + Vector similarity hybrid search engine.

    Workflow:
    1. add_documents() – register chunks in BM25 and provide their embeddings.
    2. search() – query with text (BM25) + vector (cosine) → merged + ranked.

    Args:
        alpha: Weight of BM25 in final score (default 0.4).
               Vector weight = 1 - alpha.
        top_k_multiplier: Retrieve this many candidates before reranking.
    """

    def __init__(
        self,
        alpha: float = 0.4,
        top_k_multiplier: int = 3,
    ) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        self.alpha = alpha
        self.top_k_multiplier = top_k_multiplier

        self._docs: List[SearchDoc] = []
        self._doc_idx: Dict[str, int] = {}          # chunk_id → list index
        self._tokenized: List[List[str]] = []
        self._bm25: Optional[BM25Okapi] = None
        self._embeddings: Optional[np.ndarray] = None  # (N, D)
        self._dirty = False                            # needs _rebuild()

    # ------------------------------------------------------------------
    # Indexing API
    # ------------------------------------------------------------------

    def add_document(
        self,
        chunk_id: str,
        text: str,
        embedding: np.ndarray,
        source_file: str = "",
        section_header: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Add a single document to the index.

        Args:
            chunk_id: Unique identifier.
            text: Raw text content (used for BM25).
            embedding: Pre-computed float32 vector.
            source_file: Source document path.
            section_header: Nearest parent Markdown header.
            metadata: Arbitrary key-value metadata.
        """
        if chunk_id in self._doc_idx:
            # Update existing
            idx = self._doc_idx[chunk_id]
            self._docs[idx] = SearchDoc(
                chunk_id=chunk_id, text=text, source_file=source_file,
                section_header=section_header, metadata=metadata or {}
            )
            self._tokenized[idx] = _tokenize(text)
            if self._embeddings is not None:
                emb = np.asarray(embedding, dtype=np.float32)
                self._embeddings[idx] = emb / (np.linalg.norm(emb) + 1e-10)
        else:
            idx = len(self._docs)
            self._doc_idx[chunk_id] = idx
            self._docs.append(SearchDoc(
                chunk_id=chunk_id, text=text, source_file=source_file,
                section_header=section_header, metadata=metadata or {}
            ))
            self._tokenized.append(_tokenize(text))
            emb = np.asarray(embedding, dtype=np.float32)
            emb_norm = emb / (np.linalg.norm(emb) + 1e-10)
            if self._embeddings is None:
                self._embeddings = emb_norm.reshape(1, -1)
            else:
                self._embeddings = np.vstack([self._embeddings, emb_norm])

        self._dirty = True

    def add_documents_batch(
        self,
        chunk_ids: List[str],
        texts: List[str],
        embeddings: np.ndarray,
        source_files: Optional[List[str]] = None,
        section_headers: Optional[List[Optional[str]]] = None,
        metadata_list: Optional[List[dict]] = None,
    ) -> None:
        """Add multiple documents at once."""
        n = len(chunk_ids)
        if len(texts) != n or len(embeddings) != n:
            raise ValueError("chunk_ids, texts, and embeddings must have equal length")

        for i in range(n):
            self.add_document(
                chunk_id=chunk_ids[i],
                text=texts[i],
                embedding=embeddings[i],
                source_file=source_files[i] if source_files else "",
                section_header=section_headers[i] if section_headers else None,
                metadata=metadata_list[i] if metadata_list else None,
            )

    def remove_document(self, chunk_id: str) -> bool:
        """Remove a document from the index. Returns True if found."""
        if chunk_id not in self._doc_idx:
            return False
        # Tombstone approach: zero out and mark empty
        idx = self._doc_idx.pop(chunk_id)
        self._docs[idx] = SearchDoc(chunk_id="", text="", source_file="")
        self._tokenized[idx] = []
        if self._embeddings is not None:
            self._embeddings[idx] = 0.0
        self._dirty = True
        return True

    def rebuild_index(self) -> None:
        """Rebuild BM25 index from current documents."""
        live_tokens = [t for t in self._tokenized if t]
        if not live_tokens:
            self._bm25 = None
            self._dirty = False
            return
        self._bm25 = BM25Okapi(self._tokenized)  # includes empty lists harmlessly
        self._dirty = False
        logger.debug("Rebuilt BM25 index on %d documents", len(live_tokens))

    # ------------------------------------------------------------------
    # Search API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[HybridResult]:
        """
        Run hybrid search.

        Args:
            query: Text query for BM25.
            query_embedding: Pre-computed query vector (same dims as index).
            top_k: Number of results to return.
            min_score: Minimum final score to include.

        Returns:
            Ranked list of HybridResult objects.
        """
        if not self._docs:
            return []

        if self._dirty:
            self.rebuild_index()

        candidates_k = min(top_k * self.top_k_multiplier, len(self._docs))

        bm25_scores = self._bm25_scores(query, candidates_k)
        vector_scores = self._vector_scores(query_embedding)

        # Combine scores
        results: List[HybridResult] = []
        for idx, doc in enumerate(self._docs):
            if not doc.chunk_id:  # tombstoned
                continue
            bs = float(bm25_scores[idx])
            vs = _vector_to_01(float(vector_scores[idx]))
            final = self.alpha * bs + (1.0 - self.alpha) * vs

            if final >= min_score:
                results.append(HybridResult(
                    chunk_id=doc.chunk_id,
                    text=doc.text,
                    source_file=doc.source_file,
                    section_header=doc.section_header,
                    bm25_score=bs,
                    vector_score=vs,
                    final_score=final,
                    metadata=doc.metadata,
                ))

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:top_k]

    def bm25_only(self, query: str, top_k: int = 5) -> List[HybridResult]:
        """Lexical-only BM25 search."""
        if self._dirty:
            self.rebuild_index()
        if not self._bm25:
            return []

        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)
        norm = _normalize_bm25(scores)

        indexed = sorted(enumerate(norm), key=lambda x: x[1], reverse=True)
        results: List[HybridResult] = []
        for idx, score in indexed[:top_k]:
            doc = self._docs[idx]
            if not doc.chunk_id:
                continue
            results.append(HybridResult(
                chunk_id=doc.chunk_id,
                text=doc.text,
                source_file=doc.source_file,
                section_header=doc.section_header,
                bm25_score=float(score),
                vector_score=0.0,
                final_score=float(score),
                metadata=doc.metadata,
            ))
        return results

    @property
    def document_count(self) -> int:
        return sum(1 for d in self._docs if d.chunk_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _bm25_scores(self, query: str, _top_k: int) -> np.ndarray:
        """Return normalised BM25 scores for all documents."""
        if self._bm25 is None:
            return np.zeros(len(self._docs))
        tokens = _tokenize(query)
        raw = self._bm25.get_scores(tokens)
        return _normalize_bm25(raw)

    def _vector_scores(self, query_embedding: np.ndarray) -> np.ndarray:
        """Return cosine similarities for all documents."""
        if self._embeddings is None or len(self._docs) == 0:
            return np.zeros(len(self._docs))
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-10)
        return self._embeddings @ q_norm


__all__ = ["HybridSearch", "HybridResult", "SearchDoc"]
