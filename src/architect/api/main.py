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
    ApproveRequest,
    ApprovePlanRequest,
    EscalationRequest,
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
        response_model=ProjectListResponse,
        tags=["projects"],
        summary="List projects",
    )
    async def list_projects(req: Request) -> ProjectListResponse:
        """List all analyzed projects
        
        Args:
            req: FastAPI request (for auth)
        
        Returns:
            List of projects with metadata
        """
        # Check auth/rate limits
        auth_middleware = get_auth_middleware()
        api_key, description = await auth_middleware(req)
        
        # Simplified - would use actual project manager
        projects = [
            ProjectInfo(
                project_id="project-1",
                project_path="/path/to/project1",
                created_at=datetime.utcnow() - timedelta(days=1),
                last_analyzed=datetime.utcnow(),
                languages=["python", "javascript"],
                file_count=150,
                pattern_count=8,
            )
        ]
        
        return ProjectListResponse(
            projects=projects,
            total_count=len(projects),
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

        async def event_stream():
            try:
                async for chunk in _app_state.chat_engine.stream_chat(
                    session, request.message
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

        if request.mode == "interactive":
            session_id = str(uuid4())
            runner = AgentRunner(
                task=request.task,
                project_path=project_path,
                project_modules=project_modules,
                mode="interactive",
                context=request.context,
                session_id=session_id,
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
        from ..analysis.llm_analyzer import SKIP_DIRS, SOURCE_EXTENSIONS
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(abs_path):
            raise ValidationError(f"Not a directory: {path}", field="path")
        total = 0
        analyzable = 0
        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                total += 1
                if os.path.splitext(f)[1].lower() in SOURCE_EXTENSIONS:
                    analyzable += 1
        return {"total_files": total, "analyzable_files": analyzable, "path": abs_path}

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
