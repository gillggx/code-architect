"""
FastAPI backend for Code Architect Agent Phase 2

Provides REST API and WebSocket endpoints for project analysis, pattern detection,
semantic search, and real-time progress updates.

Version: 1.0
"""

from .main import create_app
from .errors import APIError, ValidationError, AnalysisError

__all__ = [
    "create_app",
    "APIError",
    "ValidationError",
    "AnalysisError",
]
