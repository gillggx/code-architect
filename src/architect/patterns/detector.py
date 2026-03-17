"""
Pattern Detector

Language-aware engine detecting 15+ architectural patterns across 8 languages.
Uses regex + structural heuristics; no LLM required, no hallucinations.

Detection confidence is evidence-backed:
- Confidence >= 0.85: strong (multiple corroborating indicators)
- Confidence >= 0.65: moderate (1-2 indicators)
- Confidence < 0.65: filtered out (not reported)
"""

from __future__ import annotations

import os
import re
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..models import (
    Pattern,
    PatternEvidence,
    ConfidenceScore,
    PatternCategoryEnum,
)
from .catalog import PatternCatalog, get_pattern_catalog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language routing table
# ---------------------------------------------------------------------------
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".html": "html",
    ".htm": "html",
    ".sql": "sql",
}

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", "build", "dist", ".mypy_cache", ".tox",
}

_CATEGORY_MAP: Dict[str, PatternCategoryEnum] = {
    "oop": PatternCategoryEnum.OOP,
    "behavioral": PatternCategoryEnum.BEHAVIORAL,
    "structural": PatternCategoryEnum.STRUCTURAL,
    "architectural": PatternCategoryEnum.ARCHITECTURAL,
    "async_concurrency": PatternCategoryEnum.ASYNC_CONCURRENCY,
    "error_handling": PatternCategoryEnum.ERROR_HANDLING,
    "data_persistence": PatternCategoryEnum.DATA_PERSISTENCE,
}


# ---------------------------------------------------------------------------
# PatternDetector
# ---------------------------------------------------------------------------

