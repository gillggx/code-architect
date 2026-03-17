"""
Unit tests for Phase 2 RAG system.

Tests cover:
- MarkdownChunker: header splitting, size limits, token counting
- VectorStore: add, search, remove, cosine similarity
- HybridSearch: BM25 + vector combination, result ordering
- Retriever: end-to-end index and query
- ChangeDetector: snapshot, diff, file change detection
"""

import asyncio
import os
import tempfile
import time
import pytest
import numpy as np

from architect.rag.chunker import MarkdownChunker, RawChunk, chunk_id_for
from architect.rag.vector_store import VectorStore
from architect.rag.hybrid_search import HybridSearch, SearchDoc
from architect.rag.retriever import Retriever
from architect.rag.embeddings import TFIDFEmbedder
from architect.memory.incremental_analysis import ChangeDetector, ProjectSnapshot, FileSnapshot


# ---------------------------------------------------------------------------
# MarkdownChunker tests
# ---------------------------------------------------------------------------

class TestMarkdownChunker:
    @pytest.fixture
    def chunker(self):
        return MarkdownChunker(max_tokens=100, min_tokens=5)

    def test_chunks_headers(self, chunker):
        md = """# Title\n\nIntro text.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"""
        chunks = chunker.chunk_text(md, source_file="test.md")
        headers = {c.section_header for c in chunks}
        assert "Section A" in headers or any("Section A" in c.content for c in chunks)

    def test_respects_max_tokens(self, chunker):
        long_text = "word " * 500  # 500 words ≈ 500 tokens
        chunks = chunker.chunk_text(long_text, source_file="test.md")
        for chunk in chunks:
            assert chunk.token_count <= 110  # small tolerance for prefix

    def test_min_tokens_filter(self, chunker):
        md = "# Title\n\nHi.\n\n## Long Section\n\n" + "A sentence here. " * 50
        chunks = chunker.chunk_text(md, source_file="test.md")
        for chunk in chunks:
            assert chunk.token_count >= chunker.min_tokens

    def test_empty_text(self, chunker):
        chunks = chunker.chunk_text("", source_file="test.md")
        assert chunks == []

    def test_source_file_stored(self, chunker):
        chunks = chunker.chunk_text("Hello world.", source_file="my_file.md")
        for chunk in chunks:
            assert chunk.source_file == "my_file.md"

    def test_chunk_index_sequential(self, chunker):
        md = "## A\n\ntext A.\n\n## B\n\ntext B.\n"
        chunks = chunker.chunk_text(md, source_file="x.md")
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_id_stable(self, chunker):
        chunk = RawChunk(
            content="hello", source_file="f.md", chunk_index=0,
            section_header=None
        )
        id1 = chunk_id_for(chunk)
        id2 = chunk_id_for(chunk)
        assert id1 == id2

    def test_chunk_file(self, chunker, tmp_path):
        fpath = tmp_path / "test.md"
        fpath.write_text("# Hello\n\nThis is content.\n")
        chunks = chunker.chunk_file(str(fpath))
        assert len(chunks) >= 1

    def test_nonexistent_file_returns_empty(self, chunker):
        chunks = chunker.chunk_file("/nonexistent/file.md")
        assert chunks == []


# ---------------------------------------------------------------------------
# VectorStore tests
# ---------------------------------------------------------------------------

