"""
Code Generation Module for Code Architect Agent Platform

Phase 1-3 Implementation:
- Phase 1: Template Engines (pydantic_v2, fastapi_routes, agent_patterns, async_patterns)
- Phase 2: Core Generators (generator, validators, api_adapter)
- Phase 3: Integration & Testing (integration, tests)

This module provides code generation capabilities for:
1. Pydantic V2 models with validators
2. FastAPI routes with CRUD endpoints
3. Agent lifecycle patterns
4. Async/await patterns with concurrent execution
5. Validation and code quality checks
6. A2A API integration with agent-platform

Version: 1.0
Author: Code Architect Platform
"""

from .pydantic_v2 import (
    PydanticV2Template,
    FieldDef,
    ValidatorDef,
    FieldType,
)

from .fastapi_routes import (
    FastAPIRoutesTemplate,
    EndpointDef,
    RouteParameter,
    ErrorResponse,
    HTTPMethod,
)

from .agent_patterns import (
    AgentPatternsTemplate,
    AgentSessionConfig,
    MemoryConfig,
    KnowledgePackConfig,
    AgentState,
    MemoryType,
)

from .async_patterns import (
    AsyncPatternsTemplate,
    AsyncFunctionDef,
    AsyncSessionDef,
    ConcurrencyPattern,
)

from .generator import (
    CodeGenerator,
    GenerationConfig,
    CodeTemplate,
    SimpleStringTemplate,
)

from .validators import (
    CodeValidator,
    SyntaxValidator,
    TypeAnnotationValidator,
    ImportValidator,
    StyleValidator,
    ValidationIssue,
    SeverityLevel,
)

from .api_adapter import (
    A2ACodegenAdapter,
    GenerateRequest,
    GenerateResponse,
    ValidateRequest,
    ValidateResponse,
    ImpactRequest,
    ImpactResponse,
)

__all__ = [
    # Phase 1: Template Engines
    "PydanticV2Template",
    "FieldDef",
    "ValidatorDef",
    "FieldType",
    "FastAPIRoutesTemplate",
    "EndpointDef",
    "RouteParameter",
    "ErrorResponse",
    "HTTPMethod",
    "AgentPatternsTemplate",
    "AgentSessionConfig",
    "MemoryConfig",
    "KnowledgePackConfig",
    "AgentState",
    "MemoryType",
    "AsyncPatternsTemplate",
    "AsyncFunctionDef",
    "AsyncSessionDef",
    "ConcurrencyPattern",
    
    # Phase 2: Core Generators
    "CodeGenerator",
    "GenerationConfig",
    "CodeTemplate",
    "SimpleStringTemplate",
    "CodeValidator",
    "SyntaxValidator",
    "TypeAnnotationValidator",
    "ImportValidator",
    "StyleValidator",
    "ValidationIssue",
    "SeverityLevel",
    "A2ACodegenAdapter",
    "GenerateRequest",
    "GenerateResponse",
    "ValidateRequest",
    "ValidateResponse",
    "ImpactRequest",
    "ImpactResponse",
]

__version__ = "1.0.0"
__phase__ = 2  # Phase 2: Core Generators + API Adapter
