"""
Vector Store

In-memory vector store backed by numpy.
Supports cosine similarity search with O(N) brute-force or batched retrieval.

For production at scale, swap the backend to FAISS or Annoy;
the VectorStore interface remains the same.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between a query vector and a matrix of vectors.

    Args:
        query: Shape (D,) - single query vector (will be L2-normalised).
        matrix: Shape (N, D) - stored vectors (assumed pre-normalised).

    Returns:
        Shape (N,) similarity scores in [-1, 1].
    """
    q_norm = query / (np.linalg.norm(query) + 1e-10)
    return matrix @ q_norm  # dot product of normalised vectors = cosine


class VectorStore:
    """
    Numpy-backed in-memory vector store.

    Stores chunk IDs → normalised embedding vectors.
    Supports add, remove, and top-k cosine similarity search.

    Args:
        dimensions: Embedding dimensionality (auto-detected on first add).
    """

    def __init__(self, dimensions: Optional[int] = None) -> None:
        self._dimensions = dimensions
        self._ids: List[str] = []
        self._matrix: Optional[np.ndarray] = None  # (N, D)
        self._id_to_idx: Dict[str, int] = {}
        self._metadata: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        chunk_id: str,
        vector: np.ndarray,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Add or update a vector in the store.

        Args:
            chunk_id: Unique identifier for this vector.
            vector: 1-D float32 array.
            metadata: Optional key-value metadata.
        """
        vector = self._ensure_float32(vector)

        if self._dimensions is None:
            self._dimensions = len(vector)
        elif len(vector) != self._dimensions:
            raise ValueError(
                f"Vector dimension {len(vector)} != store dimension {self._dimensions}"
            )

        # L2-normalise for cosine similarity
        norm = np.linalg.norm(vector)
        normalised = vector / (norm + 1e-10)

        if chunk_id in self._id_to_idx:
            idx = self._id_to_idx[chunk_id]
            self._matrix[idx] = normalised
        else:
            idx = len(self._ids)
            self._id_to_idx[chunk_id] = idx
            self._ids.append(chunk_id)

            if self._matrix is None:
                self._matrix = normalised.reshape(1, -1)
            else:
                self._matrix = np.vstack([self._matrix, normalised])

        if metadata:
            self._metadata[chunk_id] = metadata

    def add_batch(
        self,
        chunk_ids: List[str],
        vectors: np.ndarray,
        metadata: Optional[List[dict]] = None,
    ) -> None:
        """
        Add multiple vectors at once.

        Args:
            chunk_ids: List of N unique IDs.
            vectors: Array of shape (N, D).
            metadata: Optional list of N metadata dicts.
        """
        if len(chunk_ids) != len(vectors):
            raise ValueError("chunk_ids and vectors must have the same length")

        for i, (cid, vec) in enumerate(zip(chunk_ids, vectors)):
            meta = metadata[i] if metadata else None
            self.add(cid, vec, meta)

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Tuple[str, float, dict]]:
        """
        Find top-k most similar vectors to the query.

        Args:
            query_vector: Query vector (D,).
            top_k: Number of results to return.
            min_score: Minimum cosine similarity threshold.

        Returns:
            List of (chunk_id, score, metadata) sorted by score descending.
        """
        if self._matrix is None or len(self._ids) == 0:
            return []

        query_vector = self._ensure_float32(query_vector)
        scores = _cosine_similarity(query_vector, self._matrix)

        # Get top-k indices
        k = min(top_k, len(scores))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]

        results: List[Tuple[str, float, dict]] = []
        for idx in top_idx:
            score = float(scores[idx])
            if score < min_score:
                continue
            cid = self._ids[idx]
            meta = self._metadata.get(cid, {})
            results.append((cid, score, meta))

        return results

    def remove(self, chunk_id: str) -> bool:
        """
        Remove a vector from the store.

        Marks the slot as empty (zero vector); does not compact the matrix.
        Returns True if the ID was found and removed.
        """
        if chunk_id not in self._id_to_idx:
            return False
        idx = self._id_to_idx.pop(chunk_id)
        self._ids[idx] = ""  # tombstone
        if self._matrix is not None:
            self._matrix[idx] = 0.0
        self._metadata.pop(chunk_id, None)
        return True

    def contains(self, chunk_id: str) -> bool:
        return chunk_id in self._id_to_idx

    def get_vector(self, chunk_id: str) -> Optional[np.ndarray]:
        """Retrieve the stored vector for a chunk ID."""
        idx = self._id_to_idx.get(chunk_id)
        if idx is None or self._matrix is None:
            return None
        return self._matrix[idx].copy()

    def clear(self) -> None:
        """Remove all vectors from the store."""
        self._ids = []
        self._matrix = None
        self._id_to_idx = {}
        self._metadata = {}

    def compact(self) -> None:
        """Remove tombstoned entries and rebuild the matrix."""
        live_ids = [cid for cid in self._ids if cid]
        if len(live_ids) == len(self._ids):
            return  # Nothing to compact

        live_idx = [i for i, cid in enumerate(self._ids) if cid]
        self._ids = live_ids
        self._matrix = self._matrix[live_idx] if self._matrix is not None else None
        self._id_to_idx = {cid: i for i, cid in enumerate(live_ids)}

    @property
    def size(self) -> int:
        """Number of non-tombstoned vectors in the store."""
        return sum(1 for cid in self._ids if cid)

    @property
    def dimensions(self) -> Optional[int]:
        return self._dimensions

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise store state to a plain dict (for persistence)."""
        return {
            "dimensions": self._dimensions,
            "ids": self._ids,
            "matrix": self._matrix.tolist() if self._matrix is not None else [],
            "metadata": self._metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorStore":
        """Restore store from a serialised dict."""
        store = cls(dimensions=data.get("dimensions"))
        ids = data.get("ids", [])
        matrix_data = data.get("matrix", [])
        metadata = data.get("metadata", {})

        if ids and matrix_data:
            matrix = np.array(matrix_data, dtype=np.float32)
            for i, cid in enumerate(ids):
                if cid:
                    store._id_to_idx[cid] = i
                    store._metadata[cid] = metadata.get(cid, {})
            store._ids = ids
            store._matrix = matrix
            store._dimensions = matrix.shape[1] if matrix.ndim == 2 else data.get("dimensions")

        return store

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_float32(v: np.ndarray) -> np.ndarray:
        arr = np.asarray(v, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError(f"Expected 1-D vector, got shape {arr.shape}")
        return arr


__all__ = ["VectorStore"]
