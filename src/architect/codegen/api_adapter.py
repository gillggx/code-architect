"""
A2A API Adapter for agent-platform Integration

Extends existing A2A API with codegen endpoints:
- /generate - Accept agent-platform requests and generate code
- /validate - Validate generated code
- /impact - Analyze code impact

Version: 1.0
"""

import asyncio
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .generator import CodeGenerator, GenerationConfig, SimpleStringTemplate
from .validators import CodeValidator, ValidationIssue, SeverityLevel
from .pydantic_v2 import PydanticV2Template, FieldDef, ValidatorDef
from .fastapi_routes import FastAPIRoutesTemplate, EndpointDef, HTTPMethod, RouteParameter
from .agent_patterns import AgentPatternsTemplate, AgentSessionConfig, MemoryConfig
from .async_patterns import AsyncPatternsTemplate, AsyncFunctionDef

logger = logging.getLogger(__name__)


@dataclass
class GenerateRequest:
    """Code generation request from agent-platform
    
    中文: 来自agent-platform的代码生成请求
    """
    request_id: str
    template_type: str  # "pydantic", "fastapi", "agent", "async"
    template_name: str
    context: Dict[str, Any]
    options: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.options is None:
            self.options = {}


@dataclass
class GenerateResponse:
    """Code generation response
    
    中文: 代码生成响应
    """
    request_id: str
    success: bool
    code: str = ""
    errors: List[str] = None
    warnings: List[str] = None
    metadata: Dict[str, Any] = None
    generated_at: str = ""
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.metadata is None:
            self.metadata = {}
        if not self.generated_at:
            self.generated_at = datetime.utcnow().isoformat()


@dataclass
class ValidateRequest:
    """Code validation request
    
    中文: 代码验证请求
    """
    request_id: str
    code: str
    check_syntax: bool = True
    check_types: bool = True
    check_imports: bool = True
    check_style: bool = True


@dataclass
class ValidateResponse:
    """Code validation response
    
    中文: 代码验证响应
    """
    request_id: str
    valid: bool
    issues: List[Dict[str, Any]] = None
    summary: Dict[str, int] = None  # {errors: N, warnings: N, ...}
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []
        if self.summary is None:
            self.summary = {}


@dataclass
class ImpactRequest:
    """Code impact analysis request
    
    中文: 代码影响分析请求
    """
    request_id: str
    old_code: str
    new_code: str
    context: Dict[str, Any] = None


@dataclass
class ImpactResponse:
    """Code impact analysis response
    
    中文: 代码影响分析响应
    """
    request_id: str
    changes_detected: bool
    impact_summary: Dict[str, Any]
    breaking_changes: List[str] = None
    compatibility_issues: List[str] = None
    
    def __post_init__(self):
        if self.breaking_changes is None:
            self.breaking_changes = []
        if self.compatibility_issues is None:
            self.compatibility_issues = []


