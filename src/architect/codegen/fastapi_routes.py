"""
FastAPI Routes Template Engine

Generates FastAPI CRUD endpoints with:
- CRUD endpoint templates (GET, POST, PUT, DELETE)
- Request/response Schema binding
- Error handling (HTTPException, 400/401/404/500)
- Docstrings (docstring + OpenAPI)

Version: 1.0
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any
from enum import Enum


class HTTPMethod(Enum):
    """HTTP methods for endpoints"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class RouteParameter:
    """Route parameter definition
    
    中文: 路由参数定义
    """
    name: str
    param_type: str  # e.g., "int", "str", "uuid"
    required: bool = True
    description_cn: str = ""
    description_en: str = ""
    example: Optional[Any] = None


@dataclass
class ErrorResponse:
    """Error response definition
    
    中文: 错误响应定义
    """
    status_code: int
    description_cn: str = ""
    description_en: str = ""


@dataclass
class EndpointDef:
    """Endpoint definition for CRUD operation
    
    中文: CRUD操作的端点定义
    """
    method: HTTPMethod
    path: str
    name: str  # Function name (e.g., "get_item", "create_item")
    summary_cn: str = ""
    summary_en: str = ""
    description_cn: str = ""
    description_en: str = ""
    request_model: Optional[str] = None  # Request Pydantic model
    response_model: Optional[str] = None  # Response Pydantic model
    parameters: List[RouteParameter] = None
    status_codes: List[int] = None  # Expected response codes
    tags: List[str] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []
        if self.status_codes is None:
            self.status_codes = [200]
        if self.tags is None:
            self.tags = []


