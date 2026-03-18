"""
LLM Analyzer — Core pipeline for LLM-powered file analysis.

Scans a project directory, prioritizes important files, and uses
LLMClient to generate structured summaries stored internally as dicts.

Version: 1.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..llm.client import LLMClient
from ..memory.incremental_analysis import ChangeDetector, ProjectSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directories to skip during directory scan
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcoverage",
    "site-packages",
    "eggs",
    ".eggs",
})

# ---------------------------------------------------------------------------
# Files considered entry points (highest priority)
# ---------------------------------------------------------------------------

ENTRY_POINT_NAMES: frozenset[str] = frozenset({
    "main.py",
    "app.py",
    "server.py",
    "index.py",
    "cli.py",
    "run.py",
    "start.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "index.ts",
    "index.js",
    "app.ts",
    "app.js",
    "server.ts",
    "server.js",
    "main.ts",
    "main.js",
    "index.tsx",
    "index.jsx",
})

# Config file names (second priority)
CONFIG_NAMES: frozenset[str] = frozenset({
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "package.json",
    "tsconfig.json",
    "webpack.config.js",
    "vite.config.ts",
    "vite.config.js",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "Makefile",
    ".env.example",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
})

# Source file extensions to analyse
SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".md",
})

# Extension → language name
LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
}

MAX_FILES = None  # No limit — analyze all files
MAX_CONTENT_CHARS = 8_000


# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------


@dataclass
class AgentEvent:
    """Event emitted during LLM analysis pipeline execution."""

    type: str  # scan|ast|llm_start|llm_done|memory|pattern|skip|done|error
    message: str
    file: Optional[str] = None
    summary: Optional[str] = None
    data: Optional[dict] = None


@dataclass
class AnalysisSummary:
    """High-level result returned after analysing a project."""

    project_path: str
    files_scanned: int
    files_analyzed: int
    files_skipped: int
    modules: List[dict] = field(default_factory=list)
    all_patterns: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# LLMAnalyzer
# ---------------------------------------------------------------------------


class LLMAnalyzer:
    """
    Core LLM analysis pipeline.

    Orchestrates directory scanning, file prioritisation, LLM calls, and
    result aggregation.  Events are pushed to an async callback so callers
    (WebSocket handlers, CLI progress bars, …) can react in real-time.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        on_event: Callable[[AgentEvent], Awaitable[None]],
    ) -> None:
        self._llm = llm_client
        self._on_event = on_event
        # Internal in-memory store: file_path → summary dict
        self._memory: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    async def analyze_project(
        self,
        project_path: str,
        memory_dir: Optional[str] = None,
    ) -> AnalysisSummary:
        """
        Analyse an entire project directory.

        Args:
            project_path: Absolute (or relative) path to the project root.
            memory_dir: Directory for Tier-2 memory / snapshots. When provided,
                        incremental analysis is enabled — only changed/new files
                        are re-analysed.

        Returns:
            AnalysisSummary with aggregated stats and module list.
        """
        start_time = time.monotonic()
        project_path = str(Path(project_path).resolve())
        logger.info("=== analyze_project START: %s ===", project_path)

        # --- 1. Scan ---
        await self._emit(AgentEvent(
            type="scan",
            message=f"Scanning {project_path}...",
        ))
        logger.info("Scan started")
        all_files = self._scan_directory(project_path)
        files_scanned = len(all_files)

        await self._emit(AgentEvent(
            type="scan",
            message=f"Found {files_scanned} source files.",
            data={"total": files_scanned},
        ))

        # --- 1b. Incremental: load old snapshot, detect changes ---
        # Snapshot only records ANALYZED files (not entire project), so we can
        # safely save it after each file without incorrectly marking unanalyzed
        # files as done.
        detector = ChangeDetector()
        old_snapshot: Optional[ProjectSnapshot] = None
        if memory_dir:
            old_snapshot = await detector.load_snapshot(memory_dir)

            # Sanity check: if snapshot claims many files done but modules.json
            # has far fewer entries, the memory is corrupt — force full re-analysis
            if old_snapshot and old_snapshot.file_snapshots:
                modules_path = os.path.join(memory_dir, "modules.json")
                modules_count = 0
                if os.path.exists(modules_path):
                    try:
                        import json as _json2
                        modules_count = len(_json2.load(open(modules_path)))
                    except Exception:
                        pass
                snap_count = len(old_snapshot.file_snapshots)
                if snap_count > 0 and modules_count < snap_count:
                    # More than half the snapshotted files have no module entry
                    logger.warning(
                        "Memory mismatch: %d snapshots but only %d modules — clearing snapshot for full re-analysis",
                        snap_count, modules_count,
                    )
                    await self._emit(AgentEvent(
                        type="scan",
                        message=f"Memory inconsistent ({snap_count} snapshots, {modules_count} modules) — re-analyzing all files.",
                    ))
                    old_snapshot = None  # force full re-analysis

            if old_snapshot:
                # Build current snapshot only for files in priority list
                import time as _time
                current_file_snaps = {}
                for fp in all_files:
                    try:
                        stat = os.stat(fp)
                        current_file_snaps[fp] = {
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                        }
                    except OSError:
                        pass

                # A file needs analysis if: not in snapshot, or mtime/size changed
                already_done = set()
                for fp, snap in old_snapshot.file_snapshots.items():
                    cur = current_file_snaps.get(fp)
                    if cur and cur["mtime"] == snap.mtime and cur["size"] == snap.size:
                        already_done.add(fp)

                skipped_count = len(already_done)
                if skipped_count > 0:
                    await self._emit(AgentEvent(
                        type="scan",
                        message=f"Incremental mode: skipping {skipped_count} already-analyzed files.",
                        data={"skipped_analyzed": skipped_count},
                    ))
                    for fp in sorted(already_done):
                        rel = os.path.relpath(fp, project_path)
                        await self._emit(AgentEvent(type="skip", message=f"Already analyzed: {rel}", file=rel))

                all_files = [f for f in all_files if f not in already_done]
                files_scanned = len(all_files)

        # --- 2. Prioritise ---
        priority_files = self._prioritize_files(all_files)
        files_skipped_priority = files_scanned - len(priority_files)

        if files_skipped_priority > 0:
            await self._emit(AgentEvent(
                type="skip",
                message=(
                    f"Skipping {files_skipped_priority} lower-priority files "
                    f"(keeping top {len(priority_files)})."
                ),
                data={"skipped": files_skipped_priority},
            ))

        # --- 3. Analyse each file ---
        modules: List[dict] = []
        all_patterns_seen: List[str] = []

        # Build snapshot dict in memory; flush to disk after each file (no repeated loads)
        from ..memory.incremental_analysis import FileSnapshot as _FileSnapshot
        from ..memory.incremental_analysis import ProjectSnapshot as _ProjectSnapshot
        import json as _json_inc
        import time as _time
        running_snaps = dict(old_snapshot.file_snapshots) if old_snapshot else {}

        for idx, file_path in enumerate(priority_files, 1):
            logger.info("Analyzing file %d/%d: %s", idx, len(priority_files), file_path)
            result = await self._analyze_file(file_path, project_path)
            if result is not None:
                modules.append(result)
                all_patterns_seen.extend(result.get("patterns", []))
                # Save incremental snapshot + modules after each file so progress
                # survives interruptions. Both must stay in sync.
                if memory_dir:
                    try:
                        stat = os.stat(file_path)
                        running_snaps[file_path] = _FileSnapshot(
                            path=file_path,
                            mtime=stat.st_mtime,
                            size=stat.st_size,
                        )
                        partial_snap = _ProjectSnapshot(
                            project_path=project_path,
                            analyzed_at=_time.time(),
                            file_snapshots=running_snaps,
                        )
                        await detector.save_snapshot(partial_snap, memory_dir)

                        modules_path_inc = os.path.join(memory_dir, "modules.json")
                        with open(modules_path_inc, "w") as _mf:
                            _json_inc.dump(modules, _mf, ensure_ascii=False, indent=2)
                    except Exception as _exc:
                        logger.warning("Failed to save incremental snapshot/modules: %s", _exc)

        # Deduplicate patterns while preserving order
        seen: set[str] = set()
        unique_patterns: List[str] = []
        for p in all_patterns_seen:
            if p not in seen:
                seen.add(p)
                unique_patterns.append(p)

        # --- 4. Memory / persistence event ---
        await self._emit(AgentEvent(
            type="memory",
            message="Saving to memory...",
            data={"files_stored": len(self._memory)},
        ))

        # --- 4b. Final snapshot already saved per-file above; nothing to do here ---

        duration = time.monotonic() - start_time

        summary = AnalysisSummary(
            project_path=project_path,
            files_scanned=files_scanned,
            files_analyzed=len(modules),
            files_skipped=files_skipped_priority,
            modules=modules,
            all_patterns=unique_patterns,
            duration_seconds=round(duration, 2),
        )

        await self._emit(AgentEvent(
            type="done",
            message=(
                f"Analysis complete: {len(modules)} files analysed "
                f"in {duration:.1f}s."
            ),
            data={
                "files_analyzed": len(modules),
                "patterns_found": len(unique_patterns),
                "duration_seconds": round(duration, 2),
            },
        ))

        return summary

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def _scan_directory(self, project_path: str) -> List[str]:
        """
        Walk the project tree and return paths of all recognised source files.

        Skips SKIP_DIRS entirely to avoid noise.
        """
        result: List[str] = []
        root = Path(project_path)

        for dirpath_str, dirnames, filenames in os.walk(root):
            # Prune skipped directories in-place so os.walk does not descend
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

            dirpath = Path(dirpath_str)

            for filename in filenames:
                file_path = dirpath / filename
                suffix = file_path.suffix.lower()
                if suffix in SOURCE_EXTENSIONS:
                    result.append(str(file_path))

        return result

    # ------------------------------------------------------------------
    # File prioritisation
    # ------------------------------------------------------------------

    def _prioritize_files(self, files: List[str]) -> List[str]:
        """
        Return up to MAX_FILES files ordered by importance:

        1. Entry-point files (main.py, index.ts, …)
        2. Config / build files (setup.py, package.json, …)
        3. Files with the most import/require statements (proxy for
           centrality in the dependency graph)
        4. Remaining files in path-alphabetical order
        """
        entry_points: List[str] = []
        configs: List[str] = []
        import_rich: List[tuple[int, str]] = []  # (import_count, path)
        rest: List[str] = []

        for fp in files:
            name = Path(fp).name
            if name in ENTRY_POINT_NAMES:
                entry_points.append(fp)
            elif name in CONFIG_NAMES:
                configs.append(fp)
            else:
                count = self._count_imports(fp)
                if count > 0:
                    import_rich.append((count, fp))
                else:
                    rest.append(fp)

        # Sort import-rich files descending by import count
        import_rich.sort(key=lambda t: t[0], reverse=True)
        import_rich_paths = [fp for _, fp in import_rich]

        ordered = (
            sorted(entry_points)
            + sorted(configs)
            + import_rich_paths
            + sorted(rest)
        )

        return ordered if MAX_FILES is None else ordered[:MAX_FILES]

    def _count_imports(self, file_path: str) -> int:
        """Count import/require statements as a quick proxy for file centrality."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(4096)  # only peek at first 4 KB
            count = 0
            for line in content.splitlines():
                stripped = line.strip()
                if (
                    stripped.startswith("import ")
                    or stripped.startswith("from ")
                    or "require(" in stripped
                    or stripped.startswith("use ")
                ):
                    count += 1
            return count
        except OSError:
            return 0

    # ------------------------------------------------------------------
    # Per-file LLM analysis
    # ------------------------------------------------------------------

    async def _analyze_file(
        self, file_path: str, project_path: str
    ) -> Optional[dict]:
        """
        Read a file, call the LLM for a structured summary, and return a
        module dict.  Returns None if the file cannot be read or the LLM
        call fails fatally.
        """
        filename = Path(file_path).name

        # --- Read content (full file, no hard cap) ---
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError as exc:
            await self._emit(AgentEvent(
                type="error",
                message=f"Cannot read {filename}: {exc}",
                file=file_path,
            ))
            return None

        # --- Chunked analysis for large files ---
        chunks = [content[i:i + MAX_CONTENT_CHARS] for i in range(0, len(content), MAX_CONTENT_CHARS)]
        total_chunks = len(chunks)

        await self._emit(AgentEvent(
            type="llm_start",
            message=f"Reading {filename}..." if total_chunks == 1 else f"Reading {filename} ({total_chunks} chunks)...",
            file=file_path,
        ))

        memory: dict = {"purpose": "", "key_components": [], "dependencies": [], "patterns": [], "notes": []}
        raw_response = ""

        for chunk_index, chunk in enumerate(chunks, start=1):
            if total_chunks > 1:
                await self._emit(AgentEvent(
                    type="llm_start",
                    message=f"  {filename} chunk {chunk_index}/{total_chunks}...",
                    file=file_path,
                ))

            if total_chunks == 1:
                prompt = self._build_file_prompt(file_path, chunk)
            else:
                prompt = self._build_chunk_prompt(file_path, chunk, chunk_index, total_chunks, memory)

            try:
                raw_response = await asyncio.wait_for(
                    self._llm.complete([{"role": "user", "content": prompt}]),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                logger.warning("LLM call timed out for %s chunk %d (90s), skipping chunk", file_path, chunk_index)
                await self._emit(AgentEvent(
                    type="error",
                    message=f"Timeout on {filename} chunk {chunk_index}/{total_chunks}, skipping chunk.",
                    file=file_path,
                ))
                continue  # skip this chunk, carry on with what we have

            # Merge chunk result into memory for next chunk
            try:
                parsed = self._parse_llm_response(raw_response)
                if parsed.get("purpose"):
                    memory["purpose"] = parsed["purpose"]
                for key in ("key_components", "dependencies", "patterns", "notes"):
                    existing = memory.get(key, [])
                    new_items = parsed.get(key, [])
                    if isinstance(new_items, list):
                        seen = set(existing)
                        memory[key] = existing + [x for x in new_items if x not in seen]
                    elif isinstance(new_items, str) and new_items:
                        memory[key] = existing + [new_items]
            except Exception:
                pass  # keep existing memory if parse fails

        # Use merged memory as the final raw_response for downstream parsing
        import json as _json
        raw_response = _json.dumps(memory)

        # If we got nothing useful from all chunks, skip this file
        if not memory.get("purpose"):
            await self._emit(AgentEvent(
                type="error",
                message=f"Could not analyze {filename} (all chunks failed), skipping.",
                file=file_path,
            ))
            return None

        # --- Parse JSON (with fallback) ---
        summary_data = self._parse_llm_response(raw_response)

        purpose: str = summary_data.get("purpose", "No description available.")
        patterns: List[str] = summary_data.get("patterns", [])

        # Relative path for display
        try:
            rel_path = str(Path(file_path).relative_to(project_path))
        except ValueError:
            rel_path = file_path

        # --- Emit llm_done ---
        summary_text = raw_response if not isinstance(summary_data, dict) else json.dumps(summary_data)
        await self._emit(AgentEvent(
            type="llm_done",
            file=file_path,
            summary=summary_text,
            message=f"✓ {filename}: {purpose}",
        ))

        # Emit individual pattern events
        for pattern in patterns:
            await self._emit(AgentEvent(
                type="pattern",
                message=f"Pattern detected in {filename}: {pattern}",
                file=file_path,
                data={"pattern": pattern},
            ))

        # --- Store in memory ---
        module_entry: dict = {
            "name": filename,
            "path": rel_path,
            "full_path": file_path,
            "purpose": purpose,
            "key_components": summary_data.get("key_components", []),
            "dependencies": summary_data.get("dependencies", []),
            "patterns": patterns,
            "notes": summary_data.get("notes", ""),
            "language": self._detect_language(file_path),
        }
        self._memory[file_path] = module_entry

        return module_entry

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_file_prompt(self, file_path: str, content: str) -> str:
        """Build the analysis prompt for a single file (small files only)."""
        language = self._detect_language(file_path)
        return (
            f"Analyze this {language} file. "
            "Return a JSON with keys: "
            "purpose (1 sentence), "
            "key_components (list of class/function names), "
            "dependencies (list of imports), "
            "patterns (list of design patterns spotted), "
            "notes (any important observations). "
            f"File: {file_path}\n\n{content}"
        )

    def _build_chunk_prompt(
        self,
        file_path: str,
        chunk: str,
        chunk_index: int,
        total_chunks: int,
        memory: dict,
    ) -> str:
        """Build a prompt for one chunk of a large file, carrying accumulated memory."""
        language = self._detect_language(file_path)
        memory_str = (
            f"So far from previous chunks:\n"
            f"- Purpose: {memory.get('purpose', 'unknown')}\n"
            f"- Components found: {', '.join(memory.get('key_components', [])) or 'none yet'}\n"
            f"- Dependencies: {', '.join(memory.get('dependencies', [])) or 'none yet'}\n"
            f"- Patterns: {', '.join(memory.get('patterns', [])) or 'none yet'}\n"
        ) if chunk_index > 1 else ""

        instruction = (
            "Summarize your full understanding into the final JSON."
            if chunk_index == total_chunks
            else "Update the running analysis with anything new you find. Return JSON only."
        )

        return (
            f"You are incrementally analyzing a large {language} file ({file_path}). "
            f"This is chunk {chunk_index}/{total_chunks}.\n"
            f"{memory_str}\n"
            f"Chunk content:\n{chunk}\n\n"
            f"Return JSON with keys: purpose, key_components, dependencies, patterns, notes. "
            f"{instruction}"
        )

    # ------------------------------------------------------------------
    # Language detection
    # ------------------------------------------------------------------

    def _detect_language(self, file_path: str) -> str:
        """Return a human-readable language name based on file extension."""
        suffix = Path(file_path).suffix.lower()
        return LANGUAGE_MAP.get(suffix, "Unknown")

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_llm_response(raw: str) -> dict:
        """
        Attempt to parse the LLM response as JSON.

        Tries three strategies in order:
          1. Direct JSON parse of the whole response.
          2. Extract the first ```json ... ``` code block.
          3. Find the first '{' … last '}' substring and parse that.

        Falls back to wrapping the raw text in a minimal dict on failure.
        """
        text = raw.strip()

        # Strategy 1: direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: code-fenced JSON block
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start) if "```" in text[start:] else len(text)
            snippet = text[start:end].strip()
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass

        # Strategy 3: first '{' … last '}'
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            snippet = text[brace_start : brace_end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass

        # Fallback: treat entire response as a plain note
        logger.warning("LLM response was not valid JSON; storing as raw text.")
        return {
            "purpose": text[:200] if text else "Unknown",
            "key_components": [],
            "dependencies": [],
            "patterns": [],
            "notes": text,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _emit(self, event: AgentEvent) -> None:
        """Fire the on_event callback, swallowing any exceptions."""
        try:
            await self._on_event(event)
        except Exception as exc:
            logger.warning("on_event callback raised: %s", exc)


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def create_llm_analyzer(
    on_event: Callable[[AgentEvent], Awaitable[None]],
) -> LLMAnalyzer:
    """
    Convenience factory.  Creates a default LLMClient and wraps it in an
    LLMAnalyzer wired to the supplied event callback.

    Args:
        on_event: Async callable that receives AgentEvent objects.

    Returns:
        Configured LLMAnalyzer instance.
    """
    from ..llm.client import create_llm_client

    return LLMAnalyzer(llm_client=create_llm_client(), on_event=on_event)


__all__ = [
    "AgentEvent",
    "AnalysisSummary",
    "LLMAnalyzer",
    "create_llm_analyzer",
]
