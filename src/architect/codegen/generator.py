"""
Core Code Generation Engine

Implements:
- Template loading and caching
- Code generation pipeline (parse → generate → format)
- Variable substitution (Jinja2 style)
- Code formatting (black/autopep8)

Version: 1.0
"""

import asyncio
import logging
import json
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
from dataclasses import dataclass
import re
import subprocess
import ast
from datetime import datetime
from abc import ABC, abstractmethod

# Optional: for advanced template engine
try:
    from jinja2 import Environment, FileSystemLoader, Template as Jinja2Template
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class GenerationConfig:
    """Code generation configuration
    
    中文: 代码生成配置
    """
    template_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    use_black: bool = True  # Use black for formatting
    use_autopep8: bool = False  # Use autopep8 for formatting
    validate_syntax: bool = True  # Validate generated code
    bilingual_comments: bool = True  # Include Chinese comments
    cache_templates: bool = True
    jinja2_env: Optional[Dict[str, Any]] = None  # Jinja2 environment options


class CodeTemplate(ABC):
    """Abstract base class for code templates
    
    中文: 代码模板的抽象基类
    """
    
    def __init__(self, name: str, version: str = "1.0"):
        """Initialize template
        
        Args:
            name: Template name
            version: Template version
        """
        self.name = name
        self.version = version
    
    @abstractmethod
    def render(self, context: Dict[str, Any]) -> str:
        """Render template with context
        
        中文: 使用上下文呈现模板
        
        Args:
            context: Variable context for rendering
        
        Returns:
            Rendered code
        """
        pass


class SimpleStringTemplate(CodeTemplate):
    """Simple string template with variable substitution
    
    中文: 带有变量替换的简单字符串模板
    """
    
    def __init__(self, name: str, content: str, version: str = "1.0"):
        """Initialize string template
        
        Args:
            name: Template name
            content: Template content
            version: Template version
        """
        super().__init__(name, version)
        self.content = content
    
    def render(self, context: Dict[str, Any]) -> str:
        """Render template with variable substitution
        
        中文: 使用变量替换呈现模板
        
        Args:
            context: Variable context
        
        Returns:
            Rendered code
        """
        result = self.content
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"  # {{key}} format
            result = result.replace(placeholder, str(value))
        return result


class Jinja2CodeTemplate(CodeTemplate):
    """Jinja2-based template for advanced rendering
    
    中文: 基于Jinja2的高级渲染模板
    """
    
    def __init__(self, name: str, content: str, version: str = "1.0"):
        """Initialize Jinja2 template
        
        Args:
            name: Template name
            content: Template content
            version: Template version
        """
        super().__init__(name, version)
        if not JINJA2_AVAILABLE:
            raise ImportError("Jinja2 is required for advanced templates")
        self.template = Jinja2Template(content)
    
    def render(self, context: Dict[str, Any]) -> str:
        """Render template with Jinja2
        
        中文: 使用Jinja2呈现模板
        
        Args:
            context: Variable context
        
        Returns:
            Rendered code
        """
        return self.template.render(context)


