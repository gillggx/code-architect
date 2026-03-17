"""
Architect Agent - Multi-Language Code Analysis with Persistent Memory

Core modules:
- parsers: Multi-language code analysis (8 languages)
- memory: 3-tier memory system (Tier 1: in-memory, Tier 2: persistent MD, Tier 3: archives)
- patterns: Pattern detection engine (15+ patterns across 8 languages)
- rag: RAG search system (BM25 + vector + reranking)
- qa: Q&A engine (memory search + response generation)
- models: Pydantic V2 data models
"""

__version__ = "0.2.0"
__author__ = "Code Architect Agent"

from .parsers.registry import ParserRegistry
from .memory.tier1 import MemoryTier1
from .memory.persistence import MemoryPersistenceManager
from .memory.vector_index import VectorIndex
from .memory.rag_integration import RAGMemoryIntegration
from .memory.incremental_analysis import ChangeDetector
from .patterns.detector import PatternDetector
from .patterns.catalog import get_pattern_catalog
from .rag.chunker import MarkdownChunker
from .rag.embeddings import EmbeddingManager
from .rag.vector_store import VectorStore
from .rag.hybrid_search import HybridSearch
from .rag.retriever import Retriever
from .qa.engine import QAEngine

__all__ = [
    # Phase 1
    "ParserRegistry",
    "MemoryTier1",
    "MemoryPersistenceManager",
    "QAEngine",
    # Phase 2 - Memory extensions
    "VectorIndex",
    "RAGMemoryIntegration",
    "ChangeDetector",
    # Phase 2 - Pattern detection
    "PatternDetector",
    "get_pattern_catalog",
    # Phase 2 - RAG
    "MarkdownChunker",
    "EmbeddingManager",
    "VectorStore",
    "HybridSearch",
    "Retriever",
]
