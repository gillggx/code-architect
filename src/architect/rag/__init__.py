"""
RAG (Retrieval-Augmented Generation) System

Provides semantic + lexical search over project memory:
- MarkdownChunker: header-aware chunking (max 500 tokens)
- EmbeddingManager: OpenAI / TF-IDF fallback embeddings
- VectorStore: numpy cosine-similarity store
- HybridSearch: BM25 + vector + reranking
- Retriever: high-level search API
"""

from .chunker import MarkdownChunker
from .embeddings import EmbeddingManager
from .vector_store import VectorStore
from .hybrid_search import HybridSearch
from .retriever import Retriever

__all__ = [
    "MarkdownChunker",
    "EmbeddingManager",
    "VectorStore",
    "HybridSearch",
    "Retriever",
]
