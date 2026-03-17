"""
Pattern Detection System

Detects architectural patterns across all 8 supported languages:
- Python, C++, Java, SQL, JavaScript, TypeScript, JSX, HTML

Provides pattern catalog, detection engine, and confidence scoring.
"""

from .base import Pattern, PatternEvidence, ConfidenceScore
from .catalog import PatternCatalog, get_pattern_catalog
from .detector import PatternDetector

__all__ = [
    "Pattern",
    "PatternEvidence",
    "ConfidenceScore",
    "PatternCatalog",
    "get_pattern_catalog",
    "PatternDetector",
]
