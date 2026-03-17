"""
Request and response schemas for Code Architect API

Defines Pydantic models for all API endpoints.

Version: 1.0
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================================
# Common Response Models
# ============================================================================

class HealthStatus(BaseModel):
    """Health check response
    
    Attributes:
        status: "healthy" or "unhealthy"
        timestamp: Current server timestamp
        version: API version
        uptime_seconds: Server uptime
    """
    status: str = Field(description="Health status")
    timestamp: datetime = Field(description="Current timestamp")
    version: str = Field(description="API version")
    uptime_seconds: float = Field(description="Server uptime in seconds")


class ErrorResponse(BaseModel):
    """Error response format
    
    Attributes:
        error_code: Application-specific error code
        detail: Error message
        context: Additional context/debugging info
    """
    error_code: str = Field(description="Error code")
    detail: str = Field(description="Error message")
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context"
    )
    timestamp: datetime = Field(description="Error timestamp")


# ============================================================================
# Analysis Endpoints
# ============================================================================

class AnalysisRequest(BaseModel):
    """Request for project analysis
    
    Attributes:
        project_path: Path to project directory
        project_id: Optional unique project identifier
        languages: List of supported languages to analyze
        include_patterns: Whether to detect patterns (default: true)
        include_search: Whether to enable search indexing (default: true)
        sample_ratio: For large projects, sample ratio (0.0-1.0, default: 1.0)
    """
    project_path: str = Field(
        description="Path to project directory",
        min_length=1,
    )
    project_id: Optional[str] = Field(
        None,
        description="Project identifier (auto-generated if not provided)"
    )
    languages: Optional[List[str]] = Field(
        None,
        description="Languages to analyze (auto-detected if not provided)"
    )
    include_patterns: bool = Field(
        True,
        description="Detect architectural patterns"
    )
    include_search: bool = Field(
        True,
        description="Enable search indexing"
    )
    sample_ratio: float = Field(
        1.0,
        ge=0.1,
        le=1.0,
        description="Sampling ratio for large projects"
    )


class AnalysisProgress(BaseModel):
    """Progress update for ongoing analysis
    
    Attributes:
        job_id: Analysis job ID
        status: Current status (queued, analyzing, embedding, indexing, complete, failed)
        progress_percent: Progress 0-100
        files_processed: Number of files processed
        files_total: Total files to process
        current_step: Current processing step
        eta_seconds: Estimated time remaining
    """
    job_id: str = Field(description="Analysis job ID")
    status: str = Field(description="Current status")
    progress_percent: int = Field(ge=0, le=100, description="Progress %")
    files_processed: int = Field(ge=0, description="Files processed")
    files_total: int = Field(ge=0, description="Total files")
    current_step: str = Field(description="Current processing step")
    eta_seconds: Optional[float] = Field(None, description="Time remaining")


class PatternMatch(BaseModel):
    """Detected architectural pattern
    
    Attributes:
        name: Pattern name
        category: Pattern category
        confidence: Confidence score (0.0-1.0)
        evidence_count: Number of evidence locations
        locations: List of file locations with line numbers
    """
    name: str = Field(description="Pattern name")
    category: str = Field(description="Pattern category")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    evidence_count: int = Field(ge=0, description="Number of evidence items")
    locations: List[Dict[str, Any]] = Field(
        description="Evidence locations (file, start_line, end_line)"
    )


class AnalysisResult(BaseModel):
    """Project analysis result
    
    Attributes:
        job_id: Analysis job ID
        project_id: Project identifier
        project_path: Path to analyzed project
        status: Analysis status
        patterns_detected: List of detected patterns
        total_files: Total files analyzed
        supported_languages: Languages found in project
        analysis_time_seconds: Time taken for analysis
        timestamp: Analysis timestamp
    """
    job_id: str = Field(description="Analysis job ID")
    project_id: str = Field(description="Project ID")
    project_path: str = Field(description="Project path")
    status: str = Field(description="Analysis status")
    patterns_detected: List[PatternMatch] = Field(
        default_factory=list,
        description="Detected patterns"
    )
    total_files: int = Field(ge=0, description="Total files analyzed")
    supported_languages: List[str] = Field(
        default_factory=list,
        description="Languages found"
    )
    analysis_time_seconds: float = Field(
        description="Analysis duration"
    )
    timestamp: datetime = Field(description="Completion timestamp")


# ============================================================================
# Search Endpoints
# ============================================================================

class SearchRequest(BaseModel):
    """Request for semantic search
    
    Attributes:
        query: Search query
        project_id: Project to search in
        top_k: Number of results to return (default: 5)
        include_patterns: Include pattern matches (default: true)
        confidence_threshold: Minimum confidence (0.0-1.0, default: 0.5)
    """
    query: str = Field(
        description="Search query",
        min_length=1,
    )
    project_id: Optional[str] = Field(
        None,
        description="Project to search (searches all if not specified)"
    )
    top_k: int = Field(
        5,
        ge=1,
        le=50,
        description="Number of results"
    )
    include_patterns: bool = Field(
        True,
        description="Include pattern results"
    )
    confidence_threshold: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence"
    )


class SearchResult(BaseModel):
    """Search result item
    
    Attributes:
        id: Result ID
        type: Result type (pattern, code, documentation)
        title: Result title
        content: Result content
        confidence: Confidence score
        location: Location info (file, line)
        source: Source identifier
    """
    id: str = Field(description="Result ID")
    type: str = Field(description="Result type")
    title: str = Field(description="Result title")
    content: str = Field(description="Result content")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence")
    location: Optional[Dict[str, Any]] = Field(
        None,
        description="Location info"
    )
    source: str = Field(description="Source identifier")


class SearchResponse(BaseModel):
    """Search response
    
    Attributes:
        query: Original query
        results: List of search results
        total_results: Total number of results found
        execution_time_ms: Query execution time
    """
    query: str = Field(description="Original query")
    results: List[SearchResult] = Field(description="Search results")
    total_results: int = Field(ge=0, description="Total results")
    execution_time_ms: float = Field(description="Query time in milliseconds")


# ============================================================================
# Project Management
# ============================================================================

class ProjectInfo(BaseModel):
    """Project information
    
    Attributes:
        project_id: Unique project ID
        project_path: Project path
        created_at: Creation timestamp
        last_analyzed: Last analysis timestamp
        languages: Supported languages
        file_count: Total files
        pattern_count: Number of patterns detected
    """
    project_id: str = Field(description="Project ID")
    project_path: str = Field(description="Project path")
    created_at: datetime = Field(description="Creation time")
    last_analyzed: Optional[datetime] = Field(
        None,
        description="Last analysis time"
    )
    languages: List[str] = Field(
        default_factory=list,
        description="Supported languages"
    )
    file_count: int = Field(ge=0, description="File count")
    pattern_count: int = Field(ge=0, description="Pattern count")


class ProjectListResponse(BaseModel):
    """List of projects
    
    Attributes:
        projects: List of project info
        total_count: Total number of projects
    """
    projects: List[ProjectInfo] = Field(description="Projects")
    total_count: int = Field(ge=0, description="Total count")


# ============================================================================
# Validation & Suggestion
# ============================================================================

class ValidationRequest(BaseModel):
    """Request for code validation
    
    Attributes:
        code: Code snippet to validate
        language: Programming language
        validate_syntax: Check syntax (default: true)
        validate_patterns: Check for anti-patterns (default: true)
    """
    code: str = Field(
        description="Code snippet",
        min_length=1,
    )
    language: str = Field(
        description="Programming language"
    )
    validate_syntax: bool = Field(
        True,
        description="Validate syntax"
    )
    validate_patterns: bool = Field(
        True,
        description="Check for anti-patterns"
    )


class ValidationIssue(BaseModel):
    """Validation issue
    
    Attributes:
        type: Issue type (syntax, pattern, warning)
        message: Issue message
        line: Line number
        column: Column number
        severity: Issue severity (info, warning, error)
    """
    type: str = Field(description="Issue type")
    message: str = Field(description="Issue message")
    line: int = Field(ge=1, description="Line number")
    column: int = Field(ge=1, description="Column number")
    severity: str = Field(description="Severity level")


class ValidationResponse(BaseModel):
    """Validation result
    
    Attributes:
        valid: Whether code is valid
        issues: List of detected issues
        suggestions: Improvement suggestions
    """
    valid: bool = Field(description="Is code valid")
    issues: List[ValidationIssue] = Field(
        default_factory=list,
        description="Detected issues"
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Suggestions"
    )


class SuggestionRequest(BaseModel):
    """Request for pattern suggestions
    
    Attributes:
        code_snippet: Code to analyze
        language: Programming language
        context: Optional context about the code
    """
    code_snippet: str = Field(
        description="Code snippet",
        min_length=1,
    )
    language: str = Field(
        description="Programming language"
    )
    context: Optional[str] = Field(
        None,
        description="Code context"
    )


class PatternSuggestion(BaseModel):
    """Pattern suggestion for code
    
    Attributes:
        pattern_name: Suggested pattern name
        category: Pattern category
        description: Pattern description
        benefits: Why this pattern would help
        example: Code example showing the pattern
    """
    pattern_name: str = Field(description="Pattern name")
    category: str = Field(description="Pattern category")
    description: str = Field(description="Pattern description")
    benefits: List[str] = Field(description="Benefits")
    example: str = Field(description="Code example")


class SuggestionResponse(BaseModel):
    """Pattern suggestion response

    Attributes:
        suggestions: List of suggested patterns
        explanation: Explanation of suggestions
    """
    suggestions: List[PatternSuggestion] = Field(
        description="Pattern suggestions"
    )
    explanation: str = Field(description="Explanation")


# ============================================================================
# Chat Endpoint
# ============================================================================

class ChatRequest(BaseModel):
    """Chat message request.

    Attributes:
        message: User's question or message.
        project_id: Project context for RAG retrieval.
        session_id: Conversation session ID (auto-generated client-side).
        model: Override LLM model (OpenRouter model ID).
    """
    message: str = Field(description="User message", min_length=1)
    project_id: Optional[str] = Field(None, description="Project context")
    session_id: str = Field(description="Conversation session ID")
    model: Optional[str] = Field(None, description="Override LLM model")


# ============================================================================
# A2A (Agent-to-Agent) Endpoint
# ============================================================================

class A2AQueryRequest(BaseModel):
    """Structured query from another agent.

    Attributes:
        question: The question to answer.
        project_id: Project to query against.
        query_type: Type of query — architecture | feasibility | pattern | general.
        context: Optional extra context from the calling agent.
    """
    question: str = Field(description="Question to answer", min_length=1)
    project_id: Optional[str] = Field(None, description="Project context")
    query_type: str = Field(
        "general",
        description="Query type: architecture | feasibility | pattern | general",
    )
    context: Optional[Dict[str, Any]] = Field(
        None,
        description="Extra context from calling agent",
    )


class A2AQueryResponse(BaseModel):
    """Structured response to an agent query.

    Attributes:
        answer: LLM-generated answer.
        confidence: Estimated answer confidence (0-1).
        sources: Source references from memory.
        patterns_relevant: Pattern names referenced in the answer.
        feasibility_score: For feasibility queries, 0-1 score.
        model_used: Which LLM model generated the answer.
    """
    answer: str = Field(description="Generated answer")
    confidence: float = Field(ge=0.0, le=1.0, description="Answer confidence")
    sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Source references",
    )
    patterns_relevant: List[str] = Field(
        default_factory=list,
        description="Relevant pattern names",
    )
    feasibility_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Feasibility score (feasibility queries only)",
    )
    model_used: str = Field(description="LLM model used")
    query_type: str = Field(description="Query type echoed back")