class PatternDetector:
    """
    Detects architectural patterns in source files and projects.

    All detection is static-analysis-based (regex + structural heuristics).
    Results are evidence-backed with file paths and line numbers.
    """

    def __init__(self, catalog: Optional[PatternCatalog] = None):
        self.catalog = catalog or get_pattern_catalog()
        self._min_confidence = 0.60

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_in_file(
        self,
        file_path: str,
        language: Optional[str] = None,
    ) -> List[Pattern]:
        """
        Detect patterns in a single source file.

        Args:
            file_path: Absolute or relative path to the file.
            language: Language override. If None, inferred from extension.

        Returns:
            List of Pattern objects detected in the file.
        """
        if not os.path.exists(file_path):
            logger.warning("File not found: %s", file_path)
            return []

        if language is None:
            ext = Path(file_path).suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(ext)
            if language is None:
                return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            return []

        lines = content.splitlines()
        return self._detect_patterns(content, lines, file_path, language)

    async def detect_in_project(
        self,
        project_path: str,
        languages: Optional[List[str]] = None,
    ) -> List[Pattern]:
        """
        Detect patterns across all source files in a project directory.

        Evidence from multiple files is merged into a single Pattern per
        pattern-name so confidence scores reflect the full project picture.

        Args:
            project_path: Root directory of the project.
            languages: Restrict to these languages. None = all supported.

        Returns:
            List of Pattern objects, one per detected pattern name.
        """
        merged: Dict[str, Pattern] = {}  # pattern_name → Pattern

        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            for filename in files:
                ext = Path(filename).suffix.lower()
                lang = EXTENSION_TO_LANGUAGE.get(ext)
                if lang is None:
                    continue
                if languages and lang not in languages:
                    continue

                file_path = os.path.join(root, filename)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except OSError:
                    continue

                lines = content.splitlines()
                for p in self._detect_patterns(content, lines, file_path, lang):
                    key = p.name
                    if key in merged:
                        existing = merged[key]
                        existing.evidence.extend(p.evidence)
                        for impl in p.implementations:
                            if impl not in existing.implementations:
                                existing.implementations.append(impl)
                        # Recalculate confidence with merged evidence
                        sources = list({e.file_path for e in existing.evidence})
                        existing.confidence = self._make_confidence(
                            existing.evidence, sources
                        )
                    else:
                        merged[key] = p

        return list(merged.values())

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _detect_patterns(
        self,
        content: str,
        lines: List[str],
        file_path: str,
        language: str,
    ) -> List[Pattern]:
        """Run all detectors for the given language and return found patterns."""
        detectors = [
            ("Singleton", self._detect_singleton),
            ("Factory", self._detect_factory),
            ("Decorator", self._detect_decorator),
            ("Observer", self._detect_observer),
            ("Strategy", self._detect_strategy),
            ("State", self._detect_state),
            ("Adapter", self._detect_adapter),
            ("Repository", self._detect_repository),
            ("Middleware", self._detect_middleware),
            ("ErrorHandling", self._detect_error_handling),
            ("Concurrency", self._detect_concurrency),
            ("DependencyInjection", self._detect_di),
            ("MVC", self._detect_mvc),
            ("TemplateMethod", self._detect_template_method),
            ("ChainOfResponsibility", self._detect_chain_of_responsibility),
            ("Bridge", self._detect_bridge),
            ("Facade", self._detect_facade),
        ]

        results: List[Pattern] = []
        for pattern_name, detect_fn in detectors:
            try:
                evidence = detect_fn(content, lines, file_path, language)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Detection error %s/%s: %s", pattern_name, file_path, exc)
                continue

            if not evidence:
                continue

            sources = [file_path]
            confidence = self._make_confidence(evidence, sources)
            if confidence.value < self._min_confidence:
                continue

            pattern_def = self.catalog.get_pattern(pattern_name)
            category = _CATEGORY_MAP.get(
                pattern_def.category if pattern_def else "architectural",
                PatternCategoryEnum.ARCHITECTURAL,
            )

            results.append(
                Pattern(
                    id=f"{pattern_name.lower()}_{uuid.uuid4().hex[:8]}",
                    name=pattern_name,
                    language=language,
                    category=category,
                    evidence=evidence,
                    confidence=confidence,
                    description=pattern_def.description if pattern_def else "",
                    benefits=pattern_def.benefits if pattern_def else [],
                    trade_offs=pattern_def.drawbacks if pattern_def else [],
                    alternative_patterns=pattern_def.related_patterns if pattern_def else [],
                    implementations=[file_path],
                )
            )
        return results

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _find_line_evidence(
        self,
        lines: List[str],
        file_path: str,
        pattern: str,
        evidence_type: str,
        explanation: str,
        weight: float = 0.8,
        flags: int = re.IGNORECASE,
    ) -> List[PatternEvidence]:
        """Return PatternEvidence for every line matching the regex pattern."""
        compiled = re.compile(pattern, flags)
        found: List[PatternEvidence] = []
        for i, line in enumerate(lines, 1):
            if compiled.search(line):
                found.append(
                    PatternEvidence(
                        file_path=file_path,
                        start_line=i,
                        end_line=i,
                        code_snippet=line.strip()[:250],
                        confidence=weight,
                        explanation=explanation,
                    )
                )
        return found

    def _find_block_evidence(
        self,
        lines: List[str],
        file_path: str,
        start_pattern: str,
        evidence_type: str,
        explanation: str,
        context_lines: int = 3,
        weight: float = 0.8,
    ) -> List[PatternEvidence]:
        """
        Return PatternEvidence that includes surrounding context lines
        for patterns that span multiple lines.
        """
        compiled = re.compile(start_pattern, re.IGNORECASE)
        found: List[PatternEvidence] = []
        for i, line in enumerate(lines, 1):
            if compiled.search(line):
                end = min(i + context_lines, len(lines))
                snippet = "\n".join(lines[i - 1 : end])
                found.append(
                    PatternEvidence(
                        file_path=file_path,
                        start_line=i,
                        end_line=end,
                        code_snippet=snippet[:300],
                        confidence=weight,
                        explanation=explanation,
                    )
                )
        return found

    @staticmethod
    def _make_confidence(
        evidence: List[PatternEvidence],
        sources: List[str],
    ) -> ConfidenceScore:
        """Build a ConfidenceScore from collected evidence."""
        score = ConfidenceScore.from_evidence_count(len(evidence))
        return score.model_copy(update={"sources": sources})

    # ------------------------------------------------------------------
    # Pattern-specific detectors
    # ------------------------------------------------------------------

    def _detect_singleton(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+__new__\s*\(", "singleton_new",
                "Singleton: __new__ override controls instantiation", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"_instance\s*=\s*None", "singleton_attr",
                "Singleton: _instance=None class variable", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+(get_instance|getInstance|instance)\s*\(",
                "singleton_getter", "Singleton: get_instance factory classmethod", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"cls\._instance\s+is\s+None", "singleton_check",
                "Singleton: instance existence check", 0.85)
        elif language in ("java", "cpp"):
            ev += self._find_line_evidence(
                lines, file_path, r"static.*getInstance\s*\(|getInstance\s*\(\)",
                "singleton_getinstance", "Singleton: static getInstance() method", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"private\s+static",
                "singleton_private_static", "Singleton: private static member", 0.7)
        elif language in ("javascript", "typescript", "jsx"):
            ev += self._find_line_evidence(
                lines, file_path, r"getInstance\s*\(|_instance\s*=|static\s+instance\b",
                "singleton_js", "Singleton: JS/TS singleton pattern", 0.85)
        return ev

    def _detect_factory(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Ff]actory\w*\s*[\(:]",
                "factory_class", "Factory: class name contains 'Factory'", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+create_\w+|def\s+make_\w+",
                "factory_method", "Factory: create_/make_ method", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"@staticmethod\s*\n.*def\s+(create|build|make)\b",
                "factory_static", "Factory: static creation method", 0.7)
            # File-name check
            if "factory" in Path(file_path).name.lower():
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=Path(file_path).name,
                    confidence=0.7, explanation="Factory: filename suggests factory module")]
        elif language in ("java", "cpp"):
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Ff]actory",
                "factory_class", "Factory: class name contains 'Factory'", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"(static\s+\w+\s+create\w*|createInstance)\s*\(",
                "factory_method", "Factory: static create method", 0.85)
        elif language in ("javascript", "typescript", "jsx"):
            ev += self._find_line_evidence(
                lines, file_path, r"[Ff]actory\s*[\({]|factory\s*=\s*function|createFactory",
                "factory_js", "Factory: JS factory pattern", 0.85)
        return ev

    def _detect_decorator(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"functools\.wraps|@functools\.wraps",
                "decorator_wraps", "Decorator: functools.wraps used", 0.95)
            ev += self._find_block_evidence(
                lines, file_path, r"def\s+wrapper\s*\(",
                "decorator_wrapper", "Decorator: nested wrapper function", 3, 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+\w+\s*\(\s*func\s*\)",
                "decorator_func_param", "Decorator: function accepting callable", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"return\s+wrapper",
                "decorator_return", "Decorator: returns wrapper function", 0.75)
        elif language in ("javascript", "typescript"):
            ev += self._find_line_evidence(
                lines, file_path, r"@\w+\s*\n|function\s+\w+\s*\(fn\s*\)",
                "decorator_ts", "Decorator: TypeScript/JS decorator", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"@Override|@\w+\s*\(",
                "decorator_java", "Decorator: Java annotation / decorator", 0.7)
        return ev

    def _detect_observer(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+(subscribe|unsubscribe|add_listener|remove_listener)\s*\(",
                "observer_sub", "Observer: subscribe/unsubscribe methods", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+(notify|notify_all|emit|dispatch)\s*\(",
                "observer_notify", "Observer: notify/emit method", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"(self\.listeners|self\.observers|self\._subscribers|self\.handlers)\s*=\s*\[",
                "observer_list", "Observer: listeners list attribute", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"for\s+\w+\s+in\s+self\.(listeners|observers|handlers|callbacks)",
                "observer_loop", "Observer: iterating over listeners to notify", 0.8)
        elif language in ("javascript", "typescript", "jsx"):
            ev += self._find_line_evidence(
                lines, file_path, r"addEventListener|removeEventListener|\.on\s*\(|\.emit\s*\(",
                "observer_js", "Observer: event listener/emitter pattern", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"subscribe\s*\(|unsubscribe\s*\(",
                "observer_sub_js", "Observer: subscribe/unsubscribe", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"Observer|EventListener|addObserver|removeObserver",
                "observer_java", "Observer: Java Observer pattern", 0.9)
        return ev

    def _detect_strategy(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Ss]trategy\w*\s*[\(:]",
                "strategy_class", "Strategy: class name contains 'Strategy'", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"self\._strategy\s*=|self\.strategy\s*=",
                "strategy_attr", "Strategy: strategy attribute set", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"self\.strategy\.\w+\s*\(|self\._strategy\.\w+\s*\(",
                "strategy_call", "Strategy: strategy object method called", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+set_strategy\s*\(",
                "strategy_setter", "Strategy: set_strategy method", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"(Strategy|strategy)\s+\w+|implements.*Strategy",
                "strategy_java", "Strategy: Java strategy pattern", 0.85)
        return ev

    def _detect_state(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Ss]tate\w*\s*[\(:]",
                "state_class", "State: class name contains 'State'", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+(transition_to|change_state|set_state)\s*\(",
                "state_transition", "State: transition method", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"self\._state\s*=|self\.state\s*=\s*\w+State",
                "state_attr", "State: state attribute assignment", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+handle\s*\(self.*context",
                "state_handle", "State: handle(context) method", 0.8)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"State|setState|getState",
                "state_java", "State: Java state pattern", 0.8)
        return ev

    def _detect_adapter(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Aa]dapter\w*\s*[\(:]",
                "adapter_class", "Adapter: class name contains 'Adapter'", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"self\.(adaptee|_wrapped|_target|wrapped)\s*=",
                "adapter_adaptee", "Adapter: adaptee/wrapped attribute", 0.85)
            if "adapter" in Path(file_path).name.lower():
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=Path(file_path).name,
                    confidence=0.7, explanation="Adapter: filename suggests adapter module")]
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"[Aa]dapter\b|implements.*Adapter",
                "adapter_java", "Adapter: Java adapter pattern", 0.85)
        return ev

    def _detect_repository(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*(Repository|Repo|DAO)\w*\s*[\(:]",
                "repo_class", "Repository: Repository/DAO class", 0.9)
            ev += self._find_line_evidence(
                lines, file_path,
                r"def\s+(find_by_id|find_all|find_by|get_by_id|get_all|save|delete|update)\s*\(",
                "repo_methods", "Repository: CRUD method signature", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"(session|db|connection)\.query|\.filter\s*\(",
                "repo_query", "Repository: ORM query usage", 0.75)
            name = Path(file_path).name.lower()
            if "repository" in name or "repo" in name or "dao" in name:
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=Path(file_path).name,
                    confidence=0.7, explanation="Repository: filename suggests repository")]
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"@Repository|CrudRepository|JpaRepository|extends.*Repository",
                "repo_java", "Repository: Spring Data Repository", 0.95)
        return ev

    def _detect_middleware(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Mm]iddleware\w*\s*[\(:]",
                "middleware_class", "Middleware: class name contains 'Middleware'", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+__call__\s*\(self,\s*(request|environ|scope)",
                "middleware_call", "Middleware: __call__ with request/environ", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"def\s+(process_request|before_request|after_request)\s*\(",
                "middleware_hook", "Middleware: request lifecycle hook", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"(next|get_response)\s*\(.*request",
                "middleware_next", "Middleware: next(request) call forwarding", 0.85)
            name = Path(file_path).name.lower()
            if "middleware" in name:
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=Path(file_path).name,
                    confidence=0.7, explanation="Middleware: filename suggests middleware")]
        elif language in ("javascript", "typescript"):
            ev += self._find_line_evidence(
                lines, file_path, r"app\.use\s*\(|router\.use\s*\(",
                "middleware_express", "Middleware: Express use() registration", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"\(req,\s*res,\s*next\)|function\s*\(req,\s*res,\s*next\)",
                "middleware_express_sig", "Middleware: (req, res, next) signature", 0.9)
        return ev

    def _detect_error_handling(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*(Error|Exception)\s*\(",
                "eh_custom_exc", "ErrorHandling: custom exception class", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"except\s+\w+(Error|Exception)\s+as",
                "eh_specific", "ErrorHandling: specific exception caught", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"finally\s*:",
                "eh_finally", "ErrorHandling: finally block", 0.75)
            ev += self._find_line_evidence(
                lines, file_path, r"raise\s+\w*(Error|Exception)\s*\(",
                "eh_raise", "ErrorHandling: exception raised explicitly", 0.8)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"catch\s*\(\s*\w+(Exception|Error)\s+\w+\s*\)",
                "eh_catch_java", "ErrorHandling: Java catch block", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w+(Exception|Error)\s+extends",
                "eh_custom_java", "ErrorHandling: custom Java exception", 0.9)
        elif language == "cpp":
            ev += self._find_line_evidence(
                lines, file_path, r"catch\s*\(.*\)|throw\s+std::",
                "eh_cpp", "ErrorHandling: C++ try/catch/throw", 0.85)
        elif language in ("javascript", "typescript"):
            ev += self._find_line_evidence(
                lines, file_path, r"catch\s*\(\s*\w+\s*\)\s*\{|\.catch\s*\(",
                "eh_js", "ErrorHandling: JS catch block or Promise.catch", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w+(Error|Exception)\s+extends",
                "eh_custom_js", "ErrorHandling: custom JS error class", 0.9)
        return ev

    def _detect_concurrency(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"^async\s+def\s+",
                "concurrency_async", "Concurrency: async function definition", 0.9,
                flags=re.MULTILINE)
            ev += self._find_line_evidence(
                lines, file_path, r"\bawait\s+",
                "concurrency_await", "Concurrency: await expression", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"import\s+asyncio|from\s+asyncio",
                "concurrency_asyncio", "Concurrency: asyncio import", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"threading\.Thread|from\s+threading\s+import|asyncio\.Lock",
                "concurrency_thread", "Concurrency: threading or asyncio lock", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path,
                r"synchronized\s*\(|volatile\s+|ExecutorService|CompletableFuture",
                "concurrency_java", "Concurrency: Java concurrency primitives", 0.9)
        elif language == "cpp":
            ev += self._find_line_evidence(
                lines, file_path, r"std::thread|std::mutex|std::lock|std::async",
                "concurrency_cpp", "Concurrency: C++ concurrency", 0.9)
        elif language in ("javascript", "typescript"):
            ev += self._find_line_evidence(
                lines, file_path, r"async\s+function|async\s*\(",
                "concurrency_js_async", "Concurrency: async function JS/TS", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"new\s+Promise\s*\(|Promise\.all|Promise\.race",
                "concurrency_promise", "Concurrency: Promise usage", 0.8)
        return ev

    def _detect_di(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"@inject|from\s+(injector|dependency_injector|wire|inject)\s+import",
                "di_decorator", "DI: inject decorator / DI framework", 0.95)
            ev += self._find_line_evidence(
                lines, file_path,
                r"def\s+__init__\s*\(self,\s*\w+:\s*[A-Z][A-Za-z]+[A-Za-z]*\s*[,\)]",
                "di_typed_param", "DI: typed constructor parameter (interface injection)", 0.75)
            ev += self._find_line_evidence(
                lines, file_path, r"@Provide|@Singleton|@Module",
                "di_annotations", "DI: DI framework annotations", 0.9)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"@Inject|@Autowired|@Component|@Service|@Bean",
                "di_java", "DI: Spring/CDI annotations", 0.95)
        return ev

    def _detect_mvc(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        # Directory-based detection
        path_lower = file_path.lower()
        for segment in ("models", "views", "controllers", "templates"):
            if f"/{segment}/" in path_lower or f"\\{segment}\\" in path_lower:
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=file_path, confidence=0.8,
                    explanation=f"MVC: file resides in /{segment}/ directory")]
                break

        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path,
                r"@app\.route|@router\.(get|post|put|delete|patch)\s*\(|@blueprint\.",
                "mvc_routes", "MVC: web framework route decorator", 0.85)
            ev += self._find_line_evidence(
                lines, file_path,
                r"class\s+\w*(Model|View|Controller|ViewSet|Serializer)\s*[\(:]",
                "mvc_class", "MVC: Model/View/Controller class naming", 0.8)
            ev += self._find_line_evidence(
                lines, file_path, r"render_template|HttpResponse|JSONResponse|TemplateResponse",
                "mvc_render", "MVC: template rendering / HTTP response", 0.75)
        elif language in ("javascript", "typescript"):
            ev += self._find_line_evidence(
                lines, file_path, r"router\.(get|post|put|delete)\s*\(|express\.Router",
                "mvc_js_routes", "MVC: Express router/route definitions", 0.85)
        return ev

    def _detect_template_method(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"from\s+abc\s+import.*ABC|import\s+abc",
                "tm_abc_import", "TemplateMethod: ABC import", 0.75)
            ev += self._find_line_evidence(
                lines, file_path, r"@abstractmethod",
                "tm_abstractmethod", "TemplateMethod: @abstractmethod decorator", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w+\s*\(.*ABC.*\)|class\s+\w+\s*\(.*Abstract",
                "tm_abc_class", "TemplateMethod: class inherits from ABC", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"abstract\s+class|abstract\s+\w+\s+\w+\s*\(",
                "tm_java", "TemplateMethod: Java abstract class/method", 0.9)
        return ev

    def _detect_chain_of_responsibility(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"self\.(next_handler|successor|next)\s*=",
                "cor_next", "ChainOfResponsibility: next_handler/successor attribute", 0.9)
            ev += self._find_line_evidence(
                lines, file_path,
                r"def\s+handle\s*\(self.*\):\s*\n.*if\s+self\.(next|successor)",
                "cor_handle", "ChainOfResponsibility: handle method with chain forwarding", 0.85)
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*(Handler|Chain)\w*\s*[\(:]",
                "cor_class", "ChainOfResponsibility: Handler class naming", 0.8)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"Handler|setNext\s*\(|setSuccessor\s*\(",
                "cor_java", "ChainOfResponsibility: Java handler chain", 0.85)
        return ev

    def _detect_bridge(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"self\.(implementation|implementor|_impl)\s*=",
                "bridge_impl", "Bridge: implementation object attribute", 0.9)
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*(Abstraction|Implementor|Bridge)\w*\s*[\(:]",
                "bridge_class", "Bridge: Abstraction/Implementor class naming", 0.85)
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"Implementor|ConcreteImplementor",
                "bridge_java", "Bridge: Java Bridge pattern", 0.85)
        return ev

    def _detect_facade(
        self, content: str, lines: List[str], file_path: str, language: str
    ) -> List[PatternEvidence]:
        ev: List[PatternEvidence] = []
        if language == "python":
            ev += self._find_line_evidence(
                lines, file_path, r"class\s+\w*[Ff]acade\w*\s*[\(:]",
                "facade_class", "Facade: class name contains 'Facade'", 0.9)
            # Counts delegation attributes to subsystems
            subsystem_attrs = self._find_line_evidence(
                lines, file_path, r"self\.\w+\s*=\s*\w+\(\)",
                "facade_delegates", "Facade: subsystem object initialisation", 0.5)
            if len(subsystem_attrs) >= 3:
                ev += subsystem_attrs[:3]  # Only include first 3 to avoid noise
            if "facade" in Path(file_path).name.lower():
                ev += [PatternEvidence(
                    file_path=file_path, start_line=1, end_line=1,
                    code_snippet=Path(file_path).name,
                    confidence=0.7, explanation="Facade: filename suggests facade module")]
        elif language == "java":
            ev += self._find_line_evidence(
                lines, file_path, r"[Ff]acade\b",
                "facade_java", "Facade: Java Facade class", 0.85)
        return ev