class CodeGenerator:
    """Core code generation engine
    
    中文: 核心代码生成引擎
    """
    
    def __init__(self, config: Optional[GenerationConfig] = None):
        """Initialize code generator
        
        Args:
            config: Generation configuration
        """
        self.config = config or GenerationConfig()
        self.template_cache: Dict[str, CodeTemplate] = {}
        self._formatter_available = self._check_formatter()
    
    def _check_formatter(self) -> bool:
        """Check if code formatter is available
        
        中文: 检查代码格式化工具是否可用
        
        Returns:
            True if formatter available
        """
        try:
            if self.config.use_black:
                subprocess.run(
                    ["python3", "-m", "black", "--version"],
                    capture_output=True,
                    timeout=5,
                )
                return True
        except Exception:
            logger.warning("Black formatter not available")
        
        try:
            if self.config.use_autopep8:
                subprocess.run(
                    ["python3", "-m", "autopep8", "--version"],
                    capture_output=True,
                    timeout=5,
                )
                return True
        except Exception:
            logger.warning("autopep8 formatter not available")
        
        return False
    
    def register_template(self, template: CodeTemplate) -> None:
        """Register code template
        
        中文: 注册代码模板
        
        Args:
            template: Template instance
        """
        if self.config.cache_templates:
            self.template_cache[template.name] = template
    
    def get_template(self, name: str) -> Optional[CodeTemplate]:
        """Get registered template
        
        中文: 获取已注册的模板
        
        Args:
            name: Template name
        
        Returns:
            Template instance or None
        """
        return self.template_cache.get(name)
    
    def parse_context(self, context_str: str) -> Dict[str, Any]:
        """Parse context from JSON or dict string
        
        中文: 从JSON或字典字符串解析上下文
        
        Args:
            context_str: Context string
        
        Returns:
            Parsed context dictionary
        """
        try:
            return json.loads(context_str)
        except json.JSONDecodeError:
            # Try evaluating as Python dict
            try:
                return eval(context_str)
            except Exception as e:
                logger.error(f"Failed to parse context: {e}")
                return {}
    
    async def generate(
        self,
        template: CodeTemplate,
        context: Dict[str, Any],
        format_code: bool = True,
    ) -> str:
        """Generate code from template
        
        中文: 从模板生成代码
        
        Args:
            template: Code template
            context: Variable context
            format_code: Whether to format generated code
        
        Returns:
            Generated code
        """
        try:
            # Render template
            code = template.render(context)
            
            # Optionally format
            if format_code and self._formatter_available:
                code = await self.format_code(code)
            
            # Optionally validate
            if self.config.validate_syntax:
                is_valid, errors = self.validate_syntax(code)
                if not is_valid:
                    logger.warning(f"Generated code has syntax issues: {errors}")
            
            return code
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            raise
    
    async def generate_from_file(
        self,
        template_path: Path,
        context: Dict[str, Any],
        format_code: bool = True,
    ) -> str:
        """Generate code from template file
        
        中文: 从模板文件生成代码
        
        Args:
            template_path: Path to template file
            context: Variable context
            format_code: Whether to format code
        
        Returns:
            Generated code
        """
        try:
            with open(template_path, 'r') as f:
                content = f.read()
            
            template = SimpleStringTemplate(
                template_path.stem,
                content,
            )
            return await self.generate(template, context, format_code)
        except Exception as e:
            logger.error(f"Failed to generate from file: {e}")
            raise
    
    async def format_code(self, code: str) -> str:
        """Format code using black or autopep8
        
        中文: 使用black或autopep8格式化代码
        
        Args:
            code: Code to format
        
        Returns:
            Formatted code
        """
        try:
            if self.config.use_black:
                result = subprocess.run(
                    ["python3", "-m", "black", "-"],
                    input=code.encode(),
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout.decode()
            
            if self.config.use_autopep8:
                result = subprocess.run(
                    ["python3", "-m", "autopep8", "-"],
                    input=code.encode(),
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout.decode()
        except Exception as e:
            logger.warning(f"Code formatting failed: {e}")
        
        return code  # Return unformatted if formatting fails
    
    def validate_syntax(self, code: str) -> Tuple[bool, List[str]]:
        """Validate Python code syntax
        
        中文: 验证Python代码语法
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        try:
            ast.parse(code)
            return True, []
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
        except Exception as e:
            errors.append(f"Validation error: {e}")
        
        return False, errors
    
    def validate_imports(self, code: str) -> Tuple[bool, List[str]]:
        """Validate all imports in code
        
        中文: 验证代码中的所有导入
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (all_valid, missing_modules)
        """
        missing = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        try:
                            __import__(module_name)
                        except ImportError:
                            missing.append(module_name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split('.')[0]
                        try:
                            __import__(module_name)
                        except ImportError:
                            missing.append(module_name)
        except Exception as e:
            logger.warning(f"Import validation failed: {e}")
        
        return len(missing) == 0, missing
    
    async def save_generated_code(
        self,
        code: str,
        output_path: Path,
    ) -> bool:
        """Save generated code to file
        
        中文: 将生成的代码保存到文件
        
        Args:
            code: Generated code
            output_path: Output file path
        
        Returns:
            True if successful
        """
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Add header comment
            header = f"# Auto-generated by Code Architect\n# Generated at: {datetime.utcnow().isoformat()}\n\n"
            content = header + code
            
            with open(output_path, 'w') as f:
                f.write(content)
            
            logger.info(f"Generated code saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save generated code: {e}")
            return False
    
    async def generate_pipeline(
        self,
        template: CodeTemplate,
        context: Dict[str, Any],
        output_path: Optional[Path] = None,
    ) -> Tuple[str, bool]:
        """Complete generation pipeline: parse → generate → validate → format → save
        
        中文: 完整生成管道: 解析 → 生成 → 验证 → 格式化 → 保存
        
        Args:
            template: Code template
            context: Variable context
            output_path: Optional output path
        
        Returns:
            Tuple of (generated_code, success)
        """
        try:
            # Parse context
            logger.debug(f"Parsing context with {len(context)} variables")
            
            # Generate
            logger.debug(f"Generating code from template: {template.name}")
            code = await self.generate(template, context, format_code=True)
            
            # Validate syntax
            if self.config.validate_syntax:
                is_valid, errors = self.validate_syntax(code)
                if not is_valid:
                    logger.warning(f"Syntax validation failed: {errors}")
            
            # Validate imports
            valid_imports, missing = self.validate_imports(code)
            if not valid_imports and missing:
                logger.warning(f"Missing imports: {missing}")
            
            # Save if path provided
            if output_path:
                await self.save_generated_code(code, output_path)
            
            return code, True
        except Exception as e:
            logger.error(f"Generation pipeline failed: {e}")
            return "", False
