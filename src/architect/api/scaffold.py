"""
Project Scaffold — create a new project directory structure from a template.

Supports four templates:
  fastapi-minimal  — main.py + requirements + README + .gitignore + SOUL.md
  fastapi-full     — minimal + routers/ models/ services/ tests/
  python-lib       — src layout + pyproject.toml + tests/
  agent            — FastAPI + agent lifecycle skeleton using codegen patterns

Called by POST /api/a2a/scaffold.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Boilerplate file content per template
# ---------------------------------------------------------------------------

_GITIGNORE = """\
__pycache__/
*.pyc
*.pyo
.env
.venv/
venv/
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
architect_memory/
.architect/
"""

_SOUL_MD = """\
# Agent Soul

## Personality
You are a careful, quality-focused engineer working on this project.

## Constraints
- Never delete files without confirmation
- Always prefer backward-compatible changes
- Run tests before declaring a task complete
- Keep functions small and focused (SRP)
"""

_FASTAPI_MINIMAL_MAIN = """\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="{name}", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {{"status": "ok"}}
"""

_FASTAPI_REQUIREMENTS = """\
fastapi>=0.104.1
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
httpx>=0.27.0
pytest>=7.4.3
pytest-asyncio>=0.21.1
"""

_FASTAPI_FULL_ROUTER = """\
from fastapi import APIRouter

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/")
async def list_items() -> list:
    return []


@router.post("/")
async def create_item(payload: dict) -> dict:
    return payload
"""

_FASTAPI_FULL_MODEL = """\
from pydantic import BaseModel
from typing import Optional


