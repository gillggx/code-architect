"""
Pattern Base Classes

Provides core data structures for architectural pattern detection:
- PatternEvidence: Code snippets proving pattern existence
- ConfidenceScore: Scoring with evidence count and quality
- Pattern: Detected architectural pattern with metadata

These are re-exported from models.py for backward compatibility.
"""

from architect.models import (
    PatternEvidence,
    ConfidenceScore,
    Pattern,
)

__all__ = [
    "PatternEvidence",
    "ConfidenceScore",
    "Pattern",
]
