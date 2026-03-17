"""
Evidence Validator & Robustness Checker

Validates pattern detection evidence for quality and consistency.
Filters out noise, false positives, and low-quality detections.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ..models import Pattern, PatternEvidence, ConfidenceScore

logger = logging.getLogger(__name__)

# Minimum evidence counts to report a pattern at each tier
_MIN_STRONG = 1   # Need at least this many evidence items at weight >= 0.85
_MIN_TOTAL = 1    # At least one evidence item total


class EvidenceValidator:
    """
    Validates PatternEvidence objects for quality and consistency.

    Removes duplicates, empty snippets, and noise from evidence lists.
    """

    def validate(self, evidence: List[PatternEvidence]) -> List[PatternEvidence]:
        """
        Clean and validate an evidence list.

        Removes:
        - Duplicates (same file + line + type)
        - Entries with empty code_snippet
        - Entries with confidence <= 0

        Args:
            evidence: Raw evidence list from detector.

        Returns:
            Cleaned, deduplicated evidence list sorted by confidence desc.
        """
        seen: set[tuple] = set()
        valid: List[PatternEvidence] = []

        for ev in evidence:
            if not ev.code_snippet.strip():
                continue
            if ev.confidence <= 0.0:
                continue

            key = (ev.file_path, ev.start_line, ev.code_snippet[:80])
            if key in seen:
                continue
            seen.add(key)
            valid.append(ev)

        return sorted(valid, key=lambda e: e.confidence, reverse=True)

    def has_strong_evidence(self, evidence: List[PatternEvidence]) -> bool:
        """Return True if at least one evidence item has confidence >= 0.85."""
        return any(e.confidence >= 0.85 for e in evidence)

    def count_by_weight(
        self, evidence: List[PatternEvidence]
    ) -> Tuple[int, int]:
        """Return (strong_count, weak_count) for weight >= 0.8 threshold."""
        strong = sum(1 for e in evidence if e.confidence >= 0.80)
        weak = len(evidence) - strong
        return strong, weak


class RobustnessChecker:
    """
    Checks robustness of detected patterns.

    Flags potentially false-positive detections and adjusts confidence.
    """

    # Languages where generic keyword matching may produce false positives
    _NOISY_LANGUAGES = {"html", "sql"}

    def check(self, patterns: List[Pattern]) -> List[Pattern]:
        """
        Filter and adjust a list of detected patterns for robustness.

        Applies the following rules:
        1. Patterns in noisy languages require higher evidence counts.
        2. ErrorHandling and Concurrency require strong evidence (common keywords).
        3. Patterns with only 1 low-weight indicator are suppressed.

        Args:
            patterns: Detected patterns from PatternDetector.

        Returns:
            Filtered, possibly confidence-adjusted pattern list.
        """
        result: List[Pattern] = []
        for p in patterns:
            adjusted = self._adjust(p)
            if adjusted is not None:
                result.append(adjusted)
        return result

    def _adjust(self, pattern: Pattern) -> Optional[Pattern]:
        """Adjust or discard a single pattern. Returns None to discard."""
        ev = pattern.evidence
        strong = sum(1 for e in ev if e.confidence >= 0.80)
        total = len(ev)

        # Noisy language: require 2+ strong pieces of evidence
        if pattern.language in self._NOISY_LANGUAGES:
            if strong < 2:
                logger.debug(
                    "Suppressed %s in %s (noisy language, only %d strong evidence)",
                    pattern.name, pattern.language, strong,
                )
                return None

        # High-noise patterns need at least 2 evidence items
        if pattern.name in ("ErrorHandling", "Concurrency", "DependencyInjection"):
            if total < 2:
                logger.debug(
                    "Suppressed %s – requires 2+ evidence items, found %d",
                    pattern.name, total,
                )
                return None

        # Single very weak evidence only → skip
        if total == 1 and ev[0].confidence < 0.70:
            logger.debug(
                "Suppressed %s – single low-weight evidence (%.2f)",
                pattern.name, ev[0].confidence,
            )
            return None

        return pattern

    def summary(self, patterns: List[Pattern]) -> dict:
        """Return a summary of pattern counts by category and confidence tier."""
        summary: dict = {
            "total": len(patterns),
            "by_category": {},
            "high_confidence": 0,
            "medium_confidence": 0,
        }
        for p in patterns:
            cat = p.category.value
            summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1
            if p.confidence.value >= 0.85:
                summary["high_confidence"] += 1
            else:
                summary["medium_confidence"] += 1
        return summary


__all__ = ["EvidenceValidator", "RobustnessChecker"]
