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

MAX_FILES = 40
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

    async def analyze_project(self, project_path: str) -> AnalysisSummary:
        """
        Analyse an entire project directory.

        Args:
            project_path: Absolute (or relative) path to the project root.

        Returns:
            AnalysisSummary with aggregated stats and module list.
        """
        start_time = time.monotonic()
        project_path = str(Path(project_path).resolve())

        # --- 1. Scan ---
        await self._emit(AgentEvent(
            type="scan",
            message=f"Scanning {project_path}...",
        ))
        all_files = self._scan_directory(project_path)
        files_scanned = len(all_files)

        await self._emit(AgentEvent(
            type="scan",
            message=f"Found {files_scanned} source files.",
            data={"total": files_scanned},
        ))

        # --- 2. Prioritise ---
        priority_files = self._prioritize_files(all_files)
        files_skipped = files_scanned - len(priority_files)

        if files_skipped > 0:
            await self._emit(AgentEvent(
                type="skip",
                message=(
                    f"Skipping {files_skipped} lower-priority files "
                    f"(keeping top {len(priority_files)})."
                ),
                data={"skipped": files_skipped},
            ))

        # --- 3. Analyse each file ---
        modules: List[dict] = []
        all_patterns_seen: List[str] = []

        for file_path in priority_files:
            result = await self._analyze_file(file_path, project_path)
            if result is not None:
                modules.append(result)
                all_patterns_seen.extend(result.get("patterns", []))

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

        duration = time.monotonic() - start_time

        summary = AnalysisSummary(
            project_path=project_path,
            files_scanned=files_scanned,
            files_analyzed=len(modules),
            files_skipped=files_skipped,
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

        return ordered[:MAX_FILES]

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

        # --- Read content ---
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(MAX_CONTENT_CHARS)
            if len(content) == MAX_CONTENT_CHARS:
                content += "\n... [truncated]"
        except OSError as exc:
            await self._emit(AgentEvent(
                type="error",
                message=f"Cannot read {filename}: {exc}",
                file=file_path,
            ))
            return None

        # --- Emit llm_start ---
        await self._emit(AgentEvent(
            type="llm_start",
            message=f"Reading {filename}...",
            file=file_path,
        ))

        # --- Build prompt and call LLM ---
        prompt = self._build_file_prompt(file_path, content)
        messages = [{"role": "user", "content": prompt}]

        try:
            raw_response = await self._llm.complete(messages)
        except Exception as exc:
            logger.error("LLM call failed for %s: %s", file_path, exc)
            await self._emit(AgentEvent(
                type="error",
                message=f"LLM error on {filename}: {exc}",
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
        """
        Build the analysis prompt for a single file.

        Returns a string that asks the LLM for a JSON-structured summary.
        """
        language = self._detect_language(file_path)
        path_display = file_path

        return (
            f"Analyze this {language} file. "
            "Return a JSON with keys: "
            "purpose (1 sentence), "
            "key_components (list of class/function names), "
            "dependencies (list of imports), "
            "patterns (list of design patterns spotted), "
            "notes (any important observations). "
            f"File: {path_display}\n\n{content}"
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
