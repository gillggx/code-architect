"""
Markdown Chunker

Splits Markdown documents into semantically coherent chunks while:
- Respecting section boundaries (H1/H2/H3 headers)
- Keeping chunks within a configurable token budget (default 500 tokens)
- Preserving parent-header context in each chunk's metadata
- Falling back to sentence splitting when no headers exist

Token estimation: ~4 characters per token (GPT-style approximation).
"""

from __future__ import annotations

import re
import uuid
import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 4 chars ≈ 1 token (rough approximation)
_CHARS_PER_TOKEN = 4


def _count_tokens(text: str) -> int:
    """Approximate token count (no tokenizer dependency)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass
class RawChunk:
    """Internal intermediate chunk before Pydantic wrapping."""
    content: str
    source_file: str
    chunk_index: int
    section_header: Optional[str]
    metadata: dict = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return _count_tokens(self.content)


class MarkdownChunker:
    """
    Header-aware Markdown chunker.

    Splits Markdown content on H1/H2/H3 boundaries and sub-chunks
    sections that exceed the token limit via sentence splitting.

    Args:
        max_tokens: Maximum tokens per chunk (default 500).
        overlap_tokens: Token overlap between consecutive chunks (default 50).
        min_tokens: Minimum tokens to emit a chunk (default 20).
    """

    _HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    _SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

    def __init__(
        self,
        max_tokens: int = 500,
        overlap_tokens: int = 50,
        min_tokens: int = 20,
    ) -> None:
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        source_file: str = "unknown",
        extra_metadata: Optional[dict] = None,
    ) -> List[RawChunk]:
        """
        Chunk a Markdown text string.

        Args:
            text: Raw Markdown content.
            source_file: Source document path (stored in metadata).
            extra_metadata: Additional key-value pairs attached to every chunk.

        Returns:
            Ordered list of RawChunk objects.
        """
        sections = self._split_by_headers(text)
        chunks: List[RawChunk] = []
        index = 0

        for header, body in sections:
            sub_chunks = self._sub_chunk(body, header)
            for sc in sub_chunks:
                if _count_tokens(sc) < self.min_tokens:
                    continue
                metadata = {"source": source_file, "header": header or ""}
                if extra_metadata:
                    metadata.update(extra_metadata)
                chunks.append(RawChunk(
                    content=sc,
                    source_file=source_file,
                    chunk_index=index,
                    section_header=header,
                    metadata=metadata,
                ))
                index += 1

        logger.debug("Chunked %s → %d chunks", source_file, len(chunks))
        return chunks

    def chunk_file(self, file_path: str) -> List[RawChunk]:
        """Read a Markdown file and return its chunks."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError as exc:
            logger.error("Cannot read %s: %s", file_path, exc)
            return []
        return self.chunk_text(text, source_file=file_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_by_headers(self, text: str) -> List[Tuple[Optional[str], str]]:
        """
        Split text into (header, body) sections.

        Returns list of (header_text_or_None, section_body).
        """
        parts: List[Tuple[Optional[str], str]] = []
        last_end = 0
        current_header: Optional[str] = None

        for match in self._HEADER_RE.finditer(text):
            body_so_far = text[last_end : match.start()].strip()
            if body_so_far or current_header is not None:
                parts.append((current_header, body_so_far))
            current_header = match.group(2).strip()
            last_end = match.end()

        # Remaining text after the last header
        tail = text[last_end:].strip()
        if tail or current_header is not None:
            parts.append((current_header, tail))

        return parts

    def _sub_chunk(self, text: str, header: Optional[str]) -> List[str]:
        """Split a section body into token-limited sub-chunks."""
        if not text.strip():
            return []

        max_chars = self.max_tokens * _CHARS_PER_TOKEN
        overlap_chars = self.overlap_tokens * _CHARS_PER_TOKEN

        # Prepend header to each sub-chunk for context
        prefix = f"## {header}\n\n" if header else ""

        if len(text) + len(prefix) <= max_chars:
            return [prefix + text] if (prefix + text).strip() else []

        # Need to split: try sentence boundaries first
        sentences = self._SENTENCE_SPLIT_RE.split(text)
        if len(sentences) == 1:
            # No sentence boundaries → hard split
            return self._hard_split(prefix + text, max_chars, overlap_chars)

        sub_chunks: List[str] = []
        current: List[str] = [prefix]
        current_len = len(prefix)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_len = len(sentence) + 1  # +1 for space

            if current_len + sentence_len > max_chars and len(current) > 1:
                sub_chunks.append(" ".join(current).strip())
                # Start next chunk with overlap
                overlap_sentences = self._take_overlap(current[1:], overlap_chars)
                current = [prefix] + overlap_sentences
                current_len = sum(len(s) + 1 for s in current)

            current.append(sentence)
            current_len += sentence_len

        if current:
            remainder = " ".join(current).strip()
            if remainder:
                sub_chunks.append(remainder)

        return [c for c in sub_chunks if c.strip()]

    @staticmethod
    def _hard_split(text: str, max_chars: int, overlap_chars: int) -> List[str]:
        """Hard character-based split when no sentence boundaries exist."""
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            chunks.append(text[start:end])
            start = end - overlap_chars
        return [c for c in chunks if c.strip()]

    @staticmethod
    def _take_overlap(sentences: List[str], overlap_chars: int) -> List[str]:
        """Return suffix of sentence list that fills up to overlap_chars."""
        result: List[str] = []
        total = 0
        for s in reversed(sentences):
            if total + len(s) > overlap_chars:
                break
            result.insert(0, s)
            total += len(s) + 1
        return result


def chunk_id_for(chunk: RawChunk) -> str:
    """Stable content-addressed chunk ID."""
    h = hashlib.sha256(
        f"{chunk.source_file}:{chunk.chunk_index}:{chunk.content[:100]}".encode()
    ).hexdigest()[:16]
    return f"chunk_{h}"


__all__ = ["MarkdownChunker", "RawChunk", "chunk_id_for"]
