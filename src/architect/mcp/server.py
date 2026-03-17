"""
MCP Protocol Server for Code Architect Agent - Phase 3

Implements Model Context Protocol for IDE integration (Cursor, Claude, Cline).
Standardizes resources, tools, and prompts for external tool consumption.

Version: 3.0
Status: PRODUCTION
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """MCP Resource types"""
    JSON = "application/json"
    MARKDOWN = "text/markdown"
    TEXT = "text/plain"
    YAML = "text/yaml"


@dataclass
class MCPResource:
    """MCP Resource definition"""
    uri: str
    name: str
    mimeType: str
    description: str = ""
    readOnly: bool = True
    lastModified: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return asdict(self)


@dataclass
class MCPTool:
    """MCP Tool definition"""
    name: str
    description: str
    inputSchema: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return {
            'name': self.name,
            'description': self.description,
            'inputSchema': self.inputSchema,
        }


@dataclass
class MCPPrompt:
    """MCP Prompt template"""
    name: str
    description: str
    template: str
    arguments: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        return {
            'name': self.name,
            'description': self.description,
            'template': self.template,
            'arguments': self.arguments,
        }


class MCPServer:
    """
    Model Context Protocol Server
    
    Provides standardized resources, tools, and prompts for:
    - Cursor IDE integration
    - Claude.dev integration
    - Cline integration
    - Custom MCP clients
    
    Architecture:
    - Resources: Read-only access to analysis results
    - Tools: Available operations (query, analyze, etc)
    - Prompts: Pre-defined question templates
    """
    
    def __init__(self, name: str = "architect-agent-mcp", version: str = "1.0.0"):
        self.name = name
        self.version = version
        
        # Registry
        self.resources: Dict[str, MCPResource] = {}
        self.tools: Dict[str, MCPTool] = {}
        self.prompts: Dict[str, MCPPrompt] = {}
        
        # Implementation handlers
        self._resource_handlers: Dict[str, Callable] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        
        logger.info(f"MCPServer initialized: {name} v{version}")
        
        # Register default resources, tools, prompts
        self._register_defaults()
    
    def _register_defaults(self):
        """Register default resources, tools, and prompts"""
        
        # Resources
        self.register_resource(
            uri="architect://project",
            name="Project Metadata",
            mimeType="application/json",
            description="Project metadata including files, languages, and analysis summary"
        )
        
        self.register_resource(
            uri="architect://patterns",
            name="Architectural Patterns",
            mimeType="text/markdown",
            description="Detected architectural patterns with evidence and confidence scores"
        )
        
        self.register_resource(
            uri="architect://modules",
            name="Module Structure",
            mimeType="application/json",
            description="Module hierarchy, dependencies, and key entry points"
        )
        
        self.register_resource(
            uri="architect://dependencies",
            name="Dependency Graph",
            mimeType="application/json",
            description="Module dependencies and coupling analysis"
        )
        
        self.register_resource(
            uri="architect://edge-cases",
            name="Edge Cases & Robustness",
            mimeType="text/markdown",
            description="Known edge cases, error handling patterns, and robustness analysis"
        )
        
        # Tools
        self.register_tool(
            name="query",
            description="Ask a question about code architecture and patterns",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Question about the code"
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (optional, uses current if omitted)"
                    },
                    "confidence_threshold": {
                        "type": "number",
                        "description": "Minimum confidence for results (0.0-1.0, default: 0.8)",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.8
                    },
                },
                "required": ["question"]
            }
        )
        
        self.register_tool(
            name="analyze",
            description="Trigger code analysis for a project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to project directory"
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Languages to analyze (auto-detect if omitted)"
                    },
                },
                "required": ["project_path"]
            }
        )
        
        self.register_tool(
            name="validate_code",
            description="Check if code snippet matches detected patterns",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code snippet to validate"
                    },
                    "pattern_name": {
                        "type": "string",
                        "description": "Pattern to validate against"
                    },
                },
                "required": ["code", "pattern_name"]
            }
        )
        
        self.register_tool(
            name="refresh",
            description="Refresh analysis for a project (incremental update)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID to refresh"
                    },
                },
                "required": ["project_id"]
            }
        )
        
        # Prompts
        self.register_prompt(
            name="ask_module_overview",
            description="Get overview of a module's purpose and structure",
            template="Describe the {module_name} module in detail:\n1. What does it do?\n2. Key classes/functions?\n3. Main dependencies?\n4. Error handling strategy?"
        )
        
        self.register_prompt(
            name="explain_pattern",
            description="Explain how a pattern is implemented",
            template="Explain how the {pattern_name} pattern is implemented in this codebase:\n1. Where is it used?\n2. Why this pattern?\n3. Alternatives considered?\n4. Trade-offs?"
        )
        
        self.register_prompt(
            name="analyze_dependencies",
            description="Analyze dependencies between modules",
            template="Analyze the dependencies between {module1} and {module2}:\n1. Direct dependencies?\n2. Coupling analysis?\n3. Potential issues?\n4. Refactoring opportunities?"
        )
        
        logger.info("Registered default resources, tools, and prompts")
    
    def register_resource(
        self,
        uri: str,
        name: str,
        mimeType: str,
        description: str = "",
        readOnly: bool = True,
        handler: Optional[Callable] = None
    ):
        """Register a resource"""
        
        resource = MCPResource(
            uri=uri,
            name=name,
            mimeType=mimeType,
            description=description,
            readOnly=readOnly,
            lastModified=datetime.now().isoformat()
        )
        
        self.resources[uri] = resource
        
        if handler:
            self._resource_handlers[uri] = handler
        
        logger.debug(f"Registered resource: {uri}")
    
    def register_tool(
        self,
        name: str,
        description: str,
        inputSchema: Dict[str, Any],
        handler: Optional[Callable] = None
    ):
        """Register a tool"""
        
        tool = MCPTool(
            name=name,
            description=description,
            inputSchema=inputSchema
        )
        
        self.tools[name] = tool
        
        if handler:
            self._tool_handlers[name] = handler
        
        logger.debug(f"Registered tool: {name}")
    
    def register_prompt(
        self,
        name: str,
        description: str,
        template: str,
        arguments: Optional[List[Dict[str, Any]]] = None
    ):
        """Register a prompt template"""
        
        prompt = MCPPrompt(
            name=name,
            description=description,
            template=template,
            arguments=arguments or []
        )
        
        self.prompts[name] = prompt
        logger.debug(f"Registered prompt: {name}")
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """
        Call a tool
        
        Returns: Tool execution result
        """
        
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        if tool_name not in self._tool_handlers:
            raise NotImplementedError(f"Tool not implemented: {tool_name}")
        
        handler = self._tool_handlers[tool_name]
        
        # Call handler (supports both sync and async)
        if asyncio.iscoroutinefunction(handler):
            return await handler(**arguments)
        else:
            return handler(**arguments)
    
    async def read_resource(
        self,
        uri: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Read a resource
        
        Returns: Resource content
        """
        
        if uri not in self.resources:
            raise ValueError(f"Unknown resource: {uri}")
        
        if uri not in self._resource_handlers:
            raise NotImplementedError(f"Resource not implemented: {uri}")
        
        handler = self._resource_handlers[uri]
        
        # Call handler
        if asyncio.iscoroutinefunction(handler):
            return await handler(**(arguments or {}))
        else:
            return handler(**(arguments or {}))
    
    def get_schema(self) -> Dict[str, Any]:
        """Get MCP server schema (protocol definition)"""
        
        return {
            "server": {
                "name": self.name,
                "version": self.version,
                "protocol": "MCP/1.0"
            },
            "resources": [r.to_dict() for r in self.resources.values()],
            "tools": [t.to_dict() for t in self.tools.values()],
            "prompts": [p.to_dict() for p in self.prompts.values()],
        }
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """List all resources"""
        return [r.to_dict() for r in self.resources.values()]
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools"""
        return [t.to_dict() for t in self.tools.values()]
    
    def list_prompts(self) -> List[Dict[str, Any]]:
        """List all prompts"""
        return [p.to_dict() for p in self.prompts.values()]


class MCPServerFactory:
    """Factory for creating MCP servers with handlers"""
    
    @staticmethod
    def create_with_handlers(
        project_manager,
        query_engine,
        analysis_engine
    ) -> MCPServer:
        """
        Create fully configured MCP server with handlers
        
        Args:
        - project_manager: ProjectManager instance
        - query_engine: QueryEngine instance
        - analysis_engine: CodeAnalysisEngine instance
        """
        
        server = MCPServer()
        
        # Register tool handlers
        async def query_handler(question: str, project_id: Optional[str] = None, confidence_threshold: float = 0.8):
            """Handle query tool"""
            if project_id:
                await project_manager.switch_project(project_id)
            
            result = await query_engine.answer(
                question,
                confidence_threshold=confidence_threshold
            )
            return result
        
        async def analyze_handler(project_path: str, languages: Optional[List[str]] = None):
            """Handle analyze tool"""
            result = await analysis_engine.analyze_project(
                project_path,
                languages=languages or []
            )
            return result
        
        async def validate_handler(code: str, pattern_name: str):
            """Handle validate tool"""
            # TODO: Implement code validation against pattern
            return {"validated": False, "message": "Not yet implemented"}
        
        async def refresh_handler(project_id: str):
            """Handle refresh tool"""
            # TODO: Implement incremental refresh
            return {"refreshed": False, "message": "Not yet implemented"}
        
        # Register handlers
        server.register_tool(
            name="query",
            description="Ask a question about code",
            inputSchema=server.tools["query"].inputSchema,
            handler=query_handler
        )
        
        server.register_tool(
            name="analyze",
            description="Analyze a project",
            inputSchema=server.tools["analyze"].inputSchema,
            handler=analyze_handler
        )
        
        server.register_tool(
            name="validate_code",
            description="Validate code against pattern",
            inputSchema=server.tools["validate_code"].inputSchema,
            handler=validate_handler
        )
        
        server.register_tool(
            name="refresh",
            description="Refresh project analysis",
            inputSchema=server.tools["refresh"].inputSchema,
            handler=refresh_handler
        )
        
        # Register resource handlers
        async def project_resource_handler(**kwargs):
            """Handle project resource"""
            current = await project_manager.get_current_project()
            if not current:
                return {"error": "No project loaded"}
            
            return {
                "project_id": current.project_id,
                "name": current.metadata.name,
                "files": current.metadata.file_count,
                "languages": current.metadata.languages,
            }
        
        async def patterns_resource_handler(**kwargs):
            """Handle patterns resource"""
            current = await project_manager.get_current_project()
            if not current:
                return "# No patterns (no project loaded)\n"
            
            patterns_text = "# Detected Patterns\n\n"
            for pattern in current.patterns:
                patterns_text += f"## {pattern.get('name', 'Unknown')}\n"
                patterns_text += f"Confidence: {pattern.get('confidence', 0):.1%}\n\n"
            
            return patterns_text
        
        server.register_resource(
            uri="architect://project",
            name="Project Metadata",
            mimeType="application/json",
            handler=project_resource_handler
        )
        
        server.register_resource(
            uri="architect://patterns",
            name="Patterns",
            mimeType="text/markdown",
            handler=patterns_resource_handler
        )
        
        logger.info("Created MCPServer with handlers")
        
        return server


def create_mcp_server() -> MCPServer:
    """Create default MCP server"""
    return MCPServer()