class FastAPIRoutesTemplate:
    """FastAPI routes code generator
    
    中文: FastAPI 路由代码生成器
    """
    
    def __init__(self):
        """Initialize FastAPI routes template engine"""
        self.error_map = {
            400: ErrorResponse(400, "请求参数错误", "Bad Request"),
            401: ErrorResponse(401, "未授权", "Unauthorized"),
            403: ErrorResponse(403, "禁止访问", "Forbidden"),
            404: ErrorResponse(404, "资源不存在", "Not Found"),
            422: ErrorResponse(422, "验证错误", "Validation Error"),
            500: ErrorResponse(500, "服务器错误", "Internal Server Error"),
        }
    
    def generate_parameter_annotation(self, param: RouteParameter) -> str:
        """Generate parameter annotation for function signature
        
        中文: 为函数签名生成参数注解
        
        Args:
            param: Route parameter
        
        Returns:
            Parameter annotation (e.g., "item_id: int = Path(...)")
        """
        type_mapping = {
            "int": "int",
            "str": "str",
            "float": "float",
            "uuid": "UUID",
            "bool": "bool",
        }
        
        py_type = type_mapping.get(param.param_type, param.param_type)
        
        # Use Path() for path parameters
        return f"{param.name}: {py_type} = Path(..., description='{param.description_en}')"
    
    def generate_query_parameter(self, param: RouteParameter) -> str:
        """Generate query parameter annotation
        
        中文: 生成查询参数注解
        
        Args:
            param: Route parameter
        
        Returns:
            Query parameter annotation
        """
        type_mapping = {
            "int": "int",
            "str": "str",
            "float": "float",
            "bool": "bool",
        }
        
        py_type = type_mapping.get(param.param_type, param.param_type)
        
        if param.required:
            return f"{param.name}: {py_type} = Query(..., description='{param.description_en}')"
        else:
            return f"{param.name}: Optional[{py_type}] = Query(None, description='{param.description_en}')"
    
    def generate_endpoint_docstring(self, endpoint: EndpointDef) -> str:
        """Generate endpoint docstring with bilingual support
        
        中文: 生成支持双语的端点文档字符串
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Docstring block
        """
        lines = ['    """']
        
        if endpoint.summary_cn:
            lines.append(f"    {endpoint.summary_cn}")
        if endpoint.summary_en:
            lines.append(f"    {endpoint.summary_en}")
        
        if endpoint.description_cn or endpoint.description_en:
            lines.append("")
            if endpoint.description_cn:
                lines.append(f"    {endpoint.description_cn}")
            if endpoint.description_en:
                lines.append(f"    {endpoint.description_en}")
        
        # Document status codes
        if endpoint.status_codes:
            lines.append("")
            lines.append("    返回码 / Status Codes:")
            for code in endpoint.status_codes:
                error_resp = self.error_map.get(code)
                if error_resp:
                    lines.append(f"        {code}: {error_resp.description_en}")
                else:
                    lines.append(f"        {code}: Success")
        
        lines.append('    """')
        return "\n".join(lines)
    
    def generate_function_signature(self, endpoint: EndpointDef) -> str:
        """Generate function signature with parameters
        
        中文: 生成带有参数的函数签名
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Function signature line
        """
        params = []
        
        # Add path and query parameters
        for param in endpoint.parameters:
            if param.param_type == "path":
                params.append(self.generate_parameter_annotation(param))
            else:
                params.append(self.generate_query_parameter(param))
        
        # Add request body
        if endpoint.request_model:
            params.append(f"data: {endpoint.request_model}")
        
        params_str = ", ".join(params)
        response_type = endpoint.response_model or "Dict[str, Any]"
        
        return f"async def {endpoint.name}({params_str}) -> {response_type}:"
    
    def generate_get_endpoint(self, endpoint: EndpointDef) -> str:
        """Generate GET endpoint
        
        中文: 生成 GET 端点
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Complete endpoint code
        """
        lines = []
        
        # Decorator
        lines.append(f"@router.get(")
        lines.append(f'    "{endpoint.path}",')
        lines.append(f'    summary="{endpoint.summary_en}",')
        lines.append(f'    response_model={endpoint.response_model or "Dict"},')
        lines.append(f'    status_code=200,')
        if endpoint.tags:
            lines.append(f'    tags={endpoint.tags},')
        lines.append(")")
        
        # Docstring
        lines.append(self.generate_endpoint_docstring(endpoint))
        
        # Function signature
        params = []
        for param in endpoint.parameters:
            params.append(self.generate_parameter_annotation(param))
        params_str = ", ".join(params)
        response_type = endpoint.response_model or "Dict[str, Any]"
        lines.append(f"async def {endpoint.name}({params_str}) -> {response_type}:")
        
        # Default implementation
        lines.append("    try:")
        lines.append("        # TODO: Implement endpoint logic")
        lines.append("        return {}")
        lines.append("    except ValueError as e:")
        lines.append('        raise HTTPException(status_code=400, detail=str(e))')
        lines.append("    except Exception as e:")
        lines.append('        raise HTTPException(status_code=500, detail="Internal server error")')
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_post_endpoint(self, endpoint: EndpointDef) -> str:
        """Generate POST endpoint
        
        中文: 生成 POST 端点
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Complete endpoint code
        """
        lines = []
        
        # Decorator
        lines.append(f"@router.post(")
        lines.append(f'    "{endpoint.path}",')
        lines.append(f'    summary="{endpoint.summary_en}",')
        lines.append(f'    response_model={endpoint.response_model or "Dict"},')
        lines.append(f'    status_code=201,')
        if endpoint.tags:
            lines.append(f'    tags={endpoint.tags},')
        lines.append(")")
        
        # Docstring
        lines.append(self.generate_endpoint_docstring(endpoint))
        
        # Function signature
        response_type = endpoint.response_model or "Dict[str, Any]"
        lines.append(f"async def {endpoint.name}(data: {endpoint.request_model or 'Dict'}) -> {response_type}:")
        
        # Default implementation
        lines.append("    try:")
        lines.append("        # TODO: Implement endpoint logic")
        lines.append("        return {}")
        lines.append("    except ValueError as e:")
        lines.append('        raise HTTPException(status_code=400, detail=str(e))')
        lines.append("    except Exception as e:")
        lines.append('        raise HTTPException(status_code=500, detail="Internal server error")')
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_put_endpoint(self, endpoint: EndpointDef) -> str:
        """Generate PUT endpoint
        
        中文: 生成 PUT 端点
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Complete endpoint code
        """
        lines = []
        
        # Decorator
        lines.append(f"@router.put(")
        lines.append(f'    "{endpoint.path}",')
        lines.append(f'    summary="{endpoint.summary_en}",')
        lines.append(f'    response_model={endpoint.response_model or "Dict"},')
        lines.append(")")
        
        # Docstring
        lines.append(self.generate_endpoint_docstring(endpoint))
        
        # Function signature
        params = [self.generate_parameter_annotation(p) for p in endpoint.parameters]
        params.append(f"data: {endpoint.request_model or 'Dict'}")
        params_str = ", ".join(params)
        response_type = endpoint.response_model or "Dict[str, Any]"
        lines.append(f"async def {endpoint.name}({params_str}) -> {response_type}:")
        
        # Default implementation
        lines.append("    try:")
        lines.append("        # TODO: Implement endpoint logic")
        lines.append("        return {}")
        lines.append("    except ValueError as e:")
        lines.append('        raise HTTPException(status_code=400, detail=str(e))')
        lines.append("    except Exception as e:")
        lines.append('        raise HTTPException(status_code=500, detail="Internal server error")')
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_delete_endpoint(self, endpoint: EndpointDef) -> str:
        """Generate DELETE endpoint
        
        中文: 生成 DELETE 端点
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Complete endpoint code
        """
        lines = []
        
        # Decorator
        lines.append(f"@router.delete(")
        lines.append(f'    "{endpoint.path}",')
        lines.append(f'    summary="{endpoint.summary_en}",')
        lines.append(f'    status_code=204,')
        if endpoint.tags:
            lines.append(f'    tags={endpoint.tags},')
        lines.append(")")
        
        # Docstring
        lines.append(self.generate_endpoint_docstring(endpoint))
        
        # Function signature
        params = [self.generate_parameter_annotation(p) for p in endpoint.parameters]
        params_str = ", ".join(params)
        lines.append(f"async def {endpoint.name}({params_str}):")
        
        # Default implementation
        lines.append("    try:")
        lines.append("        # TODO: Implement endpoint logic")
        lines.append("        return None")
        lines.append("    except ValueError as e:")
        lines.append('        raise HTTPException(status_code=400, detail=str(e))')
        lines.append("    except Exception as e:")
        lines.append('        raise HTTPException(status_code=500, detail="Internal server error")')
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_endpoint(self, endpoint: EndpointDef) -> str:
        """Generate endpoint based on HTTP method
        
        中文: 根据HTTP方法生成端点
        
        Args:
            endpoint: Endpoint definition
        
        Returns:
            Complete endpoint code
        """
        if endpoint.method == HTTPMethod.GET:
            return self.generate_get_endpoint(endpoint)
        elif endpoint.method == HTTPMethod.POST:
            return self.generate_post_endpoint(endpoint)
        elif endpoint.method == HTTPMethod.PUT:
            return self.generate_put_endpoint(endpoint)
        elif endpoint.method == HTTPMethod.DELETE:
            return self.generate_delete_endpoint(endpoint)
        else:
            raise ValueError(f"Unsupported HTTP method: {endpoint.method}")
    
    def generate_imports(self) -> str:
        """Generate required imports for FastAPI routes
        
        中文: 生成 FastAPI 路由所需的导入
        
        Returns:
            Import statements
        """
        return (
            "from fastapi import APIRouter, HTTPException, Path, Query, status\n"
            "from pydantic import BaseModel\n"
            "from typing import Optional, Dict, Any, List\n"
            "from uuid import UUID\n"
        )
    
    def generate_router_module(
        self,
        module_name: str,
        router_name: str,
        endpoints: List[EndpointDef],
        prefix: str = "",
    ) -> str:
        """Generate complete router module with all endpoints
        
        中文: 生成包含所有端点的完整路由模块
        
        Args:
            module_name: Module name
            router_name: Router variable name
            endpoints: List of endpoint definitions
            prefix: API prefix (e.g., "/api/v1")
        
        Returns:
            Complete module code
        """
        lines = []
        
        # Header
        lines.append(f'"""\n{module_name}\n')
        lines.append('Auto-generated FastAPI routes\n')
        lines.append('"""\n')
        
        # Imports
        lines.append(self.generate_imports())
        lines.append("")
        
        # Router initialization
        if prefix:
            lines.append(f"router = APIRouter(prefix='{prefix}')")
        else:
            lines.append(f"router = APIRouter()")
        lines.append("")
        
        # Generate endpoints
        for endpoint in endpoints:
            lines.append(self.generate_endpoint(endpoint))
        
        return "\n".join(lines)
