"""
Architecture Linter — enforces project-specific architectural rules.

Config file: .architect-rules.yml in project root.

Example config:
    version: 1
    rules:
      - id: no-db-in-controller
        description: "Controllers must not import DB models directly"
        match_files: "src/controllers/**"
        forbidden_imports:
          - "src/models/**"
          - "src/db/**"

      - id: api-extends-base
        description: "API route files must import BaseResponse"
        match_files: "src/api/routes/**"
        required_imports:
          - "BaseResponse"
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    id: str
    description: str
    match_files: str                          # glob pattern
    forbidden_imports: List[str] = field(default_factory=list)
    required_imports: List[str] = field(default_factory=list)


@dataclass
class Violation:
    rule_id: str
    description: str
    file: str
    kind: str                                 # "forbidden" | "required"
    detail: str
    fix_hint: str = ""

    def format_message(self) -> str:
        lines = [
            f"ARCHITECTURE VIOLATION [{self.rule_id}]:",
            f"  File: {self.file}",
            f"  Rule: {self.description}",
            f"  {self.detail}",
        ]
        if self.fix_hint:
            lines.append(f"  Fix: {self.fix_hint}")
        return "\n".join(lines)


class ArchLinter:
    """Load rules from .architect-rules.yml and check files for violations."""

    _RULES_FILENAME = ".architect-rules.yml"

    def __init__(self) -> None:
        self._rules_cache: Optional[List[Rule]] = None
        self._cache_project: Optional[str] = None

    def load_rules(self, project_path: str) -> List[Rule]:
        """Load (and cache) rules from .architect-rules.yml."""
        if self._cache_project == project_path and self._rules_cache is not None:
            return self._rules_cache

        rules_file = Path(project_path) / self._RULES_FILENAME
        if not rules_file.exists():
            self._rules_cache = []
            self._cache_project = project_path
            return []

        try:
            import yaml  # optional dependency
        except ImportError:
            logger.warning("PyYAML not installed — architecture linter disabled.")
            self._rules_cache = []
            self._cache_project = project_path
            return []

        try:
            with rules_file.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)

            rules = []
            for r in data.get("rules", []):
                rules.append(Rule(
                    id=r.get("id", "unknown"),
                    description=r.get("description", ""),
                    match_files=r.get("match_files", "*"),
                    forbidden_imports=r.get("forbidden_imports", []),
                    required_imports=r.get("required_imports", []),
                ))
            self._rules_cache = rules
            self._cache_project = project_path
            logger.info("ArchLinter: loaded %d rules from %s", len(rules), rules_file)
            return rules

        except Exception as exc:
            logger.warning("ArchLinter: failed to parse %s: %s — linter disabled", rules_file, exc)
            self._rules_cache = []
            self._cache_project = project_path
            return []

    def invalidate_cache(self) -> None:
        """Force rule reload on next check (call after config file changes)."""
        self._rules_cache = None
        self._cache_project = None

    def check_file(self, path: str, content: str, project_path: str) -> List[Violation]:
        """Check a file's content against all applicable rules.

        Args:
            path: File path relative to project root.
            content: New file content after the proposed change.
            project_path: Absolute project root path.

        Returns:
            List of Violation objects (empty = no violations).
        """
        rules = self.load_rules(project_path)
        if not rules:
            return []

        violations: List[Violation] = []
        for rule in rules:
            if not self._matches_file(path, rule.match_files):
                continue
            violations.extend(self._check_forbidden(path, content, rule))
            violations.extend(self._check_required(path, content, rule))

        return violations

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_file(file_path: str, pattern: str) -> bool:
        """Return True if file_path matches the glob pattern."""
        # Normalise separators
        fp = file_path.replace("\\", "/")
        pat = pattern.replace("\\", "/")
        return fnmatch.fnmatch(fp, pat) or fnmatch.fnmatch(fp, f"**/{pat.lstrip('*/')}")

    @staticmethod
    def _extract_imports(content: str) -> List[str]:
        """Extract import paths/names from Python or JS/TS source."""
        imports: List[str] = []

        # Python: import x, from x import y
        for m in re.finditer(
            r'^\s*(?:from\s+([\w./]+)\s+import|import\s+([\w./,\s]+))',
            content, re.MULTILINE
        ):
            src = m.group(1) or m.group(2)
            if src:
                imports.append(src.strip())

        # JS/TS: import ... from '...', require('...')
        for m in re.finditer(
            r'''(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"]([^'"]+)['"]''',
            content, re.MULTILINE,
        ):
            imports.append(m.group(1).strip())

        return imports

    def _check_forbidden(self, path: str, content: str, rule: Rule) -> List[Violation]:
        if not rule.forbidden_imports:
            return []
        violations = []
        imports = self._extract_imports(content)
        for imp in imports:
            for forbidden_pat in rule.forbidden_imports:
                if fnmatch.fnmatch(imp, forbidden_pat) or fnmatch.fnmatch(imp, f"*/{forbidden_pat.lstrip('*/')}"):
                    violations.append(Violation(
                        rule_id=rule.id,
                        description=rule.description,
                        file=path,
                        kind="forbidden",
                        detail=f"Found: import from {imp!r} (forbidden by pattern {forbidden_pat!r})",
                        fix_hint="Remove or replace this import with an allowed alternative.",
                    ))
                    break
        return violations

    def _check_required(self, path: str, content: str, rule: Rule) -> List[Violation]:
        if not rule.required_imports:
            return []
        violations = []
        imports = self._extract_imports(content)
        import_text = " ".join(imports)
        for req in rule.required_imports:
            # Simple substring check — req may be a symbol name or path fragment
            if req not in import_text and req not in content:
                violations.append(Violation(
                    rule_id=rule.id,
                    description=rule.description,
                    file=path,
                    kind="required",
                    detail=f"Missing required import: {req!r}",
                    fix_hint=f"Add an import for {req!r} to comply with the architectural rule.",
                ))
        return violations


# Module-level singleton used by agent_runner
_linter = ArchLinter()


def check_file_violations(path: str, content: str, project_path: str) -> List[Violation]:
    """Convenience wrapper using the module-level linter singleton."""
    return _linter.check_file(path, content, project_path)


__all__ = ["ArchLinter", "Rule", "Violation", "check_file_violations"]