class Item(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
"""

_FASTAPI_FULL_SERVICE = """\
from ..models.item import Item
from typing import List


class ItemService:
    def __init__(self) -> None:
        self._store: List[Item] = []

    def list_all(self) -> List[Item]:
        return self._store

    def create(self, item: Item) -> Item:
        self._store.append(item)
        return item
"""

_FASTAPI_FULL_MAIN = """\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import items

app = FastAPI(title="{name}", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(items.router)


@app.get("/health")
async def health() -> dict:
    return {{"status": "ok"}}
"""

_FASTAPI_FULL_TEST = """\
import pytest
from fastapi.testclient import TestClient
from {package}.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {{"status": "ok"}}
"""

_PYLIB_PYPROJECT = """\
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.4", "pytest-cov"]
"""

_PYLIB_INIT = '"""{}"""'

_PYLIB_CORE = """\
# Core module — add your implementation here


def hello(name: str = "world") -> str:
    return f"Hello, {{name}}!"
"""

_PYLIB_TEST = """\
from {package}.core import hello


def test_hello():
    assert hello() == "Hello, world!"
    assert hello("Claude") == "Hello, Claude!"
"""

_AGENT_MAIN = """\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .agent import AgentRouter

app = FastAPI(title="{name} Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent_router = AgentRouter()
app.include_router(agent_router.router)


@app.get("/health")
async def health() -> dict:
    return {{"status": "ok"}}
"""

_AGENT_SKELETON = """\
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4
from fastapi import APIRouter

logger = logging.getLogger(__name__)


@dataclass
class AgentSession:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "idle"
    memory: List[Dict[str, Any]] = field(default_factory=list)


class AgentRouter:
    \"\"\"Minimal agent with session management and memory.\"\"\"

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/agent", tags=["agent"])
        self._sessions: Dict[str, AgentSession] = {}
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.post("/session")
        async def create_session() -> dict:
            sess = AgentSession()
            self._sessions[sess.session_id] = sess
            return {{"session_id": sess.session_id, "status": sess.status}}

        @self.router.post("/session/{{session_id}}/run")
        async def run_task(session_id: str, payload: dict) -> dict:
            sess = self._sessions.get(session_id)
            if not sess:
                return {{"error": "session not found"}}
            task = payload.get("task", "")
            # TODO: replace with real agent logic
            result = await self._execute(sess, task)
            return {{"session_id": session_id, "result": result}}

    async def _execute(self, session: AgentSession, task: str) -> str:
        \"\"\"Override with real agent logic.\"\"\"
        session.memory.append({{"task": task}})
        return f"Received task: {{task}}"
"""

_AGENT_REQUIREMENTS = """\
fastapi>=0.104.1
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
httpx>=0.27.0
openai>=1.0.0
pytest>=7.4.3
pytest-asyncio>=0.21.1
"""


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

VALID_TEMPLATES = ("fastapi-minimal", "fastapi-full", "python-lib", "agent")


@dataclass
class ScaffoldResult:
    project_path: str
    project_id: str
    template: str
    files_created: List[str] = field(default_factory=list)
    git_initialized: bool = False
    error: Optional[str] = None


def _write(base: Path, rel: str, content: str) -> str:
    """Write a file relative to base, creating parent dirs. Returns rel path."""
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return rel


def _derive_package(project_name: str) -> str:
    """Turn a project name into a valid Python package identifier."""
    return project_name.lower().replace("-", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_project(
    project_path: str,
    template: str,
    project_name: Optional[str] = None,
    git_init: bool = True,
) -> ScaffoldResult:
    """
    Create a new project at *project_path* from *template*.

    Raises ValueError on invalid template.
    Raises FileExistsError if the target directory is non-empty.
    """
    if template not in VALID_TEMPLATES:
        raise ValueError(
            f"Unknown template '{template}'. "
            f"Valid options: {', '.join(VALID_TEMPLATES)}"
        )

    base = Path(project_path).expanduser().resolve()
    name = project_name or base.name or "my-project"
    pkg = _derive_package(name)

    # Conflict check
    if base.exists() and any(base.iterdir()):
        raise FileExistsError(
            f"Directory '{base}' already exists and is not empty."
        )

    base.mkdir(parents=True, exist_ok=True)

    # Derive project_id (same algorithm as main.py analyze endpoint)
    import hashlib
    pid_hash = hashlib.md5(str(base).encode()).hexdigest()[:8]
    folder_name = base.name or "project"
    project_id = f"{folder_name}-{pid_hash}"

    files: List[str] = []
    write = lambda rel, content: files.append(_write(base, rel, content))

    # ── fastapi-minimal ──────────────────────────────────────────────────────
    if template == "fastapi-minimal":
        write("main.py", _FASTAPI_MINIMAL_MAIN.format(name=name))
        write("requirements.txt", _FASTAPI_REQUIREMENTS)
        write("README.md", f"# {name}\n\nFastAPI project.\n")
        write(".gitignore", _GITIGNORE)
        write("SOUL.md", _SOUL_MD)

    # ── fastapi-full ─────────────────────────────────────────────────────────
    elif template == "fastapi-full":
        write(f"{pkg}/__init__.py", _PYLIB_INIT.format(name))
        write(f"{pkg}/main.py", _FASTAPI_FULL_MAIN.format(name=name))
        write(f"{pkg}/routers/__init__.py", "")
        write(f"{pkg}/routers/items.py", _FASTAPI_FULL_ROUTER)
        write(f"{pkg}/models/__init__.py", "")
        write(f"{pkg}/models/item.py", _FASTAPI_FULL_MODEL)
        write(f"{pkg}/services/__init__.py", "")
        write(f"{pkg}/services/item_service.py", _FASTAPI_FULL_SERVICE)
        write("tests/__init__.py", "")
        write("tests/test_api.py", _FASTAPI_FULL_TEST.format(package=pkg))
        write("requirements.txt", _FASTAPI_REQUIREMENTS)
        write("README.md", f"# {name}\n\nFastAPI project.\n\n## Run\n\n```bash\nuvicorn {pkg}.main:app --reload\n```\n")
        write(".gitignore", _GITIGNORE)
        write("SOUL.md", _SOUL_MD)

    # ── python-lib ───────────────────────────────────────────────────────────
    elif template == "python-lib":
        write("pyproject.toml", _PYLIB_PYPROJECT.format(name=name))
        write(f"src/{pkg}/__init__.py", _PYLIB_INIT.format(name))
        write(f"src/{pkg}/core.py", _PYLIB_CORE)
        write("tests/__init__.py", "")
        write("tests/test_core.py", _PYLIB_TEST.format(package=pkg))
        write("README.md", f"# {name}\n\nPython library.\n")
        write(".gitignore", _GITIGNORE)
        write("SOUL.md", _SOUL_MD)

    # ── agent ────────────────────────────────────────────────────────────────
    elif template == "agent":
        write(f"{pkg}/__init__.py", _PYLIB_INIT.format(name))
        write(f"{pkg}/main.py", _AGENT_MAIN.format(name=name))
        write(f"{pkg}/agent.py", _AGENT_SKELETON)
        write("tests/__init__.py", "")
        write("requirements.txt", _AGENT_REQUIREMENTS)
        write("README.md", f"# {name}\n\nAI Agent service.\n\n## Run\n\n```bash\nuvicorn {pkg}.main:app --reload\n```\n")
        write(".gitignore", _GITIGNORE)
        write("SOUL.md", _SOUL_MD)

    # ── git init ─────────────────────────────────────────────────────────────
    git_ok = False
    if git_init:
        try:
            subprocess.run(
                ["git", "init"],
                cwd=str(base), capture_output=True, text=True, timeout=10,
                check=True,
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=str(base), capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", "chore: initial scaffold"],
                cwd=str(base), capture_output=True, text=True, timeout=15,
            )
            git_ok = True
        except Exception as exc:
            logger.warning("git init failed for %s: %s", base, exc)

    logger.info("Scaffolded %s (%s) — %d files, git=%s", base, template, len(files), git_ok)
    return ScaffoldResult(
        project_path=str(base),
        project_id=project_id,
        template=template,
        files_created=files,
        git_initialized=git_ok,
    )
