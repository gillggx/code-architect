"""
FastAPI main application for Code Architect Agent Phase 2B

REST API + WebSocket endpoints for project analysis, pattern detection,
semantic search, and real-time progress updates.

Version: 1.0
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from ..models import (
    Pattern, ConfidenceScore, PatternEvidence,
    AnalysisStatusEnum, SearchResult,
)
from ..patterns import PatternDetector
from ..rag import HybridSearch, MarkdownChunker as Chunker
from ..projects import ProjectManager
from ..analysis import LargeProjectHandler, create_llm_analyzer, AgentEvent

from .errors import APIError, ValidationError, AnalysisError, InternalError
from .auth import (
    init_auth, get_auth_middleware, get_api_key_manager,
    get_rate_limiter, AuthMiddleware,
)
from .schemas import (
    HealthStatus, ErrorResponse, AnalysisRequest, AnalysisResult,
    AnalysisProgress, PatternMatch, SearchRequest, SearchResponse,
    SearchResult as SearchResultSchema, ProjectListResponse, ProjectInfo,
    ValidationRequest, ValidationResponse, ValidationIssue,
    SuggestionRequest, SuggestionResponse, PatternSuggestion,
    ChatRequest, A2AQueryRequest, A2AQueryResponse,
    GenerateRequest, GenerateResponse, FileChangeSchema,
    ValidateRequest, ValidateResponse,
    ImpactRequest, ImpactResponse,
    ScaffoldRequest, ScaffoldResponse,
    CodegenRequest, CodegenResponse,
    ApproveRequest,
    ApprovePlanRequest,
    EscalationRequest,
    RevertRequest,
    RollbackRequest,
)
from ..llm import create_chat_engine, get_or_create_session
from .websocket import (
    WebSocketMessage, get_connection_manager, WebSocketConnectionManager,
    ProgressNotifier,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Application State
# ============================================================================

class AppState:
    """Application state and services
    
    Attributes:
        start_time: Application start time
        pattern_detector: Pattern detection engine
        hybrid_search: Semantic search engine
        project_manager: Project management service
        large_project_handler: Large project analysis handler
        active_jobs: Tracking of running analysis jobs
    """
    
    def __init__(self):
        """Initialize application state"""
        self.start_time = datetime.utcnow()
        self.pattern_detector: Optional[PatternDetector] = None
        self.hybrid_search: Optional[HybridSearch] = None
        self.project_manager: Optional[ProjectManager] = None
        self.large_project_handler: Optional[LargeProjectHandler] = None
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.chat_engine = None  # Initialised in lifespan


# Global state
_app_state = AppState()


# ============================================================================
# Lifespan Events
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context
    
    Args:
        app: FastAPI application
    """
    # Startup
    logger.info("Starting Code Architect API")
    
    # Initialize services
    _app_state.pattern_detector = PatternDetector()
    _app_state.hybrid_search = HybridSearch()
    _app_state.project_manager = ProjectManager()
    _app_state.large_project_handler = LargeProjectHandler()
    _app_state.chat_engine = create_chat_engine()

    # Initialize authentication
    init_auth(
        default_key="test-key-12345",
        requests_per_minute=60,
        requests_per_hour=1000,
        require_auth=False,
    )
    
    logger.info("Code Architect API ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Code Architect API")


# ============================================================================
# FastAPI Application Factory
# ============================================================================

