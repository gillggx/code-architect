"""
Pydantic data models for Code Architect Agent Phase 2

Defines all request/response schemas, pattern structures, and data containers.
Fully compatible with JSON serialization for API and MCP integration.

Version: 2.0
"""

from typing import Dict, List, Optional, Literal, Any, Set, Tuple
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator
import json


# ============================================================================
# Enumerations
# ============================================================================

class ConfidenceLevelEnum(str, Enum):
    """Confidence level categories"""
    VERY_LOW = "very_low"      # 0.0-0.2
    LOW = "low"                # 0.2-0.4
    MODERATE = "moderate"      # 0.4-0.6
    HIGH = "high"              # 0.6-0.8
    VERY_HIGH = "very_high"    # 0.8-1.0


class PatternCategoryEnum(str, Enum):
    """Architectural pattern categories"""
    OOP = "oop"                          # Object-oriented patterns
    BEHAVIORAL = "behavioral"            # Behavioral patterns
    STRUCTURAL = "structural"            # Structural patterns
    ARCHITECTURAL = "architectural"      # Architectural patterns
    ASYNC_CONCURRENCY = "async_concurrency"  # Async/concurrency patterns
    ERROR_HANDLING = "error_handling"    # Error handling patterns
    DATA_PERSISTENCE = "data_persistence"    # Data access patterns


