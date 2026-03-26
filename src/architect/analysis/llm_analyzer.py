"""
LLM Analyzer — Core pipeline for LLM-powered file analysis.

Scans a project directory, prioritizes important files, and uses
LLMClient to generate structured summaries stored internally as dicts.

Version: 1.0
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
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

# ---------------------------------------------------------------------------
# Auto-generated / lock files to skip (no architectural value, often huge)
# ---------------------------------------------------------------------------

SKIP_FILES: frozenset[str] = frozenset({
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-lock.yml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
    "mix.lock",
    ".DS_Store",
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "*.chunk.js",
})

MAX_FILES = None  # No limit — analyze all files
MAX_CONTENT_CHARS = 8_000

# Concurrent LLM calls during analysis (tune via env var)
ANALYSIS_CONCURRENCY = int(os.getenv("ANALYSIS_CONCURRENCY", "6"))


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
                force_reanalyze = False

                if snap_count > 0 and modules_count < snap_count:
                    # More than half the snapshotted files have no module entry
                    logger.warning(
                        "Memory mismatch: %d snapshots but only %d modules — clearing snapshot for full re-analysis",
                        snap_count, modules_count,
                    )
                    force_reanalyze = True

                # Also force re-analysis if modules contain LLM errors
                # (previous analysis ran with a bad/missing model)
                if not force_reanalyze and os.path.exists(modules_path):
                    try:
                        import json as _json3
                        mods = _json3.load(open(modules_path))
                        if isinstance(mods, list):
                            error_count = sum(
                                1 for m in mods
                                if isinstance(m.get("purpose"), str)
                                and m["purpose"].startswith("[LLM Error")
                            )
                            if error_count > 0:
                                logger.warning(
                                    "Found %d modules with LLM errors — clearing snapshot for full re-analysis",
                                    error_count,
                                )
                                force_reanalyze = True
                    except Exception:
                        pass

                if force_reanalyze:
                    await self._emit(AgentEvent(
                        type="scan",
                        message="Previous analysis had errors — re-analyzing all files.",
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

        # --- 3. Analyse each file (parallel, bounded by ANALYSIS_CONCURRENCY) ---
        from ..memory.incremental_analysis import FileSnapshot as _FileSnapshot
        from ..memory.incremental_analysis import ProjectSnapshot as _ProjectSnapshot
        import json as _json_inc
        import time as _time

        modules: List[dict] = []
        all_patterns_seen: List[str] = []
        running_snaps = dict(old_snapshot.file_snapshots) if old_snapshot else {}

        semaphore = asyncio.Semaphore(ANALYSIS_CONCURRENCY)
        write_lock = asyncio.Lock()  # protects modules list + disk writes
        total = len(priority_files)

        async def _analyze_one(idx: int, file_path: str) -> None:
            async with semaphore:
                logger.info("Analyzing file %d/%d: %s", idx, total, file_path)
                result = await self._analyze_file(file_path, project_path)
                if result is None:
                    return

                async with write_lock:
                    modules.append(result)
                    all_patterns_seen.extend(result.get("patterns", []))
                    # Persist snapshot + modules so progress survives interruptions
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

        await asyncio.gather(
            *[_analyze_one(idx, fp) for idx, fp in enumerate(priority_files, 1)],
            return_exceptions=True,
        )

        # Deduplicate patterns while preserving order
        seen: set[str] = set()
        unique_patterns: List[str] = []
        for p in all_patterns_seen:
            if p not in seen:
                seen.add(p)
                unique_patterns.append(p)

        # Post-process: build imported_by reverse index across all modules
        modules = self._build_imported_by(modules)

        # Persist final modules.json with imported_by populated.
        # If no new files were analyzed (all skipped), preserve the existing
        # modules.json instead of overwriting it with an empty list.
        if memory_dir:
            try:
                import json as _jfinal
                modules_path_final = os.path.join(memory_dir, "modules.json")
                if not modules and os.path.exists(modules_path_final):
                    # All files were cache-hits — load existing data to keep in memory
                    with open(modules_path_final) as _mf_existing:
                        modules = _jfinal.load(_mf_existing)
                    logger.info("All files skipped — preserved %d cached modules from disk", len(modules))
                else:
                    with open(modules_path_final, "w") as _mf:
                        _jfinal.dump(modules, _mf, ensure_ascii=False, indent=2)
            except Exception as _exc:
                logger.warning("Failed to save final modules.json: %s", _exc)

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
                if filename in SKIP_FILES:
                    continue
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

        memory: dict = {"purpose": "", "public_interface": [], "dependencies": [], "critical_path": False, "edit_hints": ""}
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
                    timeout=180.0,
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
                if parsed.get("critical_path"):
                    memory["critical_path"] = parsed["critical_path"]
                if parsed.get("edit_hints") and not memory["edit_hints"]:
                    memory["edit_hints"] = parsed["edit_hints"]
                for key in ("public_interface", "dependencies"):
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

        # --- Extract symbols via AST/regex (accurate, no LLM cost) ---
        symbols = self._extract_symbols(file_path, content)

        # --- Store in memory ---
        module_entry: dict = {
            "name": filename,
            "path": rel_path,
            "full_path": file_path,
            "purpose": purpose,
            "public_interface": summary_data.get("public_interface", []),
            "dependencies": summary_data.get("dependencies", []),
            "critical_path": bool(summary_data.get("critical_path", False)),
            "edit_hints": summary_data.get("edit_hints", "") or summary_data.get("notes", ""),
            "symbols": symbols,
            "imported_by": [],   # populated in post-processing pass
            "language": self._detect_language(file_path),
        }
        self._memory[file_path] = module_entry

        return module_entry

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_file_prompt(self, file_path: str, content: str) -> str:
        """Build the navigation-map analysis prompt for a single file."""
        language = self._detect_language(file_path)
        return (
            f"You are a senior architect building a navigation map for a {language} file. "
            "Your goal is to produce a compact index that lets an AI agent quickly find the right file "
            "and understand its role — the agent can always read source code directly for details.\n\n"
            "Return JSON with ONLY these keys:\n"
            "- purpose: 1 sentence — what this file does\n"
            "- public_interface: list of exported function signatures "
            "(e.g. ['verify_token(token: str) -> User', 'create_token(user_id: int) -> str'])\n"
            "- dependencies: list of internal imports (not stdlib/third-party)\n"
            "- critical_path: true if this file is on a core business flow (auth, payment, data integrity)\n"
            "- edit_hints: 1 sentence — the single most important gotcha when modifying this file. "
            "'none' if unremarkable.\n\n"
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
            f"You are incrementally building a navigation map for a large {language} file ({file_path}). "
            f"This is chunk {chunk_index}/{total_chunks}.\n"
            f"{memory_str}\n"
            f"Chunk content:\n{chunk}\n\n"
            "Return JSON with keys: purpose, public_interface (list of exported function signatures with types), "
            "dependencies (internal imports only), critical_path (true/false), "
            "edit_hints (most important gotcha or 'none'). "
            f"{instruction}"
        )

    # ------------------------------------------------------------------
    # Symbol extraction (AST for Python, regex for JS/TS)
    # ------------------------------------------------------------------

    def _extract_symbols(self, file_path: str, content: str) -> List[dict]:
        """Extract function/class symbols with line numbers for edit navigation."""
        suffix = Path(file_path).suffix.lower()
        if suffix == ".py":
            return self._extract_symbols_python(content)
        elif suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
            return self._extract_symbols_js(content)
        return []

    @staticmethod
    def _extract_symbols_python(content: str) -> List[dict]:
        """Use Python AST to get accurate symbols with line ranges."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        symbols: List[dict] = []

        def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
            a = node.args
            parts: List[str] = []
            for arg in a.args:
                parts.append(arg.arg)
            if a.vararg:
                parts.append(f"*{a.vararg.arg}")
            for arg in a.kwonlyargs:
                parts.append(arg.arg)
            if a.kwarg:
                parts.append(f"**{a.kwarg.arg}")
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            return f"{prefix}{node.name}({', '.join(parts)})"

        for node in tree.body:
            end = getattr(node, "end_lineno", node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "name": node.name,
                    "type": "function",
                    "line_start": node.lineno,
                    "line_end": end,
                    "signature": _sig(node),
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "type": "class",
                    "line_start": node.lineno,
                    "line_end": end,
                    "signature": f"class {node.name}",
                })
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        item_end = getattr(item, "end_lineno", item.lineno)
                        symbols.append({
                            "name": f"{node.name}.{item.name}",
                            "type": "method",
                            "line_start": item.lineno,
                            "line_end": item_end,
                            "signature": _sig(item),
                        })
        return symbols

    @staticmethod
    def _extract_symbols_js(content: str) -> List[dict]:
        """Regex-based symbol extraction for JS/TS/TSX/JSX (line_start only)."""
        symbols: List[dict] = []
        patterns = [
            (r"(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)\s*\(", "function"),
            (r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", "class"),
            (r"(?:export\s+)?interface\s+(\w+)", "interface"),
            (r"(?:export\s+)?(?:const|let)\s+(\w+)\s*[=:][^=]", "const"),
        ]
        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            for pattern, sym_type in patterns:
                m = re.match(pattern, stripped)
                if m:
                    symbols.append({
                        "name": m.group(1),
                        "type": sym_type,
                        "line_start": line_num,
                        "line_end": line_num,
                        "signature": stripped[:100],
                    })
                    break
        return symbols

    # ------------------------------------------------------------------
    # Imported-by reverse index (post-analysis pass)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_imported_by(modules: List[dict]) -> List[dict]:
        """
        Add `imported_by` to each module: list of files that import it.

        Uses stem-matching heuristic: if module B's path stem appears in
        any of module A's dependency strings, A imports B.
        """
        # stem → list of module paths (multiple files can share a stem)
        stem_map: Dict[str, List[str]] = {}
        for m in modules:
            stem = Path(m.get("path", "")).stem
            if stem:
                stem_map.setdefault(stem, []).append(m["path"])

        path_to_mod = {m["path"]: m for m in modules}
        for m in modules:
            m.setdefault("imported_by", [])

        for m in modules:
            source = m.get("path", "")
            for dep in m.get("dependencies", []):
                dep_stem = Path(dep).stem  # last segment without ext
                for target_path in stem_map.get(dep_stem, []):
                    if target_path != source and target_path in path_to_mod:
                        iby = path_to_mod[target_path]["imported_by"]
                        if source not in iby:
                            iby.append(source)

        return modules

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

    # ------------------------------------------------------------------
    # Refresh (incremental update — only new/changed/error files)
    # ------------------------------------------------------------------

    async def refresh_project(
        self,
        project_path: str,
        memory_dir: str,
    ) -> AnalysisSummary:
        """
        Incremental refresh: only analyze files that are new, changed, or had
        LLM errors in the previous run. Merges results back into modules.json
        and removes paths that no longer exist on disk.

        Args:
            project_path: Absolute path to the project root.
            memory_dir:   Directory where modules.json + SNAPSHOTS.json live.

        Returns:
            AnalysisSummary covering only the refreshed files.
        """
        import json as _j
        from ..memory.incremental_analysis import FileSnapshot as _FileSnapshot
        from ..memory.incremental_analysis import ProjectSnapshot as _ProjectSnapshot
        import time as _time

        start_time = time.monotonic()
        project_path = str(Path(project_path).resolve())
        logger.info("=== refresh_project START: %s ===", project_path)

        # --- Load existing modules.json ---
        modules_path = os.path.join(memory_dir, "modules.json")
        existing_modules: dict[str, dict] = {}  # path → module
        if os.path.isfile(modules_path):
            try:
                raw = _j.loads(open(modules_path).read())
                if isinstance(raw, list):
                    for m in raw:
                        if isinstance(m, dict) and m.get("full_path"):
                            existing_modules[m["full_path"]] = m
                        elif isinstance(m, dict) and m.get("path"):
                            existing_modules[m["path"]] = m
            except Exception:
                pass

        # --- Load existing snapshot ---
        detector = ChangeDetector()
        old_snapshot = await detector.load_snapshot(memory_dir)

        # --- Scan all source files ---
        await self._emit(AgentEvent(type="scan", message=f"⚡ Refreshing {project_path}..."))
        all_files = self._scan_directory(project_path)

        # Build current stat dict
        current_stats: dict[str, dict] = {}
        for fp in all_files:
            try:
                stat = os.stat(fp)
                current_stats[fp] = {"mtime": stat.st_mtime, "size": stat.st_size}
            except OSError:
                pass

        # --- Determine which files need analysis ---
        to_analyze: list[str] = []
        for fp in all_files:
            cur = current_stats.get(fp)
            if cur is None:
                continue

            # New file — not in snapshot at all
            if old_snapshot is None or fp not in old_snapshot.file_snapshots:
                to_analyze.append(fp)
                continue

            snap = old_snapshot.file_snapshots[fp]
            # Changed mtime/size
            if cur["mtime"] != snap.mtime or cur["size"] != snap.size:
                to_analyze.append(fp)
                continue

            # Previous run had LLM error
            mod = existing_modules.get(fp) or existing_modules.get(
                str(Path(fp).relative_to(project_path))
            )
            if mod and isinstance(mod.get("purpose"), str) and mod["purpose"].startswith("[LLM Error"):
                to_analyze.append(fp)

        # Emit skip events for unchanged files
        already_done = set(all_files) - set(to_analyze)
        if already_done:
            await self._emit(AgentEvent(
                type="scan",
                message=f"⚡ Skipping {len(already_done)} unchanged files, re-analyzing {len(to_analyze)}.",
                data={"skipped_analyzed": len(already_done)},
            ))

        if not to_analyze:
            await self._emit(AgentEvent(type="done", message="⚡ Nothing to refresh — all files up to date.", data={"files_analyzed": 0, "patterns_found": 0, "duration_seconds": 0.0}))
            # Still remove deleted files from modules.json
            existing_keys = set(existing_modules.keys())
            on_disk = set(all_files)
            for deleted in existing_keys - on_disk:
                existing_modules.pop(deleted, None)
            merged = list(existing_modules.values())
            with open(modules_path, "w") as _mf:
                _j.dump(merged, _mf, ensure_ascii=False, indent=2)
            return AnalysisSummary(project_path=project_path, files_scanned=len(all_files), files_analyzed=0, files_skipped=len(already_done), modules=merged, all_patterns=[], duration_seconds=0.0)

        # --- Analyze in parallel (same concurrency as analyze_project) ---
        priority_files = self._prioritize_files(to_analyze)
        running_snaps = dict(old_snapshot.file_snapshots) if old_snapshot else {}
        new_modules: list[dict] = []
        semaphore = asyncio.Semaphore(ANALYSIS_CONCURRENCY)
        write_lock = asyncio.Lock()
        total = len(priority_files)

        async def _refresh_one(idx: int, file_path: str) -> None:
            async with semaphore:
                logger.info("Refreshing file %d/%d: %s", idx, total, file_path)
                result = await self._analyze_file(file_path, project_path)
                if result is None:
                    return
                async with write_lock:
                    new_modules.append(result)
                    existing_modules[file_path] = result
                    # Update snapshot for this file
                    try:
                        stat = os.stat(file_path)
                        running_snaps[file_path] = _FileSnapshot(
                            path=file_path, mtime=stat.st_mtime, size=stat.st_size,
                        )
                        partial_snap = _ProjectSnapshot(
                            project_path=project_path,
                            analyzed_at=_time.time(),
                            file_snapshots=running_snaps,
                        )
                        await detector.save_snapshot(partial_snap, memory_dir)
                        merged = list(existing_modules.values())
                        with open(modules_path, "w") as _mf:
                            _j.dump(merged, _mf, ensure_ascii=False, indent=2)
                    except Exception as exc:
                        logger.warning("Failed to save refresh snapshot: %s", exc)

        await asyncio.gather(
            *[_refresh_one(idx, fp) for idx, fp in enumerate(priority_files, 1)],
            return_exceptions=True,
        )

        # --- Remove deleted files from modules.json ---
        on_disk = set(all_files)
        for deleted in list(existing_modules.keys()):
            if deleted not in on_disk:
                existing_modules.pop(deleted)

        merged_modules = list(existing_modules.values())
        with open(modules_path, "w") as _mf:
            _j.dump(merged_modules, _mf, ensure_ascii=False, indent=2)

        all_patterns_seen = [p for m in new_modules for p in m.get("patterns", [])]
        seen: set[str] = set()
        unique_patterns = [p for p in all_patterns_seen if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]

        duration = time.monotonic() - start_time
        await self._emit(AgentEvent(
            type="done",
            message=f"⚡ Refresh complete: {len(new_modules)} files re-analyzed in {duration:.1f}s.",
            data={"files_analyzed": len(new_modules), "patterns_found": len(unique_patterns), "duration_seconds": round(duration, 2)},
        ))

        return AnalysisSummary(
            project_path=project_path,
            files_scanned=len(all_files),
            files_analyzed=len(new_modules),
            files_skipped=len(already_done),
            modules=merged_modules,
            all_patterns=unique_patterns,
            duration_seconds=round(duration, 2),
        )


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
    import os
    from ..llm.client import create_llm_client

    # Use ANALYSIS_LLM_MODEL if set (cheaper model for bulk file analysis),
    # otherwise fall back to DEFAULT_LLM_MODEL.
    analysis_model = os.getenv("ANALYSIS_LLM_MODEL") or os.getenv("DEFAULT_LLM_MODEL")
    return LLMAnalyzer(llm_client=create_llm_client(model=analysis_model) if analysis_model else create_llm_client(), on_event=on_event)


__all__ = [
    "AgentEvent",
    "AnalysisSummary",
    "LLMAnalyzer",
    "create_llm_analyzer",
]