def create_app(debug: bool = False) -> FastAPI:
    """Create and configure FastAPI application
    
    Args:
        debug: Whether to enable debug mode
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Code Architect Agent API",
        description="REST API + WebSocket for project analysis",
        version="1.0.0",
        debug=debug,
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # ========================================================================
    # Health & Status
    # ========================================================================
    
    @app.get(
        "/health",
        response_model=HealthStatus,
        tags=["health"],
        summary="Health check",
    )
    async def health_check() -> HealthStatus:
        """Get API health status
        
        Returns:
            HealthStatus with uptime and version info
        """
        uptime = (datetime.utcnow() - _app_state.start_time).total_seconds()
        return HealthStatus(
            status="healthy",
            timestamp=datetime.utcnow(),
            version="1.0.0",
            uptime_seconds=uptime,
        )
    
    @app.get(
        "/stats",
        tags=["health"],
        summary="Get API statistics",
    )
    async def get_stats() -> Dict[str, Any]:
        """Get API usage statistics
        
        Returns:
            Statistics dictionary
        """
        rate_limiter = get_rate_limiter()
        ws_manager = get_connection_manager()
        
        return {
            "active_jobs": len(_app_state.active_jobs),
            "websocket_stats": ws_manager.get_stats(),
            "rate_limits": {
                "requests_per_minute": rate_limiter.requests_per_minute,
                "requests_per_hour": rate_limiter.requests_per_hour,
            },
        }
    
    # ========================================================================
    # Analysis Endpoints
    # ========================================================================
    
    @app.post(
        "/api/analyze",
        tags=["analysis"],
        summary="Start project analysis — returns job_id, stream events via WS",
    )
    async def analyze_project(request: AnalysisRequest, req: Request) -> dict:
        """
        Start LLM-powered project analysis.

        Returns job_id immediately. Connect to /ws/analyze/{job_id} to
        receive real-time AgentEvents as the LLM reads each file and
        builds memory.
        """
        auth_middleware = get_auth_middleware()
        await auth_middleware(req)

        if not os.path.exists(request.project_path):
            raise ValidationError(
                f"Project path does not exist: {request.project_path}",
                field="project_path",
            )

        import hashlib
        job_id = str(uuid4())
        # Derive a stable project_id from the path so the same project
        # always maps to the same memory_dir (enables incremental analysis).
        if request.project_id:
            project_id = request.project_id
        else:
            path_hash = hashlib.sha1(
                os.path.abspath(request.project_path).encode()
            ).hexdigest()[:12]
            folder_name = os.path.basename(request.project_path.rstrip("/")) or "project"
            project_id = f"{folder_name}-{path_hash}"

        # Register job so WS endpoint can track it
        async with _app_state._lock:
            _app_state.active_jobs[job_id] = {
                "status": "queued",
                "project_id": project_id,
                "project_path": request.project_path,
                "summary": None,
            }

        # Init event buffer BEFORE task starts so no events are missed
        manager = get_connection_manager()
        await manager.init_job_buffer(job_id)

        async def run_analysis():
            manager = get_connection_manager()

            async def on_event(event: AgentEvent):
                """Forward AgentEvent to all WebSocket clients watching this job."""
                payload = {
                    "type": event.type,
                    "message": event.message,
                    "file": event.file,
                    "summary": event.summary,
                    "data": event.data,
                }
                # Track progress so chat can report analysis status
                if event.type == "done" and event.file:
                    async with _app_state._lock:
                        job = _app_state.active_jobs.get(job_id, {})
                        job["files_analyzed"] = job.get("files_analyzed", 0) + 1
                        if event.data and isinstance(event.data, dict):
                            job["total_files"] = event.data.get("total_files", job.get("total_files", 0))
                ws_msg = WebSocketMessage(
                    type="agent_event",
                    job_id=job_id,
                    data=payload,
                )
                await manager.broadcast_to_job(job_id, ws_msg)

            try:
                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "running"

                memory_dir = os.path.join(
                    "architect_memory", project_id
                )
                analyzer = create_llm_analyzer(on_event=on_event)
                summary = await analyzer.analyze_project(
                    request.project_path,
                    memory_dir=memory_dir,
                )

                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "complete"
                    _app_state.active_jobs[job_id]["summary"] = summary

                # Persist project path for later use by edit agent
                os.makedirs(memory_dir, exist_ok=True)
                with open(os.path.join(memory_dir, "project_path.txt"), "w") as _pf:
                    _pf.write(os.path.abspath(request.project_path))

                # Persist modules to disk + inject into chat engine
                if summary.modules:
                    import json as _json
                    modules_path = os.path.join(memory_dir, "modules.json")
                    os.makedirs(memory_dir, exist_ok=True)
                    with open(modules_path, "w") as _f:
                        _json.dump(summary.modules, _f, ensure_ascii=False, indent=2)
                    _app_state.chat_engine.update_project_context(project_id, summary.modules)

                await manager.broadcast_to_job(job_id, WebSocketMessage(
                    type="agent_event",
                    job_id=job_id,
                    data={
                        "type": "done",
                        "message": f"Analysis complete — {summary.files_analyzed} files analyzed, {len(summary.all_patterns)} patterns found",
                        "data": {
                            "files_scanned": summary.files_scanned,
                            "files_analyzed": summary.files_analyzed,
                            "files_skipped": summary.files_skipped,
                            "patterns": summary.all_patterns,
                            "modules": summary.modules,
                            "duration_seconds": summary.duration_seconds,
                        },
                    },
                ))

            except Exception as exc:
                logger.error("Analysis job %s failed: %s", job_id, exc)
                await manager.broadcast_to_job(job_id, WebSocketMessage(
                    type="agent_event",
                    job_id=job_id,
                    data={"type": "error", "message": str(exc)},
                ))
                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "error"

        # Fire and forget — client tracks via WebSocket
        asyncio.create_task(run_analysis())

        return {"job_id": job_id, "project_id": project_id, "status": "queued"}

    @app.post(
        "/api/analyze/refresh",
        tags=["analysis"],
        summary="Incremental refresh — only re-analyze new/changed/error files",
    )
    async def refresh_analysis(request: AnalysisRequest, req: Request) -> dict:
        """
        Like /api/analyze but skips files that haven't changed since the last run.
        Requires an existing modules.json + SNAPSHOTS.json in architect_memory.
        Falls back to full analysis if no prior snapshot exists.
        """
        auth_middleware = get_auth_middleware()
        await auth_middleware(req)

        if not os.path.exists(request.project_path):
            raise ValidationError(
                f"Project path does not exist: {request.project_path}",
                field="project_path",
            )

        import hashlib
        job_id = str(uuid4())
        if request.project_id:
            project_id = request.project_id
        else:
            path_hash = hashlib.sha1(
                os.path.abspath(request.project_path).encode()
            ).hexdigest()[:12]
            folder_name = os.path.basename(request.project_path.rstrip("/")) or "project"
            project_id = f"{folder_name}-{path_hash}"

        async with _app_state._lock:
            _app_state.active_jobs[job_id] = {
                "status": "queued",
                "project_id": project_id,
                "project_path": request.project_path,
                "summary": None,
            }

        manager = get_connection_manager()
        await manager.init_job_buffer(job_id)

        async def run_refresh():
            manager = get_connection_manager()

            async def on_event(event: AgentEvent):
                payload = {
                    "type": event.type,
                    "message": event.message,
                    "file": event.file,
                    "summary": event.summary,
                    "data": event.data,
                }
                ws_msg = WebSocketMessage(type="agent_event", job_id=job_id, data=payload)
                await manager.broadcast_to_job(job_id, ws_msg)

            try:
                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "running"

                memory_dir = os.path.join("architect_memory", project_id)
                os.makedirs(memory_dir, exist_ok=True)
                with open(os.path.join(memory_dir, "project_path.txt"), "w") as _pf:
                    _pf.write(os.path.abspath(request.project_path))

                analyzer = create_llm_analyzer(on_event=on_event)

                # If no snapshot exists fall back to full analysis
                snap_path = os.path.join(memory_dir, "SNAPSHOTS.json")
                if not os.path.isfile(snap_path):
                    summary = await analyzer.analyze_project(
                        request.project_path, memory_dir=memory_dir,
                    )
                else:
                    summary = await analyzer.refresh_project(
                        request.project_path, memory_dir=memory_dir,
                    )

                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "complete"
                    _app_state.active_jobs[job_id]["summary"] = summary

                if summary.modules:
                    import json as _json
                    modules_path = os.path.join(memory_dir, "modules.json")
                    os.makedirs(memory_dir, exist_ok=True)
                    with open(modules_path, "w") as _f:
                        _json.dump(summary.modules, _f, ensure_ascii=False, indent=2)
                    _app_state.chat_engine.update_project_context(project_id, summary.modules)

                await manager.broadcast_to_job(job_id, WebSocketMessage(
                    type="agent_event",
                    job_id=job_id,
                    data={
                        "type": "done",
                        "message": f"⚡ Refresh complete — {summary.files_analyzed} files re-analyzed",
                        "data": {
                            "files_scanned": summary.files_scanned,
                            "files_analyzed": summary.files_analyzed,
                            "files_skipped": summary.files_skipped,
                            "patterns": summary.all_patterns,
                            "modules": summary.modules,
                            "duration_seconds": summary.duration_seconds,
                        },
                    },
                ))

            except Exception as exc:
                logger.error("Refresh job %s failed: %s", job_id, exc)
                await manager.broadcast_to_job(job_id, WebSocketMessage(
                    type="agent_event",
                    job_id=job_id,
                    data={"type": "error", "message": str(exc)},
                ))
                async with _app_state._lock:
                    _app_state.active_jobs[job_id]["status"] = "error"

        asyncio.create_task(run_refresh())
        return {"job_id": job_id, "project_id": project_id, "status": "queued", "mode": "refresh"}

    @app.get(
        "/api/jobs/{job_id}",
        response_model=AnalysisProgress,
        tags=["analysis"],
        summary="Get job progress",
    )
    async def get_job_progress(job_id: str) -> AnalysisProgress:
        """Get progress for ongoing analysis job
        
        Args:
            job_id: Job identifier
        
        Returns:
            Current progress information
        
        Raises:
            NotFoundError: If job not found
        """
        if job_id not in _app_state.active_jobs:
            from .errors import NotFoundError
            raise NotFoundError(
                f"Job not found: {job_id}",
                resource_type="job",
            )
        
        job_info = _app_state.active_jobs[job_id]
        return AnalysisProgress(
            job_id=job_id,
            status=job_info.get("status", "unknown"),
            progress_percent=job_info.get("progress_percent", 0),
            files_processed=job_info.get("files_processed", 0),
            files_total=job_info.get("files_total", 0),
            current_step=job_info.get("current_step", ""),
            eta_seconds=job_info.get("eta_seconds"),
        )
    
    # ========================================================================
    # Search Endpoints
    # ========================================================================
    
    @app.post(
        "/api/search",
        response_model=SearchResponse,
        tags=["search"],
        summary="Semantic search",
    )
    async def search(
        request: SearchRequest,
        req: Request,
    ) -> SearchResponse:
        """Search project memory semantically
        
        Args:
            request: Search request parameters
            req: FastAPI request (for auth)
        
        Returns:
            Search results with confidence scores
        
        Raises:
            ValidationError: If request is invalid
        """
        # Check auth/rate limits
        auth_middleware = get_auth_middleware()
        api_key, description = await auth_middleware(req)
        
        if len(request.query) < 3:
            raise ValidationError(
                "Query must be at least 3 characters",
                field="query"
            )
        
        try:
            # Search (simplified - would use actual RAG system)
            start_time = datetime.utcnow()
            
            results = [
                SearchResultSchema(
                    id=f"result-{i}",
                    type="pattern",
                    title=f"Pattern match for '{request.query}'",
                    content=f"Found potential architectural pattern",
                    confidence=0.85 - (i * 0.05),
                    location={"file": "example.py", "line": 100 + i * 10},
                    source="pattern_detector",
                )
                for i in range(min(request.top_k, 5))
            ]
            
            exec_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return SearchResponse(
                query=request.query,
                results=results,
                total_results=len(results),
                execution_time_ms=exec_time,
            )
        
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise AnalysisError(
                detail="Search failed",
                reason=str(e),
            ) from e
    
    # ========================================================================
    # Project Management
    # ========================================================================
    
    @app.get(
        "/api/projects",
        tags=["projects"],
        summary="List projects",
    )
    async def list_projects(req: Request) -> dict:
        """List all analyzed projects by reading from architect_memory/ directory."""
        import json as _json
        import shutil as _shutil

        memory_base = "architect_memory"
        results = []

        if os.path.isdir(memory_base):
            for entry in os.scandir(memory_base):
                if not entry.is_dir():
                    continue
                project_id = entry.name
                project_path_file = os.path.join(entry.path, "project_path.txt")
                modules_file = os.path.join(entry.path, "modules.json")

                if not os.path.exists(project_path_file):
                    continue

                try:
                    with open(project_path_file) as pf:
                        project_path = pf.read().strip()
                except Exception:
                    continue

                module_count = 0
                last_analyzed = None

                if os.path.exists(modules_file):
                    try:
                        mtime = os.path.getmtime(modules_file)
                        last_analyzed = datetime.utcfromtimestamp(mtime).isoformat() + "Z"
                        with open(modules_file) as mf:
                            modules_data = _json.load(mf)
                            module_count = len(modules_data) if isinstance(modules_data, list) else 0
                    except Exception:
                        pass

                project_name = project_path.rstrip("/").split("/")[-1] if project_path else project_id

                results.append({
                    "project_id": project_id,
                    "project_path": project_path,
                    "project_name": project_name,
                    "last_analyzed": last_analyzed,
                    "module_count": module_count,
                })

        # Sort by last_analyzed descending (None goes to end)
        results.sort(key=lambda x: x["last_analyzed"] or "", reverse=True)

        return {"projects": results, "total_count": len(results)}

    @app.get(
        "/api/projects/{project_id}/load",
        tags=["projects"],
        summary="Load a project's memory modules and file tree",
    )
    async def load_project(project_id: str) -> dict:
        """
        Returns stored memory modules and a reconstructed file tree for a
        previously analyzed project, so the UI can restore workspace state
        without re-running analysis.
        """
        import json as _j

        memory_dir = os.path.join("architect_memory", project_id)
        if not os.path.isdir(memory_dir):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

        # Read project path
        project_path = ""
        path_file = os.path.join(memory_dir, "project_path.txt")
        if os.path.isfile(path_file):
            project_path = open(path_file).read().strip()

        # Read modules
        modules: list = []
        modules_file = os.path.join(memory_dir, "modules.json")
        if os.path.isfile(modules_file):
            try:
                raw = _j.loads(open(modules_file).read())
                modules = raw if isinstance(raw, list) else list(raw.values())
            except Exception:
                pass

        # Build file tree from modules (status = done for all known files)
        file_nodes = []
        for m in modules:
            file_nodes.append({
                "path": m.get("full_path") or os.path.join(project_path, m.get("path", "")),
                "name": m.get("name") or m.get("path", ""),
                "status": "done",
                "summary": m.get("purpose") or "",
                "isDir": False,
            })

        return {
            "project_id": project_id,
            "project_path": project_path,
            "modules": modules,
            "file_tree": file_nodes,
        }

    @app.get(
        "/api/projects/{project_id}/graph",
        tags=["projects"],
        summary="Dependency graph for Cytoscape visualization",
    )
    async def project_graph(project_id: str) -> dict:
        """
        Builds a node/edge graph from modules.json dependency lists.
        - Nodes: one per MemoryModule (internal) + external packages
        - Edges: internal if dependency resolves to a known module path;
                 external otherwise
        No LLM calls — pure data transformation.
        """
        import json as _j

        memory_dir = os.path.join("architect_memory", project_id)
        if not os.path.isdir(memory_dir):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

        modules_file = os.path.join(memory_dir, "modules.json")
        if not os.path.isfile(modules_file):
            return {"nodes": [], "edges": []}

        try:
            raw = _j.loads(open(modules_file).read())
            modules: list = raw if isinstance(raw, list) else []
        except Exception:
            return {"nodes": [], "edges": []}

        # Read project path for entry-point detection
        path_file = os.path.join(memory_dir, "project_path.txt")
        project_path = open(path_file).read().strip() if os.path.isfile(path_file) else ""

        # Build lookups for dependency resolution
        # path_lookup: full/rel path → module
        # stem_lookup: filename-without-extension → module  (e.g. "scenarios" → scenarios.py)
        path_lookup: dict[str, dict] = {}
        stem_lookup: dict[str, dict] = {}
        for m in modules:
            if m.get("full_path"):
                path_lookup[m["full_path"]] = m
            if m.get("path"):
                path_lookup[m["path"]] = m
                path_lookup[os.path.basename(m["path"])] = m
            # Index by stem — "scenarios.py" → key "scenarios"
            name = m.get("name") or os.path.basename(m.get("path", "") or m.get("full_path", ""))
            stem = name.rsplit(".", 1)[0] if "." in name else name
            if stem:
                stem_lookup[stem] = m

        ENTRY_NAMES = {"main.py", "app.py", "server.py", "index.ts", "index.js",
                       "app.ts", "app.js", "server.ts", "server.js", "main.ts",
                       "main.js", "index.tsx", "index.jsx"}

        nodes = []
        edges = []
        external_nodes: set[str] = set()

        for m in modules:
            node_id = m.get("full_path") or m.get("path", "")
            name = m.get("name") or os.path.basename(node_id)
            nodes.append({
                "id": node_id,
                "name": name,
                "purpose": m.get("purpose", ""),
                "patterns": m.get("patterns", []),
                "is_entry": name in ENTRY_NAMES,
                "type": "internal",
            })

        for m in modules:
            source_id = m.get("full_path") or m.get("path", "")
            for dep in m.get("dependencies", []):
                if not dep or not isinstance(dep, str):
                    continue
                dep = dep.strip()

                # Resolve dep to an internal module.
                # deps may be: "scenarios", "scenarios.ValidationResult",
                # "from scenarios import X", bare package name, etc.
                resolved = None

                # Extract the root module name from various formats
                # e.g. "scenarios.ValidationResult" → "scenarios"
                #      "from scenarios import X"    → "scenarios"
                dep_clean = dep
                if dep_clean.startswith("from "):
                    dep_clean = dep_clean.split()[1]  # "from X import ..." → "X"
                if dep_clean.startswith("import "):
                    dep_clean = dep_clean.split()[1]

                # Segments to try: first segment and last segment
                first_seg = dep_clean.split(".")[0].split("/")[0]
                last_seg  = dep_clean.split(".")[-1].split("/")[-1]

                stem_candidates = [dep_clean, first_seg, last_seg]
                path_candidates = [
                    dep_clean,
                    dep_clean.replace(".", "/") + ".py",
                    dep_clean.replace(".", "/") + ".ts",
                    dep_clean.replace(".", "/") + ".tsx",
                    first_seg + ".py",
                    first_seg + ".ts",
                    first_seg + ".tsx",
                    first_seg + ".js",
                    os.path.basename(dep_clean),
                ]

                # Stem lookup first (most reliable for Python/TS imports)
                for sc in stem_candidates:
                    if sc and sc in stem_lookup:
                        target = stem_lookup[sc]
                        resolved = target.get("full_path") or target.get("path", "")
                        break

                # Fall back to path lookup
                if not resolved:
                    for c in path_candidates:
                        if c and c in path_lookup:
                            target = path_lookup[c]
                            resolved = target.get("full_path") or target.get("path", "")
                            break

                if resolved and resolved != source_id:
                    edges.append({"source": source_id, "target": resolved, "type": "internal"})
                else:
                    # External dependency — add node once
                    ext_id = dep.split(".")[0].split("/")[0]  # top-level package name
                    if ext_id and ext_id not in external_nodes:
                        external_nodes.add(ext_id)
                        nodes.append({
                            "id": ext_id,
                            "name": ext_id,
                            "purpose": "",
                            "patterns": [],
                            "is_entry": False,
                            "type": "external",
                        })
                    if ext_id and ext_id != source_id:
                        edges.append({"source": source_id, "target": ext_id, "type": "external"})

        # Deduplicate edges
        seen_edges: set[tuple] = set()
        unique_edges = []
        for e in edges:
            key = (e["source"], e["target"])
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return {"nodes": nodes, "edges": unique_edges}

    @app.get(
        "/api/projects/{project_id}/freshness",
        tags=["projects"],
        summary="Check if tracked files have changed since last analysis",
    )
    async def project_freshness(project_id: str) -> dict:
        """
        Pure filesystem stat check — no LLM calls. Runs in < 100ms.

        Returns:
          last_analyzed_at  — ISO timestamp of last analysis (from SNAPSHOTS.json mtime)
          total_tracked     — number of files in the snapshot
          changed_files     — files whose mtime or size differs from snapshot
          new_files         — source files on disk not in the snapshot
          deleted_files     — files in snapshot that no longer exist on disk
          is_fresh          — True when no changes detected
        """
        import json as _j
        from datetime import timezone

        memory_dir = os.path.join("architect_memory", project_id)
        if not os.path.isdir(memory_dir):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

        snap_path = os.path.join(memory_dir, "SNAPSHOTS.json")
        if not os.path.isfile(snap_path):
            return {
                "last_analyzed_at": None,
                "total_tracked": 0,
                "changed_files": [],
                "new_files": [],
                "deleted_files": [],
                "is_fresh": False,
            }

        # Load snapshot
        try:
            snap_data = _j.loads(open(snap_path).read())
        except Exception:
            raise HTTPException(status_code=500, detail="Could not read snapshot")

        snap_mtime = os.path.getmtime(snap_path)
        last_analyzed_at = datetime.fromtimestamp(snap_mtime, tz=timezone.utc).isoformat()
        file_snapshots: dict = snap_data.get("file_snapshots", {})

        # Compare each tracked file against its snapshot
        changed_files = []
        deleted_files = []
        for fpath, snap in file_snapshots.items():
            if not os.path.exists(fpath):
                deleted_files.append({"path": fpath, "reason": "deleted"})
                continue
            try:
                stat = os.stat(fpath)
                if stat.st_mtime != snap.get("mtime") or stat.st_size != snap.get("size"):
                    changed_files.append({"path": fpath, "reason": "mtime_changed"})
            except OSError:
                deleted_files.append({"path": fpath, "reason": "unreadable"})

        # Detect new source files not yet in snapshot
        # Read project path to scan for new files
        new_files = []
        path_file = os.path.join(memory_dir, "project_path.txt")
        if os.path.isfile(path_file):
            project_path = open(path_file).read().strip()
            if os.path.isdir(project_path):
                skip_dirs = frozenset({
                    "node_modules", ".git", "__pycache__", "venv", ".venv",
                    "env", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
                    "site-packages",
                })
                source_exts = frozenset({
                    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
                    ".java", ".cpp", ".c", ".h", ".hpp", ".cs",
                    ".toml", ".yaml", ".yml",
                })
                for dirpath, dirnames, filenames in os.walk(project_path):
                    dirnames[:] = [
                        d for d in dirnames
                        if d not in skip_dirs and not d.startswith(".")
                    ]
                    for fname in filenames:
                        fp = os.path.join(dirpath, fname)
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in source_exts and fp not in file_snapshots:
                            new_files.append({"path": fp, "reason": "not_in_memory"})

        is_fresh = not changed_files and not new_files and not deleted_files

        return {
            "last_analyzed_at": last_analyzed_at,
            "total_tracked": len(file_snapshots),
            "changed_files": changed_files,
            "new_files": new_files,
            "deleted_files": deleted_files,
            "is_fresh": is_fresh,
        }

    @app.delete(
        "/api/projects/{project_id}",
        tags=["projects"],
        summary="Delete a project's memory",
    )
    async def delete_project(project_id: str) -> dict:
        """Remove the architect_memory/{project_id} directory."""
        import shutil as _shutil
        memory_dir = os.path.join("architect_memory", project_id)
        if not os.path.isdir(memory_dir):
            from .errors import NotFoundError
            raise NotFoundError(f"Project not found: {project_id}", resource_type="project")
        try:
            _shutil.rmtree(memory_dir)
        except Exception as exc:
            raise InternalError(detail=f"Failed to delete project: {exc}") from exc
        return {"deleted": project_id}

    @app.post(
        "/api/chat/new-project",
        tags=["chat"],
        summary="Chat to plan a new project (SSE streaming)",
    )
    async def chat_new_project(request: ChatRequest):
        """
        SSE streaming chat with a new-project planning system prompt.
        Same format as /api/chat: {"type": "chunk"|"done"|"error", "data": "..."}
        """
        import json as _json

        NEW_PROJECT_SYSTEM = (
            "You are a software architect helping a user plan a new project.\n"
            "Your job:\n"
            "1. Ask clarifying questions (tech stack, features, scale, deployment) — 3-5 messages max\n"
            "2. Once you have enough info, generate a complete project specification as a markdown document\n"
            "3. Format the spec inside a special marker:\n\n"
            "===SPEC_START===\n"
            "# Project Spec: {name}\n"
            "...full markdown spec...\n"
            "===SPEC_END===\n\n"
            "Keep the conversation focused. Be concise."
        )

        session = get_or_create_session(request.session_id, None)

        async def event_stream():
            try:
                # Build messages with custom system prompt
                messages = [{"role": "system", "content": NEW_PROJECT_SYSTEM}]
                for m in session.history:
                    messages.append({"role": m.role, "content": m.content})
                messages.append({"role": "user", "content": request.message})

                # Add user turn to session
                session.add("user", request.message)

                # Route model same as normal chat
                decision = _app_state.chat_engine.router.route(request.message)
                model = decision.primary_model

                full_response = ""
                async for chunk in _app_state.chat_engine.llm.stream(messages, model=model):
                    full_response += chunk
                    payload = _json.dumps({"type": "chunk", "data": chunk})
                    yield f"data: {payload}\n\n"

                # Save assistant response to session
                session.add("assistant", full_response)
                yield f"data: {_json.dumps({'type': 'done'})}\n\n"
            except Exception as exc:
                logger.error("new-project chat stream error: %s", exc)
                payload = _json.dumps({"type": "error", "data": str(exc)})
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    
    # ========================================================================
    # Validation & Suggestions
    # ========================================================================
    
    @app.post(
        "/api/validate",
        response_model=ValidationResponse,
        tags=["validation"],
        summary="Validate code",
    )
    async def validate_code(
        request: ValidationRequest,
        req: Request,
    ) -> ValidationResponse:
        """Validate code snippet
        
        Args:
            request: Validation request
            req: FastAPI request (for auth)
        
        Returns:
            Validation results with issues and suggestions
        """
        # Check auth/rate limits
        auth_middleware = get_auth_middleware()
        api_key, description = await auth_middleware(req)
        
        # Simplified validation
        issues = []
        if request.validate_syntax:
            # Basic syntax check (would use actual parser)
            pass
        
        return ValidationResponse(
            valid=True,
            issues=issues,
            suggestions=[
                "Consider using type hints for better code clarity"
            ],
        )
    
    @app.post(
        "/api/suggest",
        response_model=SuggestionResponse,
        tags=["suggestions"],
        summary="Suggest patterns",
    )
    async def suggest_patterns(
        request: SuggestionRequest,
        req: Request,
    ) -> SuggestionResponse:
        """Suggest design patterns for code
        
        Args:
            request: Code snippet for analysis
            req: FastAPI request (for auth)
        
        Returns:
            Suggested patterns with explanations
        """
        # Check auth/rate limits
        auth_middleware = get_auth_middleware()
        api_key, description = await auth_middleware(req)
        
        # Simplified suggestions
        suggestions = [
            PatternSuggestion(
                pattern_name="Factory",
                category="oop",
                description="Create objects without specifying exact classes",
                benefits=["Decouples creation logic", "Easy to extend"],
                example="class ObjectFactory:\n    def create(self, type): ...",
            )
        ]
        
        return SuggestionResponse(
            suggestions=suggestions,
            explanation="Based on your code structure, the Factory pattern could improve flexibility.",
        )
    
    # ========================================================================
    # Chat Endpoint (SSE streaming)
    # ========================================================================

    @app.post("/api/chat", tags=["chat"], summary="Chat with the LLM about the codebase")
    async def chat(request: ChatRequest):
        """
        Stream an LLM response grounded in project memory via RAG.

        Returns Server-Sent Events (text/event-stream).
        Each event is a JSON object: {"type": "chunk"|"done"|"error", "data": "..."}
        """
        import json

        # Auto-load persisted modules from disk if not already in memory
        if request.project_id and request.project_id not in _app_state.chat_engine._project_modules:
            modules_path = os.path.join("architect_memory", request.project_id, "modules.json")
            if os.path.exists(modules_path):
                try:
                    with open(modules_path) as _f:
                        stored = json.load(_f)
                    _app_state.chat_engine.update_project_context(request.project_id, stored)
                    logger.info("Chat: loaded %d modules from disk for %s", len(stored), request.project_id)
                except Exception as _e:
                    logger.warning("Chat: failed to load modules.json: %s", _e)

        session = get_or_create_session(request.session_id, request.project_id)

        # Check if analysis is still running for this project
        analysis_status = None
        if request.project_id:
            for job in _app_state.active_jobs.values():
                if job.get("project_id") == request.project_id and job.get("status") == "running":
                    analyzed = job.get("files_analyzed", 0)
                    total = job.get("total_files", 0)
                    analysis_status = f"Analysis in progress ({analyzed}/{total} files analyzed). Memory is incomplete — tell the user to wait for analysis to finish before asking questions."
                    break

        # Inject recent git context so agent knows what was recently changed
        import subprocess as _sp
        recent_changes = None
        project_path = _resolve_project_path(request.project_id) if request.project_id else None
        if project_path and os.path.isdir(os.path.join(project_path, ".git")):
            try:
                git_log = _sp.run(
                    ["git", "log", "--oneline", "-10"],
                    cwd=project_path, capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                git_status = _sp.run(
                    ["git", "status", "--short"],
                    cwd=project_path, capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                if git_log or git_status:
                    recent_changes = ""
                    if git_status:
                        recent_changes += f"Uncommitted changes:\n{git_status}\n\n"
                    if git_log:
                        recent_changes += f"Recent commits:\n{git_log}"
            except Exception:
                pass

        async def event_stream():
            try:
                # Explain Selection: bypass chat engine, use custom system prompt directly
                if request.system_override:
                    messages = [
                        {"role": "system", "content": request.system_override},
                        {"role": "user", "content": request.message},
                    ]
                    decision = _app_state.chat_engine.router.route(request.message)
                    async for chunk in _app_state.chat_engine.llm.stream(messages, model=decision.primary_model):
                        payload = json.dumps({"type": "chunk", "data": chunk})
                        yield f"data: {payload}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

                async for chunk in _app_state.chat_engine.stream_chat(
                    session, request.message,
                    analysis_status=analysis_status,
                    recent_changes=recent_changes,
                ):
                    payload = json.dumps({"type": "chunk", "data": chunk})
                    yield f"data: {payload}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except Exception as exc:
                logger.error("Chat stream error: %s", exc)
                payload = json.dumps({"type": "error", "data": str(exc)})
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ========================================================================
    # A2A (Agent-to-Agent) Endpoint
    # ========================================================================

    @app.post(
        "/api/a2a/query",
        response_model=A2AQueryResponse,
        tags=["a2a"],
        summary="Agent-to-agent structured query",
    )
    async def a2a_query(request: A2AQueryRequest) -> A2AQueryResponse:
        """
        Structured query endpoint for agent-to-agent communication.

        Another agent can POST a question and receive a structured JSON response
        with answer, confidence, sources, and relevant patterns.
        No authentication required, no streaming.
        """
        import json
        from ..llm.model_router import create_model_router

        session_id = f"a2a-{request.project_id or 'global'}"
        session = get_or_create_session(session_id, request.project_id)

        # Ensure project modules are loaded into chat engine context
        if request.project_id:
            _load_project_modules(request.project_id)

        # Prefix with query type so the LLM tailors its answer
        type_prefix = {
            "architecture": "Describe the architecture: ",
            "feasibility": "Assess the technical feasibility of: ",
            "pattern": "Identify and explain relevant design patterns for: ",
            "general": "",
        }.get(request.query_type, "")

        full_question = type_prefix + request.question

        # Non-streaming completion
        answer = await _app_state.chat_engine.complete_chat(session, full_question)

        # Extract confidence from context (heuristic)
        router = create_model_router()
        decision = router.route(request.question)

        # For feasibility queries, try to parse a score from the answer
        feasibility_score = None
        if request.query_type == "feasibility":
            import re
            m = re.search(r"\b(\d{1,3})\s*(?:/\s*100|%)", answer)
            if m:
                feasibility_score = min(float(m.group(1)) / 100.0, 1.0)

        return A2AQueryResponse(
            answer=answer,
            confidence=decision.confidence,
            sources=[],
            patterns_relevant=[],
            feasibility_score=feasibility_score,
            model_used=decision.primary_model,
            query_type=request.query_type,
        )

    @app.get("/api/a2a/schema", tags=["a2a"], summary="MCP-compatible schema")
    async def a2a_schema():
        """Return MCP-compatible schema for agent discovery."""
        from ..mcp import MCPServer
        server = MCPServer()
        return server.get_schema()

    # ========================================================================
    # Code Edit Agent Endpoints
    # ========================================================================

    def _load_project_modules(project_id: str) -> list:
        """Load project modules from disk or in-memory cache."""
        import json as _json
        if project_id in _app_state.chat_engine._project_modules:
            return _app_state.chat_engine._project_modules[project_id]
        modules_path = os.path.join("architect_memory", project_id, "modules.json")
        if os.path.exists(modules_path):
            try:
                with open(modules_path) as _f:
                    mods = _json.load(_f)
                _app_state.chat_engine.update_project_context(project_id, mods)
                return mods
            except Exception as _e:
                logger.warning("Could not load modules.json for %s: %s", project_id, _e)
        return []

    def _resolve_project_path(project_id: str) -> str:
        """Resolve absolute project path from job registry or modules.json."""
        # Check active_jobs first
        for job in _app_state.active_jobs.values():
            if job.get("project_id") == project_id:
                return job.get("project_path", "")
        # Fall back to a directory named after project_id under cwd
        candidate = os.path.join("architect_memory", project_id, "project_path.txt")
        if os.path.exists(candidate):
            with open(candidate) as _f:
                return _f.read().strip()
        return ""

    @app.post(
        "/api/a2a/generate",
        tags=["a2a"],
        summary="Generate / apply code changes via the edit agent",
    )
    async def generate_code(request: GenerateRequest):
        """
        Run the Code Edit Agent for a given task.

        - dry_run: returns proposed changes without writing to disk.
        - apply: writes changes immediately and returns results.
        - interactive: returns SSE stream with approval events.
        """
        import json as _json
        from .agent_runner import AgentRunner, AGENT_MODEL

        project_modules = _load_project_modules(request.project_id)
        project_path = _resolve_project_path(request.project_id)

        if not project_path:
            raise ValidationError(
                f"Project path not found for project_id '{request.project_id}'. "
                "Run an analysis first.",
                field="project_id",
            )

        if not project_modules and not request.force_generate:
            raise HTTPException(
                status_code=428,
                detail={
                    "error": "project_memory_empty",
                    "message": (
                        f"Project '{request.project_id}' has no architecture memory. "
                        "The agent cannot generate reliable code without it — "
                        "it will produce hardcoded/mock data instead of real implementations."
                    ),
                    "remediation": {
                        "step_1": {
                            "description": "Trigger analysis to build architecture memory",
                            "method": "POST",
                            "path": "/api/analyze",
                            "body": {
                                "project_id": request.project_id,
                                "project_path": project_path,
                            },
                        },
                        "step_2": {
                            "description": "Wait for analysis to complete (poll or listen to SSE)",
                            "method": "GET",
                            "path": f"/api/projects/{request.project_id}/freshness",
                        },
                        "step_3": {
                            "description": "Retry generate after analysis completes",
                            "method": "POST",
                            "path": "/api/a2a/generate",
                        },
                    },
                    "tip": (
                        "Alternatively, include explicit implementation details in your task "
                        "(e.g. 'use httpx to fetch from https://...', 'parse RSS with feedparser') "
                        "and set force_generate=true to bypass this check."
                    ),
                },
            )

        if request.mode == "interactive":
            session_id = str(uuid4())
            runner = AgentRunner(
                task=request.task,
                project_path=project_path,
                project_modules=project_modules,
                mode="interactive",
                context=request.context,
                session_id=session_id,
                chat_history=request.chat_history or [],
                shell_unrestricted=request.shell_unrestricted,
                auto_approve=request.auto_approve,
            )

            async def sse_stream():
                # Send session_id first so the client can use /api/agent/approve
                yield f"data: {_json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
                async for event in runner.run():
                    yield f"data: {_json.dumps(event.to_dict())}\n\n"

            return StreamingResponse(
                sse_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # dry_run or apply — collect all events and return JSON
        runner = AgentRunner(
            task=request.task,
            project_path=project_path,
            project_modules=project_modules,
            mode=request.mode,
            context=request.context,
            chat_history=request.chat_history or [],
            shell_unrestricted=request.shell_unrestricted,
            auto_approve=request.auto_approve,
        )

        explanation = ""
        async for event in runner.run():
            if event.type in ("message", "done") and event.content:
                explanation = event.content

        changes = [
            FileChangeSchema(
                file=c.file,
                action=c.action,
                content=c.content,
                diff=c.diff,
                applied=c.applied,
            )
            for c in runner.changes
        ]

        return GenerateResponse(
            changes=changes,
            plan=[],
            explanation=explanation,
            patterns_used=[],
            tests_suggested=[],
            applied=(request.mode == "apply"),
            model_used=AGENT_MODEL,
            session_id=None,
        )

    @app.post(
        "/api/a2a/validate",
        response_model=ValidateResponse,
        tags=["a2a"],
        summary="Validate proposed code changes against project patterns",
    )
    async def validate_changes(request: ValidateRequest) -> ValidateResponse:
        """
        Use the LLM to check whether proposed changes match project patterns
        and conventions.
        """
        from ..llm.model_router import create_model_router

        project_modules = _load_project_modules(request.project_id)
        session_id = f"validate-{request.project_id}-{uuid4()}"
        session = get_or_create_session(session_id, request.project_id)

        changes_summary = "\n".join(
            f"- {c.action} {c.file}" for c in request.changes
        )
        prompt = (
            "Review these proposed code changes and assess if they are consistent "
            "with the project's architecture and patterns.\n\n"
            f"Changes:\n{changes_summary}\n\n"
            "Respond in JSON with keys: valid (bool), confidence (0-1), "
            "issues (list[str]), warnings (list[str]), "
            "patterns_matched (list[str]), patterns_missing (list[str])."
        )

        answer = await _app_state.chat_engine.complete_chat(session, prompt)

        # Try to parse JSON from the answer
        import re as _re
        try:
            m = _re.search(r"\{.*\}", answer, _re.DOTALL)
            if m:
                data = _json_loads_safe(m.group(0))
                return ValidateResponse(**data)
        except Exception:
            pass

        # Fallback: optimistic response
        return ValidateResponse(
            valid=True,
            confidence=0.7,
            issues=[],
            warnings=["Could not parse LLM validation response"],
            patterns_matched=[],
            patterns_missing=[],
        )

    @app.post(
        "/api/a2a/impact",
        response_model=ImpactResponse,
        tags=["a2a"],
        summary="Analyse the impact of changing a set of files",
    )
    async def impact_analysis(request: ImpactRequest) -> ImpactResponse:
        """
        Use the LLM and project modules to estimate which files will be
        affected by the proposed change.
        """
        project_modules = _load_project_modules(request.project_id)
        session_id = f"impact-{request.project_id}-{uuid4()}"
        session = get_or_create_session(session_id, request.project_id)

        files_str = ", ".join(request.files)
        prompt = (
            f"Analyse the impact of the following change on the project:\n\n"
            f"Change: {request.change_description}\n"
            f"Files being modified: {files_str}\n\n"
            "List other files likely to be affected, explain the risk (low/medium/high), "
            "and give a recommendation.\n\n"
            "Respond in JSON: {affected_files: [{file, reason, risk}], "
            "risk: 'low'|'medium'|'high', confidence: 0-1, recommendation: str}"
        )

        answer = await _app_state.chat_engine.complete_chat(session, prompt)

        import re as _re
        try:
            m = _re.search(r"\{.*\}", answer, _re.DOTALL)
            if m:
                data = _json_loads_safe(m.group(0))
                return ImpactResponse(**data)
        except Exception:
            pass

        return ImpactResponse(
            affected_files=[],
            risk="low",
            confidence=0.5,
            recommendation=answer[:500] if answer else "No recommendation available.",
        )

    @app.post(
        "/api/a2a/scaffold",
        response_model=ScaffoldResponse,
        tags=["a2a"],
        summary="Scaffold a new project from a template",
    )
    async def scaffold_project(request: ScaffoldRequest) -> ScaffoldResponse:
        """
        Create a new project directory from a template and optionally trigger analysis.

        Templates:
          fastapi-minimal — main.py, requirements.txt, README, .gitignore, SOUL.md
          fastapi-full    — above + routers/ models/ services/ tests/
          python-lib      — src layout + pyproject.toml + tests/
          agent           — FastAPI + agent lifecycle skeleton
        """
        from .scaffold import create_project, VALID_TEMPLATES

        if request.template not in VALID_TEMPLATES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid template '{request.template}'. Valid: {', '.join(VALID_TEMPLATES)}",
            )

        try:
            result = create_project(
                project_path=request.project_path,
                template=request.template,
                project_name=request.project_name,
                git_init=request.options.git_init,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            logger.error("Scaffold failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Scaffold failed: {exc}")

        analysis_job_id: Optional[str] = None

        if request.options.auto_analyze:
            try:
                # Kick off background analysis using the same pipeline as /api/analyze
                job_id = str(uuid4())
                memory_dir = os.path.join("architect_memory", result.project_id)
                os.makedirs(memory_dir, exist_ok=True)
                with open(os.path.join(memory_dir, "project_path.txt"), "w") as _pf:
                    _pf.write(result.project_path)

                _app_state.active_jobs[job_id] = {
                    "status": "running",
                    "project_id": result.project_id,
                    "project_path": result.project_path,
                }

                async def _run_analysis(job_id: str, project_path: str, project_id: str) -> None:
                    try:
                        async def _noop_event(evt: AgentEvent) -> None:
                            pass
                        analyzer = create_llm_analyzer(on_event=_noop_event)
                        _mem_dir = os.path.join("architect_memory", project_id)
                        summary = await analyzer.analyze_project(project_path, memory_dir=_mem_dir)
                        _app_state.active_jobs[job_id]["status"] = "complete"
                        _app_state.active_jobs[job_id]["summary"] = summary
                    except Exception as _exc:
                        logger.error("Auto-analysis failed for scaffold job %s: %s", job_id, _exc)
                        _app_state.active_jobs[job_id]["status"] = "error"

                asyncio.create_task(_run_analysis(job_id, result.project_path, result.project_id))
                analysis_job_id = job_id
            except Exception as exc:
                logger.warning("Could not start auto-analysis after scaffold: %s", exc)

        return ScaffoldResponse(
            project_id=result.project_id,
            project_path=result.project_path,
            template_used=result.template,
            files_created=result.files_created,
            git_initialized=result.git_initialized,
            analysis_job_id=analysis_job_id,
        )

    @app.post(
        "/api/a2a/codegen",
        response_model=CodegenResponse,
        tags=["a2a"],
        summary="Generate a code component and write it into a project",
    )
    async def codegen_component(request: CodegenRequest) -> CodegenResponse:
        """
        Use the codegen template engine to generate a Pydantic model, FastAPI router,
        agent skeleton, or async pattern, and optionally write it to the project.

        template_type values: pydantic | fastapi | agent | async
        """
        from ..codegen import A2ACodegenAdapter, GenerateRequest as CgGenerateRequest
        from pathlib import Path as _Path

        valid_types = ("pydantic", "fastapi", "agent", "async")
        if request.template_type not in valid_types:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid template_type '{request.template_type}'. Valid: {', '.join(valid_types)}",
            )

        # Resolve project path from memory
        project_path: Optional[str] = None
        memory_dir = os.path.join("architect_memory", request.project_id)
        path_file = os.path.join(memory_dir, "project_path.txt")
        if os.path.isfile(path_file):
            with open(path_file) as _f:
                project_path = _f.read().strip()
        if not project_path or not os.path.isdir(project_path):
            raise HTTPException(
                status_code=404,
                detail=f"Project '{request.project_id}' not found. Scaffold or analyze it first.",
            )

        # Auto-infer output path if not provided
        output_path = request.output_path
        if not output_path:
            type_dirs = {
                "pydantic": "models",
                "fastapi": "routers",
                "agent": "agents",
                "async": "tasks",
            }
            safe_name = request.template_name.lower().replace(" ", "_")
            output_path = f"{type_dirs[request.template_type]}/{safe_name}.py"

        # Run codegen adapter
        adapter = A2ACodegenAdapter()
        cg_request = CgGenerateRequest(
            request_id=str(uuid4()),
            template_type=request.template_type,
            template_name=request.template_name,
            context=request.context,
        )

        try:
            cg_response = await adapter.handle_generate_request(cg_request)
        except Exception as exc:
            logger.error("Codegen failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Code generation failed: {exc}")

        if not cg_response.success:
            return CodegenResponse(
                success=False,
                errors=cg_response.errors,
                warnings=cg_response.warnings,
            )

        # Write to disk if requested
        if request.write_to_disk and cg_response.code:
            try:
                target = _Path(project_path) / output_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(cg_response.code, encoding="utf-8")
            except Exception as exc:
                return CodegenResponse(
                    success=False,
                    code=cg_response.code,
                    output_path=output_path,
                    errors=[f"Failed to write file: {exc}"],
                    warnings=cg_response.warnings or [],
                )

        return CodegenResponse(
            success=True,
            code=cg_response.code,
            output_path=output_path if request.write_to_disk else None,
            validation=cg_response.metadata or {},
            errors=cg_response.errors or [],
            warnings=cg_response.warnings or [],
        )

    @app.post(
        "/api/agent/approve",
        tags=["agent"],
        summary="Approve or reject a pending agent action",
    )
    async def approve_action(request: ApproveRequest) -> dict:
        """
        Signal the waiting AgentRunner to continue (apply/skip/stop/edit).
        Must be called while the SSE stream for the session is still open.
        """
        from .agent_runner import get_session as _get_session

        sess = _get_session(request.session_id)
        if sess is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{request.session_id}' not found or already complete.",
            )
        if request.action not in ("apply", "skip", "stop", "edit"):
            raise HTTPException(
                status_code=422,
                detail="action must be one of: apply, skip, stop, edit",
            )

        sess.approved_action = request.action
        sess.edited_content = request.edited_content
        sess.approval_event.set()

        return {"ok": True, "session_id": request.session_id, "action": request.action}

    @app.post(
        "/api/agent/approve-plan",
        tags=["agent"],
        summary="Approve or reject the execution plan",
    )
    async def approve_plan(request: ApprovePlanRequest) -> dict:
        from .agent_runner import get_session as _get_session
        sess = _get_session(request.session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found.")
        sess.plan_approved_action = request.action
        sess.plan_approval_event.set()
        return {"ok": True, "session_id": request.session_id, "action": request.action}

    @app.post(
        "/api/agent/escalate",
        tags=["agent"],
        summary="Respond to an escalation event",
    )
    async def handle_escalation(request: EscalationRequest) -> dict:
        from .agent_runner import get_session as _get_session
        sess = _get_session(request.session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found.")
        sess.escalation_action = request.action
        sess.escalation_instruction = request.instruction
        sess.escalation_event.set()
        return {"ok": True, "session_id": request.session_id, "action": request.action}

    @app.get(
        "/api/agent/sessions/{session_id}",
        tags=["agent"],
        summary="Get agent session status",
    )
    async def get_agent_session(session_id: str) -> dict:
        """Return current status of an agent session."""
        from .agent_runner import get_session as _get_session

        sess = _get_session(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        return {
            "session_id": sess.session_id,
            "status": sess.status,
            "pending_approval": sess.approval_event.is_set() is False and sess.status == "running",
        }

    @app.post(
        "/api/agent/sessions/{session_id}/stop",
        tags=["agent"],
        summary="Stop a running agent session",
    )
    async def stop_agent_session(session_id: str) -> dict:
        """Immediately stop a running agent session."""
        from .agent_runner import get_session as _get_session

        sess = _get_session(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        sess.status = "stopped"
        sess.approved_action = "stop"
        sess.approval_event.set()  # unblock any waiting approval
        return {"ok": True, "session_id": session_id}

    @app.post(
        "/api/agent/revert",
        tags=["agent"],
        summary="Revert a file to its most recent backup",
    )
    async def revert_file(request: RevertRequest) -> dict:
        """Restore a file from the .architect/backup/ directory (most recent snapshot)."""
        import shutil as _shutil
        from pathlib import Path as _Path

        project_path = os.path.abspath(os.path.expanduser(request.project_path))
        backup_dir = _Path(project_path) / ".architect" / "backup"
        if not backup_dir.exists():
            raise HTTPException(status_code=404, detail="No backup directory found for this project.")

        safe_name = str(_Path(request.file_path).as_posix()).replace("/", "__")
        candidates = sorted(backup_dir.glob(f"{safe_name}.*"), reverse=True)
        if not candidates:
            raise HTTPException(status_code=404, detail=f"No backup found for: {request.file_path}")

        latest_backup = candidates[0]
        target = _Path(project_path) / request.file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(latest_backup, target)
        return {"ok": True, "restored_from": str(latest_backup.name), "file": request.file_path}

    @app.post(
        "/api/agent/rollback-session",
        tags=["agent"],
        summary="Rollback all changes for a session by deleting the task git branch",
    )
    async def rollback_session(request: RollbackRequest) -> dict:
        """Restore to the base branch and delete the task branch created by the agent."""
        import subprocess as _sp
        from .agent_runner import get_session

        sess = get_session(request.session_id)
        if not sess:
            raise HTTPException(status_code=404, detail=f"Session not found: {request.session_id}")
        if not sess.git_base_branch or not sess.git_task_branch:
            raise HTTPException(status_code=400, detail="No git checkpoint found for this session.")

        # We need the project_path — try to find it from active runners in the session registry
        # The session doesn't store project_path, so we look it up via task_branch name (safe fallback)
        project_path = None
        # Try to find from environment or session metadata (best effort)
        from .agent_runner import _agent_sessions
        # Note: project_path is not stored in AgentSession; the caller should pass it.
        # Raise helpful error instead.
        raise HTTPException(
            status_code=400,
            detail="rollback-session requires project_path. Use /api/agent/rollback-session-v2 with project_path."
        )

    @app.post(
        "/api/agent/rollback-session-v2",
        tags=["agent"],
        summary="Rollback all changes — checkout base branch, delete task branch",
    )
    async def rollback_session_v2(
        session_id: str,
        project_path: str,
    ) -> dict:
        """Restore to the base branch and delete the task branch created by the agent."""
        import subprocess as _sp
        from .agent_runner import get_session

        sess = get_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        if not sess.git_base_branch or not sess.git_task_branch:
            raise HTTPException(status_code=400, detail="No git checkpoint found for this session.")

        project_path = os.path.abspath(os.path.expanduser(project_path))
        base = sess.git_base_branch
        task = sess.git_task_branch

        try:
            # Checkout base branch
            r1 = _sp.run(
                ["git", "checkout", base],
                cwd=project_path, capture_output=True, text=True, timeout=15,
            )
            if r1.returncode != 0:
                raise HTTPException(status_code=500, detail=f"git checkout failed: {r1.stderr.strip()}")

            # Delete task branch
            r2 = _sp.run(
                ["git", "branch", "-D", task],
                cwd=project_path, capture_output=True, text=True, timeout=10,
            )
            if r2.returncode != 0:
                logger.warning("Could not delete task branch %s: %s", task, r2.stderr.strip())

            # Restore pre-task stash if one was created
            if getattr(sess, "git_stash_created", False):
                stash_list = _sp.run(
                    ["git", "stash", "list"],
                    cwd=project_path, capture_output=True, text=True, timeout=5,
                )
                session_tag = session_id[:8]
                matching_stash = None
                for line in stash_list.stdout.splitlines():
                    if f"Architect pre-task backup {session_tag}" in line:
                        matching_stash = line.split(":")[0].strip()  # e.g. "stash@{0}"
                        break
                if matching_stash:
                    pop_result = _sp.run(
                        ["git", "stash", "pop", matching_stash],
                        cwd=project_path, capture_output=True, text=True, timeout=15,
                    )
                    if pop_result.returncode != 0:
                        logger.warning("Could not pop stash %s: %s", matching_stash, pop_result.stderr.strip())
                    else:
                        logger.info("Restored pre-task stash %s", matching_stash)

            # Clear session git state
            sess.git_base_branch = None
            sess.git_task_branch = None
            sess.git_stash_created = False

            return {"status": "rolled_back", "branch": base}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}") from exc

    # ========================================================================
    # File System Helpers (for GUI folder browser + pre-scan)
    # ========================================================================

    @app.get("/api/browse", tags=["filesystem"], summary="List directory contents")
    async def browse_directory(path: str = "/") -> dict:
        """Return immediate children of a directory for the folder picker."""
        from ..analysis.llm_analyzer import SKIP_DIRS
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(abs_path):
            raise ValidationError(f"Not a directory: {path}", field="path")
        entries = []
        try:
            for name in sorted(os.listdir(abs_path)):
                if name.startswith(".") or name in SKIP_DIRS:
                    continue
                full = os.path.join(abs_path, name)
                entries.append({"name": name, "path": full, "is_dir": os.path.isdir(full)})
        except PermissionError:
            pass
        parent = str(os.path.dirname(abs_path)) if abs_path != "/" else None
        return {"path": abs_path, "parent": parent, "entries": entries}

    @app.get("/api/scan", tags=["filesystem"], summary="Quick file count before analysis")
    async def scan_project(path: str) -> dict:
        """Scan a directory and return file counts without running LLM analysis."""
        from ..analysis.llm_analyzer import SKIP_DIRS, SKIP_FILES, SOURCE_EXTENSIONS
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(abs_path):
            raise ValidationError(f"Not a directory: {path}", field="path")
        total = 0
        analyzable = 0
        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                total += 1
                if f not in SKIP_FILES and os.path.splitext(f)[1].lower() in SOURCE_EXTENSIONS:
                    analyzable += 1
        return {"total_files": total, "analyzable_files": analyzable, "path": abs_path}

    @app.get("/api/memory/{project_id}", tags=["memory"], summary="Load persisted memory for a project")
    async def get_project_memory(project_id: str) -> dict:
        """Return saved modules and patterns for a project from disk."""
        import json as _json
        modules = _load_project_modules(project_id)
        patterns: list = []
        patterns_path = os.path.join("architect_memory", project_id, "patterns.json")
        if os.path.exists(patterns_path):
            try:
                patterns = _json.load(open(patterns_path))
            except Exception:
                pass
        return {"modules": modules, "patterns": patterns, "count": len(modules)}

    @app.get("/api/native-pick", tags=["filesystem"], summary="Open native OS folder picker")
    async def native_pick_folder() -> dict:
        """
        Trigger a native macOS Finder folder-picker dialog on the server.
        Returns the selected path, or null if the user cancelled.
        """
        import subprocess
        import sys

        if sys.platform != "darwin":
            raise HTTPException(status_code=501, detail="Native picker only supported on macOS")

        try:
            result = subprocess.run(
                ["osascript", "-e", "POSIX path of (choose folder)"],
                capture_output=True,
                text=True,
                timeout=120,  # user has 2 min to pick
            )
            if result.returncode == 0:
                chosen = result.stdout.strip()
                # osascript appends a trailing slash — normalise
                return {"path": chosen.rstrip("/")}
            else:
                # User pressed Cancel
                return {"path": None}
        except subprocess.TimeoutExpired:
            return {"path": None}
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="osascript not found")

    # ========================================================================
    # WebSocket Endpoint
    # ========================================================================
    
    @app.websocket("/ws/analyze/{job_id}")
    async def websocket_analyze(websocket: WebSocket, job_id: str):
        """WebSocket endpoint for real-time analysis updates
        
        Args:
            websocket: WebSocket connection
            job_id: Analysis job ID
        """
        client_id = str(uuid4())
        manager = get_connection_manager()
        
        await manager.connect(websocket, client_id)
        await manager.register_job(job_id, client_id)
        
        try:
            # Send initial message
            msg = WebSocketMessage(
                type="connected",
                job_id=job_id,
                data={"client_id": client_id},
            )
            await websocket.send_text(msg.to_json())
            
            # Receive messages
            async def on_message(cid, message):
                logger.info(f"Message from {cid}: {message.type}")
            
            await manager.receive_messages(websocket, client_id, on_message)
        
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        
        finally:
            await manager.unregister_job(job_id, client_id)
    
    # ========================================================================
    # File read / write endpoints
    # ========================================================================

    @app.get(
        "/api/file",
        tags=["files"],
        summary="Read a project file's content",
    )
    async def read_file(path: str, project_id: str) -> dict:
        """
        Returns the full text content of a file.
        `path` must be an absolute path that lives inside the project root.
        Binary files are rejected with a 415 error.
        """
        import mimetypes as _mt

        # Resolve project root from memory dir
        memory_dir = os.path.join("architect_memory", project_id)
        project_path: Optional[str] = None
        path_file = os.path.join(memory_dir, "project_path.txt")
        if os.path.isfile(path_file):
            project_path = open(path_file).read().strip()

        # Resolve relative paths against the project root
        if project_path and not os.path.isabs(path):
            path = os.path.join(project_path, path)

        # Security: path must be within the project root
        abs_path = os.path.realpath(path)
        if project_path:
            real_root = os.path.realpath(project_path)
            if not abs_path.startswith(real_root + os.sep) and abs_path != real_root:
                raise HTTPException(status_code=403, detail="Path is outside project root")

        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        # Reject binary files
        mime, _ = _mt.guess_type(abs_path)
        binary_exts = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff',
                       '.woff2', '.ttf', '.eot', '.pdf', '.zip', '.tar', '.gz',
                       '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe'}
        ext = os.path.splitext(abs_path)[1].lower()
        if ext in binary_exts:
            raise HTTPException(status_code=415, detail="Binary file — cannot display as text")

        try:
            content = open(abs_path, encoding='utf-8', errors='replace').read()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        return {"path": path, "content": content}

    @app.post(
        "/api/file",
        tags=["files"],
        summary="Write content back to a project file",
    )
    async def write_file(body: dict) -> dict:
        """
        Saves edited file content to disk.
        Body: { "path": "...", "content": "...", "project_id": "..." }
        """
        path = body.get("path", "")
        content = body.get("content", "")
        project_id = body.get("project_id", "")

        if not path:
            raise HTTPException(status_code=400, detail="path is required")

        # Resolve project root for security check
        memory_dir = os.path.join("architect_memory", project_id)
        project_path: Optional[str] = None
        path_file = os.path.join(memory_dir, "project_path.txt")
        if os.path.isfile(path_file):
            project_path = open(path_file).read().strip()

        if project_path and not os.path.isabs(path):
            path = os.path.join(project_path, path)

        abs_path = os.path.realpath(path)
        if project_path:
            real_root = os.path.realpath(project_path)
            if not abs_path.startswith(real_root + os.sep) and abs_path != real_root:
                raise HTTPException(status_code=403, detail="Path is outside project root")

        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        try:
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        return {"saved": True, "path": path}

    # ========================================================================
    # Error Handlers
    # ========================================================================
    
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        """Handle API errors
        
        Args:
            request: HTTP request
            exc: API error
        
        Returns:
            JSON error response
        """
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=exc.error_code,
                detail=exc.detail,
                context=exc.context,
                timestamp=datetime.utcnow(),
            ).model_dump(mode="json"),
        )
    
    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        """Handle unexpected errors
        
        Args:
            request: HTTP request
            exc: Exception
        
        Returns:
            JSON error response
        """
        logger.error(f"Unhandled error: {exc}")
        error = InternalError("Internal server error", exception=exc)
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                error_code=error.error_code,
                detail=error.detail,
                context=error.context,
                timestamp=datetime.utcnow(),
            ).model_dump(mode="json"),
        )
    
    return app


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _json_loads_safe(s: str) -> dict:
    """Load JSON, converting Python-style booleans / None if needed."""
    import json as _json
    try:
        return _json.loads(s)
    except Exception:
        fixed = s.replace("True", "true").replace("False", "false").replace("None", "null")
        return _json.loads(fixed)


# Create default application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "architect.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