class RiskLevelEnum(str, Enum):
    """Risk/severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QueryComplexityEnum(str, Enum):
    """Query complexity classification"""
    SIMPLE = "simple"          # Single clause, fast answer
    MODERATE = "moderate"      # Multi-clause, explanation needed
    COMPLEX = "complex"        # Design questions, trade-offs


class AnalysisStatusEnum(str, Enum):
    """Analysis job status"""
    QUEUED = "queued"
    ANALYZING = "analyzing"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETE = "complete"
    FAILED = "failed"


# ============================================================================
# Confidence & Scoring
# ============================================================================

class ConfidenceScore(BaseModel):
    """Confidence score with reasoning"""
    value: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score (0.0-1.0)"
    )
    evidence_count: int = Field(
        ge=0,
        description="Number of evidence samples"
    )
    evidence_quality: Literal["no_evidence", "weak", "moderate", "strong"] = (
        Field(description="Quality of evidence")
    )
    sources: List[str] = Field(
        default_factory=list,
        description="Evidence sources (file paths)"
    )
    
    @property
    def level(self) -> ConfidenceLevelEnum:
        """Get confidence level category"""
        if self.value < 0.2:
            return ConfidenceLevelEnum.VERY_LOW
        elif self.value < 0.4:
            return ConfidenceLevelEnum.LOW
        elif self.value < 0.6:
            return ConfidenceLevelEnum.MODERATE
        elif self.value < 0.8:
            return ConfidenceLevelEnum.HIGH
        else:
            return ConfidenceLevelEnum.VERY_HIGH
    
    @staticmethod
    def from_evidence_count(count: int) -> "ConfidenceScore":
        """Create confidence score from evidence count"""
        if count == 0:
            value = 0.0
            quality = "no_evidence"
        elif count == 1:
            value = 0.65
            quality = "weak"
        elif count <= 3:
            value = 0.80
            quality = "moderate"
        else:
            value = min(0.95, 0.80 + (count - 3) * 0.03)
            quality = "strong"
        
        return ConfidenceScore(
            value=value,
            evidence_count=count,
            evidence_quality=quality
        )


# ============================================================================
# Pattern Evidence & Detection
# ============================================================================

class PatternEvidence(BaseModel):
    """Evidence for a detected pattern"""
    file_path: str = Field(description="File containing evidence")
    start_line: int = Field(ge=1, description="Starting line number")
    end_line: int = Field(ge=1, description="Ending line number")
    code_snippet: str = Field(description="Actual code from file")
    confidence: float = Field(ge=0.0, le=1.0, description="Evidence confidence")
    explanation: Optional[str] = Field(
        None, description="Why this is evidence"
    )
    
    @property
    def line_range(self) -> Tuple[int, int]:
        """Get line range tuple"""
        return (self.start_line, self.end_line)
    
    @field_validator('end_line')
    @classmethod
    def end_after_start(cls, v, info):
        """Validate end_line > start_line"""
        if 'start_line' in info.data and v < info.data['start_line']:
            raise ValueError("end_line must be >= start_line")
        return v


class Pattern(BaseModel):
    """Detected architectural pattern"""
    id: str = Field(description="Unique pattern instance ID")
    name: str = Field(description="Pattern name (e.g., 'Singleton')")
    language: str = Field(description="Language (python, cpp, java, etc)")
    category: PatternCategoryEnum = Field(description="Pattern category")
    
    # Evidence
    evidence: List[PatternEvidence] = Field(
        description="Code evidence for pattern"
    )
    confidence: ConfidenceScore = Field(
        description="Confidence score with reasoning"
    )
    
    # Documentation
    description: str = Field(
        description="What this pattern does"
    )
    benefits: List[str] = Field(
        default_factory=list,
        description="Why this pattern is good"
    )
    trade_offs: List[str] = Field(
        default_factory=list,
        description="Drawbacks of this pattern"
    )
    
    # Implementation locations (file paths where pattern was found)
    implementations: List[str] = Field(
        default_factory=list,
        description="File paths where this pattern was detected"
    )

    # Alternatives
    alternative_patterns: List[str] = Field(
        default_factory=list,
        description="Other patterns that could be used"
    )
    
    # Verification
    verified: bool = Field(
        default=False,
        description="Manually verified"
    )
    verification_notes: Optional[str] = Field(
        None,
        description="Verification comments"
    )
    
    # Timestamps
    detected_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When pattern was detected"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": "pattern_001",
            "name": "Singleton",
            "language": "python",
            "category": "oop",
            "evidence": [{
                "file_path": "src/database.py",
                "start_line": 10,
                "end_line": 25,
                "code_snippet": "class Database:\n    _instance = None\n    def __new__(cls):\n        if cls._instance is None:\n            cls._instance = super().__new__(cls)\n        return cls._instance",
                "confidence": 0.95,
                "explanation": "Uses __new__ to implement singleton pattern"
            }],
            "confidence": {
                "value": 0.95,
                "evidence_count": 1,
                "evidence_quality": "strong",
                "sources": ["src/database.py"]
            },
            "description": "Ensures only one instance of a class exists",
            "benefits": ["Centralized resource management", "Lazy initialization"],
            "trade_offs": ["Harder to test", "Global state"],
            "alternative_patterns": ["Module-level singleton", "Class variables"]
        }
    })


# ============================================================================
# RAG / Search Components
# ============================================================================

class Chunk(BaseModel):
    """Markdown chunk for RAG"""
    id: str = Field(description="Unique chunk ID")
    text: str = Field(description="Chunk content")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata (source, section, etc)"
    )
    tokens: int = Field(ge=1, description="Approximate token count")
    embedding: Optional[List[float]] = Field(
        None,
        description="Vector embedding (if embedded)"
    )


class SearchResult(BaseModel):
    """Result from RAG search"""
    chunk: Chunk = Field(description="Retrieved chunk")
    relevance_score: float = Field(
        ge=0.0, le=1.0,
        description="Relevance score (0-1)"
    )
    source_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence of source content"
    )
    search_method: Literal["bm25", "vector", "hybrid"] = Field(
        description="Which search method found this"
    )
    explanation: Optional[str] = Field(
        None,
        description="Why this result matched"
    )
    
    @property
    def confidence(self) -> float:
        """Combined confidence score"""
        return (0.4 * self.relevance_score) + (0.6 * self.source_confidence)


# ============================================================================
# Analysis Job & Progress
# ============================================================================

class AnalysisProgress(BaseModel):
    """Analysis job progress update"""
    job_id: str = Field(description="Job identifier")
    status: AnalysisStatusEnum = Field(description="Current status")
    percentage: int = Field(ge=0, le=100, description="Progress percentage")
    current_phase: str = Field(description="Current analysis phase")
    current_file: Optional[str] = Field(None, description="File being processed")
    files_processed: int = Field(ge=0, description="Files analyzed so far")
    total_files: int = Field(ge=1, description="Total files to analyze")
    eta_seconds: Optional[int] = Field(None, description="Estimated seconds remaining")
    message: Optional[str] = Field(None, description="Status message")
    
    @property
    def progress_fraction(self) -> float:
        """Progress as fraction 0-1"""
        return self.percentage / 100.0


class AnalysisJob(BaseModel):
    """Submitted analysis job"""
    job_id: str = Field(description="Job identifier")
    project_id: str = Field(description="Project being analyzed")
    project_path: str = Field(description="Path to project root")
    languages: List[str] = Field(
        description="Languages to analyze"
    )
    status: AnalysisStatusEnum = Field(
        default=AnalysisStatusEnum.QUEUED,
        description="Current status"
    )
    submitted_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When job was submitted"
    )
    started_at: Optional[datetime] = Field(None, description="When analysis started")
    completed_at: Optional[datetime] = Field(None, description="When analysis completed")


class AnalysisResult(BaseModel):
    """Completed analysis result"""
    job_id: str = Field(description="Job ID")
    status: AnalysisStatusEnum = Field(description="Final status")
    
    # Detected patterns
    patterns: List[Pattern] = Field(
        default_factory=list,
        description="Detected patterns"
    )
    
    # Statistics
    total_files_analyzed: int = Field(description="Total files processed")
    files_per_language: Dict[str, int] = Field(
        default_factory=dict,
        description="File count by language"
    )
    total_lines_of_code: int = Field(
        default=0,
        description="Total lines analyzed"
    )
    
    # Quality metrics
    average_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Average pattern confidence"
    )
    patterns_by_confidence: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of patterns by confidence level"
    )
    
    # Timing
    analysis_duration_seconds: float = Field(
        description="Total analysis time"
    )
    
    # Errors
    errors: List[str] = Field(
        default_factory=list,
        description="Analysis errors encountered"
    )


# ============================================================================
# Query & Response
# ============================================================================

class QueryRequest(BaseModel):
    """User query request"""
    query: str = Field(min_length=1, description="User question")
    project_id: str = Field(description="Project to query")
    confidence_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0,
        description="Min confidence for results"
    )
    max_results: int = Field(
        default=5, ge=1, le=20,
        description="Maximum results to return"
    )
    complexity_hint: Optional[QueryComplexityEnum] = Field(
        None,
        description="Query complexity (auto-detected if omitted)"
    )
    include_edge_cases: bool = Field(
        default=True,
        description="Include edge case information"
    )
    include_alternatives: bool = Field(
        default=True,
        description="Include alternative patterns"
    )


class QueryResponse(BaseModel):
    """Response to user query"""
    query_id: str = Field(description="Query ID")
    query: str = Field(description="Original query")
    complexity: QueryComplexityEnum = Field(description="Detected complexity")
    
    # Answer
    answer: str = Field(description="Direct answer to question")
    confidence: ConfidenceScore = Field(description="Overall confidence")
    
    # Sources
    sources: List[SearchResult] = Field(
        default_factory=list,
        description="Retrieved sources"
    )
    patterns_mentioned: List[Pattern] = Field(
        default_factory=list,
        description="Patterns relevant to answer"
    )
    
    # Additional info
    edge_cases: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Known edge cases"
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternative approaches"
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Known limitations"
    )
    
    # Metadata
    latency_ms: int = Field(description="Response latency")
    source: Literal["memory", "analysis"] = Field(
        description="Where answer came from"
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When response was generated"
    )


# ============================================================================
# WebSocket Messages
# ============================================================================

class WebSocketMessage(BaseModel):
    """WebSocket message frame"""
    type: Literal[
        "progress", "complete", "error", "query_response", "notification"
    ] = Field(description="Message type")
    payload: Dict[str, Any] = Field(description="Message payload")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Message timestamp"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "type": "progress",
                    "payload": {
                        "job_id": "job_123",
                        "percentage": 45,
                        "current_file": "src/auth.py",
                        "message": "Analyzing Python files"
                    }
                },
                {
                    "type": "complete",
                    "payload": {
                        "job_id": "job_123",
                        "patterns_found": 12,
                        "avg_confidence": 0.87
                    }
                }
            ]
        }


# ============================================================================
# Edge Cases & Robustness
# ============================================================================

class EdgeCase(BaseModel):
    """Known edge case or boundary condition"""
    id: str = Field(description="Edge case ID")
    description: str = Field(description="What the edge case is")
    scenario: str = Field(description="How to trigger it")
    impact: str = Field(description="What happens")
    handling: str = Field(description="How it's handled")
    risk_level: RiskLevelEnum = Field(description="Severity")
    affected_patterns: List[str] = Field(
        default_factory=list,
        description="Patterns that exhibit this edge case"
    )
    mitigation: Optional[str] = Field(
        None,
        description="How to mitigate"
    )


class Decision(BaseModel):
    """Architectural decision"""
    id: str = Field(description="Decision ID")
    title: str = Field(description="Decision title")
    context: str = Field(description="Why it was needed")
    decision: str = Field(description="What was decided")
    rationale: str = Field(description="Why this choice")
    alternatives: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Other options considered"
    )
    consequences: List[str] = Field(
        default_factory=list,
        description="Trade-offs and effects"
    )
    status: Literal["proposed", "approved", "superseded"] = Field(
        description="Decision status"
    )
    made_at: datetime = Field(description="When decision was made")


# ============================================================================
# Agent API
# ============================================================================

class ValidationRequest(BaseModel):
    """Request to validate code against patterns"""
    code: str = Field(description="Code to validate")
    language: str = Field(description="Programming language")
    patterns_to_check: Optional[List[str]] = Field(
        None,
        description="Patterns to specifically check (all if omitted)"
    )


class ValidationResponse(BaseModel):
    """Validation results"""
    valid: bool = Field(description="Is code valid per patterns")
    matches: List[Pattern] = Field(
        default_factory=list,
        description="Matching patterns"
    )
    violations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Pattern violations"
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Improvement suggestions"
    )


class SuggestionRequest(BaseModel):
    """Request pattern suggestions"""
    code: str = Field(description="Code to analyze")
    language: str = Field(description="Programming language")
    context: Optional[str] = Field(None, description="Additional context")


class SuggestionResponse(BaseModel):
    """Pattern suggestions"""
    suggested_patterns: List[Pattern] = Field(
        description="Suggested patterns"
    )
    reasoning: Dict[str, str] = Field(
        description="Why each pattern is suggested"
    )
    implementation_tips: List[str] = Field(
        default_factory=list,
        description="Tips for implementation"
    )


# ============================================================================
# Health & Status
# ============================================================================

class HealthStatus(BaseModel):
    """Service health status"""
    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        description="Overall health"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow
    )
    version: str = Field(description="API version")
    
    # Component status
    memory_available: bool = Field(description="Memory system operational")
    rag_available: bool = Field(description="RAG system operational")
    parsers_available: bool = Field(description="Code parsers available")
    
    # Metrics
    memory_usage_mb: int = Field(description="Memory usage in MB")
    pending_jobs: int = Field(ge=0, description="Pending analysis jobs")
    uptime_seconds: int = Field(ge=0, description="Service uptime")
    
    # Configuration
    max_concurrent_analyses: int = Field(
        description="Max concurrent jobs"
    )
    supported_languages: List[str] = Field(
        description="Supported languages"
    )


# ============================================================================
# Memory / Project Metadata
# ============================================================================

class ProjectMetadata(BaseModel):
    """Project analysis metadata"""
    project_id: str = Field(description="Project identifier")
    project_path: str = Field(description="Project root path")
    project_name: Optional[str] = Field(None, description="Project name")
    
    # Analysis info
    languages: List[str] = Field(
        description="Languages detected"
    )
    total_files: int = Field(ge=0, description="Total files")
    total_loc: int = Field(ge=0, description="Total lines of code")
    
    # Timestamps
    first_analyzed: datetime = Field(description="First analysis time")
    last_analyzed: datetime = Field(description="Last analysis time")
    
    # Statistics
    patterns_detected: int = Field(ge=0, description="Total patterns")
    average_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Average confidence"
    )
    analysis_duration_seconds: float = Field(
        ge=0,
        description="Total analysis time"
    )


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "ConfidenceLevelEnum",
    "PatternCategoryEnum",
    "RiskLevelEnum",
    "QueryComplexityEnum",
    "AnalysisStatusEnum",
    
    # Core models
    "ConfidenceScore",
    "PatternEvidence",
    "Pattern",
    "EdgeCase",
    "Decision",
    
    # RAG
    "Chunk",
    "SearchResult",
    
    # Analysis
    "AnalysisJob",
    "AnalysisProgress",
    "AnalysisResult",
    
    # Query/Response
    "QueryRequest",
    "QueryResponse",
    
    # WebSocket
    "WebSocketMessage",
    
    # Agent API
    "ValidationRequest",
    "ValidationResponse",
    "SuggestionRequest",
    "SuggestionResponse",
    
    # Health
    "HealthStatus",
    "ProjectMetadata",
]