class A2ACodegenAdapter:
    """A2A API adapter for code generation
    
    中文: 代码生成的A2A API适配器
    """
    
    def __init__(self):
        """Initialize A2A adapter"""
        config = GenerationConfig(
            use_black=True,
            validate_syntax=True,
            bilingual_comments=True,
        )
        
        self.generator = CodeGenerator(config)
        self.validator = CodeValidator()
        
        # Template engines
        self.pydantic_template = PydanticV2Template()
        self.fastapi_template = FastAPIRoutesTemplate()
        self.agent_template = AgentPatternsTemplate()
        self.async_template = AsyncPatternsTemplate()
        
        # Request/response tracking
        self.request_history: Dict[str, Dict[str, Any]] = {}
    
    async def handle_generate_request(self, request: GenerateRequest) -> GenerateResponse:
        """Handle code generation request
        
        中文: 处理代码生成请求
        
        Args:
            request: Generation request
        
        Returns:
            Generation response
        """
        logger.info(f"Generating {request.template_type} code: {request.request_id}")
        
        try:
            # Generate code based on template type
            code = await self._generate_by_type(
                request.template_type,
                request.template_name,
                request.context,
                request.options,
            )
            
            # Validate generated code
            valid, issues = self.validator.validate(code)
            
            # Prepare response
            errors = []
            warnings = []
            for issue in issues:
                if issue.severity == SeverityLevel.ERROR:
                    errors.append(f"{issue.code}: {issue.message_en}")
                elif issue.severity == SeverityLevel.WARNING:
                    warnings.append(f"{issue.code}: {issue.message_en}")
            
            response = GenerateResponse(
                request_id=request.request_id,
                success=len(errors) == 0,
                code=code,
                errors=errors,
                warnings=warnings,
                metadata={
                    "template_type": request.template_type,
                    "template_name": request.template_name,
                    "code_lines": len(code.split('\n')),
                    "code_chars": len(code),
                    "validation_issues": len(issues),
                },
            )
            
            # Store in history
            self.request_history[request.request_id] = {
                "request": request,
                "response": response,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            return response
        
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return GenerateResponse(
                request_id=request.request_id,
                success=False,
                errors=[str(e)],
            )
    
    async def handle_validate_request(self, request: ValidateRequest) -> ValidateResponse:
        """Handle code validation request
        
        中文: 处理代码验证请求
        
        Args:
            request: Validation request
        
        Returns:
            Validation response
        """
        logger.info(f"Validating code: {request.request_id}")
        
        try:
            valid, issues = self.validator.validate(
                request.code,
                check_syntax=request.check_syntax,
                check_types=request.check_types,
                check_imports=request.check_imports,
                check_style=request.check_style,
            )
            
            # Convert issues to dict format
            issues_dict = []
            for issue in issues:
                issues_dict.append({
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message_en,
                    "line": issue.line_no,
                    "column": issue.column,
                    "suggestion": issue.suggestion,
                })
            
            # Summary
            summary = {
                "total": len(issues),
                "errors": sum(1 for i in issues if i.severity == SeverityLevel.ERROR),
                "warnings": sum(1 for i in issues if i.severity == SeverityLevel.WARNING),
                "info": sum(1 for i in issues if i.severity == SeverityLevel.INFO),
            }
            
            return ValidateResponse(
                request_id=request.request_id,
                valid=valid,
                issues=issues_dict,
                summary=summary,
            )
        
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return ValidateResponse(
                request_id=request.request_id,
                valid=False,
                issues=[],
                summary={"error": str(e)},
            )
    
    async def handle_impact_request(self, request: ImpactRequest) -> ImpactResponse:
        """Analyze code impact
        
        中文: 分析代码影响
        
        Args:
            request: Impact analysis request
        
        Returns:
            Impact analysis response
        """
        logger.info(f"Analyzing code impact: {request.request_id}")
        
        try:
            impact = self._analyze_code_changes(request.old_code, request.new_code)
            
            return ImpactResponse(
                request_id=request.request_id,
                changes_detected=impact["changes_detected"],
                impact_summary=impact["summary"],
                breaking_changes=impact.get("breaking_changes", []),
                compatibility_issues=impact.get("compatibility_issues", []),
            )
        
        except Exception as e:
            logger.error(f"Impact analysis failed: {e}")
            return ImpactResponse(
                request_id=request.request_id,
                changes_detected=False,
                impact_summary={"error": str(e)},
            )
    
    async def _generate_by_type(
        self,
        template_type: str,
        template_name: str,
        context: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """Generate code by template type
        
        中文: 根据模板类型生成代码
        
        Args:
            template_type: Type of template
            template_name: Template name
            context: Generation context
            options: Generation options
        
        Returns:
            Generated code
        """
        if template_type == "pydantic":
            return self._generate_pydantic(template_name, context)
        elif template_type == "fastapi":
            return self._generate_fastapi(template_name, context)
        elif template_type == "agent":
            return self._generate_agent(template_name, context)
        elif template_type == "async":
            return self._generate_async(template_name, context)
        else:
            raise ValueError(f"Unsupported template type: {template_type}")
    
    def _generate_pydantic(self, template_name: str, context: Dict[str, Any]) -> str:
        """Generate Pydantic V2 model
        
        中文: 生成Pydantic V2模型
        """
        model_name = context.get("model_name", "Model")
        fields_data = context.get("fields", [])
        
        fields = []
        for field_data in fields_data:
            field = FieldDef(
                name=field_data.get("name"),
                type_name=self.pydantic_template.map_field_type(
                    field_data.get("type", "str")
                ),
                required=field_data.get("required", True),
                default=field_data.get("default"),
                description_en=field_data.get("description", ""),
            )
            fields.append(field)
        
        return self.pydantic_template.generate_model(
            model_name,
            fields,
            description_en=context.get("description", ""),
        )
    
    def _generate_fastapi(self, template_name: str, context: Dict[str, Any]) -> str:
        """Generate FastAPI routes
        
        中文: 生成FastAPI路由
        """
        endpoints_data = context.get("endpoints", [])
        prefix = context.get("prefix", "")
        
        endpoints = []
        for ep_data in endpoints_data:
            endpoint = EndpointDef(
                method=HTTPMethod[ep_data.get("method", "GET")],
                path=ep_data.get("path", "/"),
                name=ep_data.get("name", "endpoint"),
                summary_en=ep_data.get("summary", ""),
                response_model=ep_data.get("response_model"),
                request_model=ep_data.get("request_model"),
            )
            endpoints.append(endpoint)
        
        return self.fastapi_template.generate_router_module(
            template_name,
            "router",
            endpoints,
            prefix,
        )
    
    def _generate_agent(self, template_name: str, context: Dict[str, Any]) -> str:
        """Generate Agent patterns
        
        中文: 生成Agent模式
        """
        config = AgentSessionConfig(
            agent_id=context.get("agent_id", str(uuid4())),
            agent_name=context.get("agent_name", "Agent"),
            role=context.get("role", "agent"),
            description_en=context.get("description", ""),
        )
        
        return self.agent_template.generate_complete_agent_module(config)
    
    def _generate_async(self, template_name: str, context: Dict[str, Any]) -> str:
        """Generate async patterns
        
        中文: 生成异步模式
        """
        functions_data = context.get("functions", [])
        
        functions = []
        for func_data in functions_data:
            func = AsyncFunctionDef(
                name=func_data.get("name"),
                parameters=func_data.get("parameters", []),
                return_type=func_data.get("return_type", "Any"),
                description_en=func_data.get("description", ""),
                concurrent_calls=func_data.get("concurrent_calls", []),
            )
            functions.append(func)
        
        return self.async_template.generate_complete_async_module(
            template_name,
            functions,
        )
    
    def _analyze_code_changes(self, old_code: str, new_code: str) -> Dict[str, Any]:
        """Analyze changes between old and new code
        
        中文: 分析新旧代码之间的变化
        
        Args:
            old_code: Original code
            new_code: New code
        
        Returns:
            Impact analysis result
        """
        import ast
        import difflib
        
        changes_detected = old_code != new_code
        
        try:
            old_tree = ast.parse(old_code)
            new_tree = ast.parse(new_code)
            
            old_functions = {n.name for n in ast.walk(old_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            new_functions = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            
            removed_functions = old_functions - new_functions
            added_functions = new_functions - old_functions
            
            breaking_changes = []
            if removed_functions:
                breaking_changes.append(f"Removed functions: {', '.join(removed_functions)}")
            
            return {
                "changes_detected": changes_detected,
                "summary": {
                    "lines_changed": len(list(difflib.unified_diff(
                        old_code.split('\n'),
                        new_code.split('\n'),
                    ))),
                    "functions_added": len(added_functions),
                    "functions_removed": len(removed_functions),
                },
                "breaking_changes": breaking_changes,
                "compatibility_issues": [],
            }
        
        except Exception as e:
            logger.warning(f"Detailed analysis failed: {e}")
            return {
                "changes_detected": changes_detected,
                "summary": {"note": "Basic diff analysis only"},
            }
