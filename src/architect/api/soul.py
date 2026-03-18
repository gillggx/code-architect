"""
SOUL.md loader — reads agent personality/constraints from project root.
Falls back to DEFAULT_SOUL if no SOUL.md is found.
"""
import os
import logging

logger = logging.getLogger(__name__)

DEFAULT_SOUL = """## Agent Identity & Constraints
- You are a precise, methodical software engineer.
- Prefer minimal, targeted changes over large rewrites.
- Always read files before editing them.
- Respect existing code conventions and patterns.
- Never write secrets, credentials, or API keys to disk.
- When uncertain, ask for clarification rather than guessing.
- Run tests after making changes when possible.
"""

def load_soul(project_path: str) -> str:
    """Load SOUL.md from project root, or return DEFAULT_SOUL."""
    soul_path = os.path.join(project_path, "SOUL.md")
    if os.path.isfile(soul_path):
        try:
            with open(soul_path, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                logger.info("Loaded SOUL.md from %s", soul_path)
                return content
        except OSError as exc:
            logger.warning("Could not read SOUL.md: %s", exc)
    return DEFAULT_SOUL