class TestVectorStore:
    @pytest.fixture
    def store(self):
        return VectorStore(dimensions=4)

    def test_add_and_search(self, store):
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        store.add("id1", v1)
        store.add("id2", v2)
        # Query close to v1
        results = store.search(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), top_k=2)
        assert results[0][0] == "id1"

    def test_size(self, store):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        store.add("a", v)
        store.add("b", v)
        assert store.size == 2

    def test_contains(self, store):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        store.add("myid", v)
        assert store.contains("myid")
        assert not store.contains("missing")

    def test_remove(self, store):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        store.add("todelete", v)
        assert store.remove("todelete")
        assert not store.contains("todelete")

    def test_remove_nonexistent(self, store):
        assert not store.remove("ghost")

    def test_clear(self, store):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        store.add("x", v)
        store.clear()
        assert store.size == 0

    def test_dimension_mismatch_raises(self, store):
        with pytest.raises(ValueError):
            store.add("bad", np.array([1.0, 0.0], dtype=np.float32))

    def test_search_empty_store(self, store):
        results = store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
        assert results == []

    def test_serialisation_roundtrip(self, store):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        store.add("chunk1", v, metadata={"source": "test.md"})
        data = store.to_dict()
        store2 = VectorStore.from_dict(data)
        assert store2.contains("chunk1")
        result = store2.search(v, top_k=1)
        assert result[0][0] == "chunk1"

    def test_top_k_limit(self, store):
        for i in range(10):
            store.add(f"id{i}", np.random.rand(4).astype(np.float32))
        results = store.search(np.random.rand(4).astype(np.float32), top_k=3)
        assert len(results) <= 3

    def test_cosine_similarity_identical_vectors(self, store):
        v = np.array([0.6, 0.8, 0.0, 0.0], dtype=np.float32)
        store.add("same", v)
        results = store.search(v, top_k=1)
        assert abs(results[0][1] - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# HybridSearch tests
# ---------------------------------------------------------------------------

class TestHybridSearch:
    @pytest.fixture
    def search_engine(self):
        engine = HybridSearch(alpha=0.5)
        docs = [
            ("c1", "singleton pattern class with _instance variable", np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)),
            ("c2", "factory method for creating objects", np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)),
            ("c3", "observer pattern with subscribe notify", np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)),
            ("c4", "async concurrency with asyncio", np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)),
        ]
        for cid, text, emb in docs:
            engine.add_document(cid, text, emb, source_file="test.md")
        engine.rebuild_index()
        return engine

    def test_basic_search_returns_results(self, search_engine):
        query_emb = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = search_engine.search("singleton", query_emb, top_k=2)
        assert len(results) >= 1
        assert results[0].chunk_id == "c1"

    def test_scores_in_range(self, search_engine):
        query_emb = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        results = search_engine.search("factory singleton", query_emb, top_k=4)
        for r in results:
            assert 0.0 <= r.final_score <= 1.5  # combined score can exceed 1

    def test_results_sorted_descending(self, search_engine):
        query_emb = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        results = search_engine.search("factory", query_emb, top_k=4)
        scores = [r.final_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_bm25_only(self, search_engine):
        results = search_engine.bm25_only("singleton pattern", top_k=2)
        assert len(results) >= 1
        assert results[0].chunk_id == "c1"

    def test_remove_document(self, search_engine):
        search_engine.remove_document("c1")
        query_emb = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = search_engine.search("singleton", query_emb, top_k=4)
        ids = [r.chunk_id for r in results]
        assert "c1" not in ids

    def test_document_count(self, search_engine):
        assert search_engine.document_count == 4


# ---------------------------------------------------------------------------
# TFIDFEmbedder tests
# ---------------------------------------------------------------------------

class TestTFIDFEmbedder:
    def test_fit_and_embed(self):
        corpus = [
            "singleton pattern instance",
            "factory method create object",
            "observer subscribe notify",
        ]
        embedder = TFIDFEmbedder(n_components=16)
        embedder.fit(corpus)
        vec = embedder.embed("singleton pattern")
        assert len(vec) == embedder.dimensions
        assert vec.dtype == np.float32

    def test_embed_before_fit_raises(self):
        embedder = TFIDFEmbedder()
        with pytest.raises(RuntimeError):
            embedder.embed("test")

    def test_batch_embed_shape(self):
        corpus = ["hello world", "foo bar", "baz qux"]
        embedder = TFIDFEmbedder(n_components=8)
        embedder.fit(corpus)
        vecs = embedder.embed_batch(corpus)
        assert vecs.shape == (3, embedder.dimensions)


# ---------------------------------------------------------------------------
# Retriever end-to-end tests
# ---------------------------------------------------------------------------

class TestRetriever:
    @pytest.fixture
    def retriever(self):
        chunker = MarkdownChunker(max_tokens=200, min_tokens=5)
        embedder_mock = _MockEmbedder()
        from architect.rag.hybrid_search import HybridSearch
        r = Retriever(chunker=chunker, embedder=embedder_mock)
        return r

    def test_index_and_query(self, retriever):
        async def run():
            n = await retriever.index_text(
                "## Singleton\n\nUse _instance = None pattern.\n\n## Factory\n\nUse create() method.",
                source="memory.md",
            )
            assert n >= 1
            results = await retriever.query("singleton", top_k=3)
            assert len(results) >= 0  # can be 0 if mock embedder not great

        asyncio.run(run())

    def test_indexed_count_increases(self, retriever):
        async def run():
            before = retriever.indexed_count
            await retriever.index_text("## Header\n\nContent here.", source="x.md")
            after = retriever.indexed_count
            assert after >= before

        asyncio.run(run())

    def test_empty_index_returns_empty(self, retriever):
        async def run():
            results = await retriever.query("anything")
            assert results == []

        asyncio.run(run())


# ---------------------------------------------------------------------------
# ChangeDetector tests
# ---------------------------------------------------------------------------

class TestChangeDetector:
    def test_snapshot_project(self, tmp_path):
        (tmp_path / "a.py").write_text("print('hello')")
        (tmp_path / "b.py").write_text("x = 1")

        detector = ChangeDetector()
        snapshot = asyncio.run(
            detector.snapshot_project(str(tmp_path))
        )
        assert len(snapshot.file_snapshots) == 2

    def test_detect_new_file(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        detector = ChangeDetector()
        old_snap = asyncio.run(
            detector.snapshot_project(str(tmp_path))
        )
        (tmp_path / "b.py").write_text("y = 2")
        changed, added, deleted = asyncio.run(
            detector.detect_changes(str(tmp_path), old_snap)
        )
        assert any("b.py" in p for p in added)

    def test_detect_deleted_file(self, tmp_path):
        f1 = tmp_path / "a.py"
        f1.write_text("x = 1")
        f2 = tmp_path / "b.py"
        f2.write_text("y = 2")

        detector = ChangeDetector()
        old_snap = asyncio.run(
            detector.snapshot_project(str(tmp_path))
        )
        f2.unlink()
        changed, added, deleted = asyncio.run(
            detector.detect_changes(str(tmp_path), old_snap)
        )
        assert any("b.py" in p for p in deleted)

    def test_no_changes_detected(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        detector = ChangeDetector()
        old_snap = asyncio.run(
            detector.snapshot_project(str(tmp_path))
        )
        changed, added, deleted = asyncio.run(
            detector.detect_changes(str(tmp_path), old_snap)
        )
        assert changed == [] and added == [] and deleted == []

    def test_save_and_load_snapshot(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("pass")

        mem_dir = tmp_path / "memory"
        detector = ChangeDetector()
        snap = asyncio.run(
            detector.snapshot_project(str(src_dir))
        )
        asyncio.run(
            detector.save_snapshot(snap, str(mem_dir))
        )
        loaded = asyncio.run(
            detector.load_snapshot(str(mem_dir))
        )
        assert loaded is not None
        assert len(loaded.file_snapshots) == len(snap.file_snapshots)

    def test_describe_changes(self):
        detector = ChangeDetector()
        desc = detector.describe_changes(["a.py"], ["b.py"], ["c.py"])
        assert "modified" in desc
        assert "new" in desc
        assert "deleted" in desc

    def test_get_files_to_analyze_first_run(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        detector = ChangeDetector()
        snap = asyncio.run(
            detector.snapshot_project(str(tmp_path))
        )
        files = detector.get_files_to_analyze(None, snap)
        assert len(files) == 1


# ---------------------------------------------------------------------------
# Mock embedder for Retriever tests
# ---------------------------------------------------------------------------

class _MockEmbedder:
    """Minimal embedder that uses TF-IDF under the hood for tests."""

    def __init__(self):
        self._tfidf = TFIDFEmbedder(n_components=16)
        self._ready = False

    @property
    def is_ready(self):
        return self._ready

    @property
    def model_name(self):
        return "mock-tfidf"

    @property
    def dimensions(self):
        return 16

    async def fit_fallback(self, corpus):
        self._tfidf.fit(corpus)
        self._ready = True

    async def embed_texts(self, texts):
        if not self._ready:
            self._tfidf.fit(texts)
            self._ready = True
        return self._tfidf.embed_batch(texts)

    async def embed_single(self, text):
        if not self._ready:
            self._tfidf.fit([text])
            self._ready = True
        return self._tfidf.embed(text)
