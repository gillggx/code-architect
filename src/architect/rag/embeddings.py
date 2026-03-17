"""
Embedding Manager

Generates vector embeddings for text chunks using:
1. OpenAI text-embedding-3-small (primary, requires OPENAI_API_KEY)
2. TF-IDF + TruncatedSVD (fallback, pure sklearn, 256-dim dense vectors)

The fallback produces deterministic embeddings once the vocabulary is fitted.
The manager is async-first and batches OpenAI calls for efficiency.
"""

from __future__ import annotations

import os
import asyncio
import logging
import hashlib
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_OPENAI_MODEL = "text-embedding-3-small"
_OPENAI_DIMS = 1536
_FALLBACK_DIMS = 256          # SVD output dimensions
_BATCH_SIZE = 96              # Max texts per OpenAI batch
_CACHE_MAX = 10_000           # In-memory embedding cache size


class EmbeddingCache:
    """Simple LRU-style in-memory cache keyed by content hash."""

    def __init__(self, max_size: int = _CACHE_MAX) -> None:
        self._data: Dict[str, np.ndarray] = {}
        self._max = max_size

    def get(self, text: str) -> Optional[np.ndarray]:
        key = self._hash(text)
        return self._data.get(key)

    def put(self, text: str, vector: np.ndarray) -> None:
        if len(self._data) >= self._max:
            # Evict oldest (first inserted) entry
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._data[self._hash(text)] = vector

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def __len__(self) -> int:
        return len(self._data)


class TFIDFEmbedder:
    """
    Fallback embedder using TF-IDF + Truncated SVD (LSA).

    Must call fit() with a corpus before embed() can be used.
    Thread-safe for reads once fitted.
    """

    def __init__(self, n_components: int = _FALLBACK_DIMS) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        from sklearn.preprocessing import Normalizer
        from sklearn.pipeline import Pipeline

        self.n_components = n_components
        self._pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                max_features=20_000,
                sublinear_tf=True,
                ngram_range=(1, 2),
                min_df=1,
            )),
            ("svd", TruncatedSVD(n_components=n_components, random_state=42)),
            ("norm", Normalizer(copy=False)),
        ])
        self._fitted = False

    def fit(self, corpus: List[str]) -> None:
        """Fit the TF-IDF + SVD pipeline on a text corpus."""
        if not corpus:
            raise ValueError("Cannot fit on empty corpus")
        # Clamp n_components to vocab size
        n = min(self.n_components, len(corpus) - 1, 20_000)
        self._pipeline.named_steps["svd"].n_components = max(1, n)
        self._pipeline.fit(corpus)
        self._fitted = True
        logger.info("TFIDFEmbedder fitted on %d documents", len(corpus))

    def embed(self, text: str) -> np.ndarray:
        """Return a normalised dense vector for a single text."""
        if not self._fitted:
            raise RuntimeError("Call fit() before embed()")
        vec = self._pipeline.transform([text])
        return vec[0].astype(np.float32)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Return a (N, dims) array of embeddings."""
        if not self._fitted:
            raise RuntimeError("Call fit() before embed_batch()")
        return self._pipeline.transform(texts).astype(np.float32)

    @property
    def dimensions(self) -> int:
        return self._pipeline.named_steps["svd"].n_components

    @property
    def is_fitted(self) -> bool:
        return self._fitted


class EmbeddingManager:
    """
    Unified async embedding manager.

    Tries OpenAI first; falls back to TF-IDF + SVD if:
    - OPENAI_API_KEY is not set, or
    - OpenAI call fails.

    Usage::

        manager = EmbeddingManager()
        vectors = await manager.embed_texts(["hello world", "foo bar"])

    Args:
        use_openai: Force OpenAI (raises if key missing). Default: auto-detect.
        openai_model: OpenAI model name. Default: text-embedding-3-small.
        fallback_dims: Dimensions for TF-IDF fallback. Default: 256.
    """

    def __init__(
        self,
        use_openai: Optional[bool] = None,
        openai_model: str = _OPENAI_MODEL,
        fallback_dims: int = _FALLBACK_DIMS,
    ) -> None:
        self._openai_model = openai_model
        self._cache = EmbeddingCache()
        self._tfidf = TFIDFEmbedder(n_components=fallback_dims)
        self._lock = asyncio.Lock()

        # Determine backend
        has_key = bool(os.getenv("OPENAI_API_KEY"))
        if use_openai is True and not has_key:
            raise EnvironmentError("use_openai=True but OPENAI_API_KEY not set")
        self._use_openai: bool = has_key if use_openai is None else use_openai

        if self._use_openai:
            try:
                from openai import AsyncOpenAI  # noqa: F401
                logger.info("EmbeddingManager: using OpenAI %s", openai_model)
            except ImportError:
                logger.warning("openai package missing; falling back to TF-IDF")
                self._use_openai = False
        else:
            logger.info("EmbeddingManager: using TF-IDF fallback (%d dims)", fallback_dims)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Embed a list of texts.

        Returns:
            np.ndarray of shape (N, dimensions), dtype float32.
        """
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)

        if self._use_openai:
            return await self._embed_openai(texts)
        return await self._embed_tfidf(texts)

    async def embed_single(self, text: str) -> np.ndarray:
        """Embed a single text string."""
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        result = await self.embed_texts([text])
        vec = result[0]
        self._cache.put(text, vec)
        return vec

    async def fit_fallback(self, corpus: List[str]) -> None:
        """
        Fit the TF-IDF fallback on a corpus.

        Must be called before embed_texts() if use_openai=False.
        """
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._tfidf.fit, corpus)

    @property
    def dimensions(self) -> int:
        """Embedding vector dimensionality."""
        if self._use_openai:
            return _OPENAI_DIMS
        return self._tfidf.dimensions if self._tfidf.is_fitted else _FALLBACK_DIMS

    @property
    def model_name(self) -> str:
        if self._use_openai:
            return self._openai_model
        return "tfidf-svd"

    @property
    def is_ready(self) -> bool:
        """True if the embedder can produce embeddings without fitting."""
        return self._use_openai or self._tfidf.is_fitted

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    async def _embed_openai(self, texts: List[str]) -> np.ndarray:
        """Batch-embed using OpenAI API."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        all_vectors: List[np.ndarray] = []

        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            try:
                response = await client.embeddings.create(
                    input=batch,
                    model=self._openai_model,
                )
                for item in response.data:
                    all_vectors.append(np.array(item.embedding, dtype=np.float32))
            except Exception as exc:
                logger.warning("OpenAI embedding failed (%s); falling back for this batch", exc)
                # Fallback: use TF-IDF for this batch
                if not self._tfidf.is_fitted:
                    self._tfidf.fit(batch)
                vecs = self._tfidf.embed_batch(batch)
                # Pad/truncate to OpenAI dims
                padded = np.zeros((len(batch), _OPENAI_DIMS), dtype=np.float32)
                padded[:, : vecs.shape[1]] = vecs
                all_vectors.extend(padded)

        return np.stack(all_vectors) if all_vectors else np.empty((0, _OPENAI_DIMS), dtype=np.float32)

    async def _embed_tfidf(self, texts: List[str]) -> np.ndarray:
        """Embed using TF-IDF + SVD (runs in thread pool to avoid blocking)."""
        if not self._tfidf.is_fitted:
            async with self._lock:
                if not self._tfidf.is_fitted:
                    logger.info("Auto-fitting TF-IDF on %d texts", len(texts))
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._tfidf.fit, texts)

        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(None, self._tfidf.embed_batch, texts)
        return vecs


__all__ = ["EmbeddingManager", "EmbeddingCache", "TFIDFEmbedder"]
