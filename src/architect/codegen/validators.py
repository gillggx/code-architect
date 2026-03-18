"""
Code Validation System

Implements:
- Python syntax validation (ast.parse)
- Type annotation checking
- Import dependency validation
- Code style checking (PEP 8)

Version: 1.0
"""

import ast
import logging
import re
import subprocess
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SeverityLevel(Enum):
    """Validation severity levels
    
    中文: 验证严重程度级别
    """
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Validation issue report
    
    中文: 验证问题报告
    """
    severity: SeverityLevel
    code: str  # Issue code (e.g., "E001", "W001")
    message_cn: str = ""
    message_en: str = ""
    line_no: Optional[int] = None
    column: Optional[int] = None
    suggestion: Optional[str] = None
    
    def __str__(self) -> str:
        """String representation"""
        location = f":{self.line_no}" if self.line_no else ""
        return f"{self.severity.value.upper()} {self.code}{location}: {self.message_en}"


class SyntaxValidator:
    """Python syntax validation
    
    中文: Python语法验证
    """
    
    def __init__(self):
        """Initialize syntax validator"""
        self.issues: List[ValidationIssue] = []
    
    def validate(self, code: str) -> Tuple[bool, List[ValidationIssue]]:
        """Validate Python syntax
        
        中文: 验证Python语法
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (is_valid, issues)
        """
        self.issues = []
        
        try:
            ast.parse(code)
            return True, []
        except SyntaxError as e:
            issue = ValidationIssue(
                severity=SeverityLevel.ERROR,
                code="E001",
                message_cn="语法错误",
                message_en=f"Syntax error: {e.msg}",
                line_no=e.lineno,
                column=e.offset,
            )
            self.issues.append(issue)
            return False, self.issues
        except Exception as e:
            issue = ValidationIssue(
                severity=SeverityLevel.ERROR,
                code="E002",
                message_cn="解析错误",
                message_en=f"Parse error: {e}",
            )
            self.issues.append(issue)
            return False, self.issues
    
    def extract_ast_tree(self, code: str) -> Optional[ast.AST]:
        """Extract AST tree from code
        
        中文: 从代码提取AST树
        
        Args:
            code: Code to parse
        
        Returns:
            AST tree or None if invalid
        """
        try:
            return ast.parse(code)
        except Exception:
            return None


class TypeAnnotationValidator:
    """Type annotation validation
    
    中文: 类型注解验证
    """
    
    VALID_TYPES = {
        'str', 'int', 'float', 'bool', 'bytes',
        'list', 'dict', 'set', 'tuple',
        'List', 'Dict', 'Set', 'Tuple',
        'Optional', 'Union', 'Any',
        'Callable', 'Iterable', 'Iterator',
        'Sequence', 'Mapping', 'MutableMapping',
        'AsyncIterator', 'AsyncGenerator',
    }
    
    def __init__(self):
        """Initialize type annotation validator"""
        self.issues: List[ValidationIssue] = []
        self.undefined_types: set = set()
    
    def validate(self, code: str) -> Tuple[bool, List[ValidationIssue]]:
        """Validate type annotations
        
        中文: 验证类型注解
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (all_valid, issues)
        """
        self.issues = []
        self.undefined_types = set()
        
        try:
            tree = ast.parse(code)
            self._validate_tree(tree)
            return len(self.issues) == 0, self.issues
        except Exception as e:
            logger.error(f"Type annotation validation failed: {e}")
            return False, self.issues
    
    def _validate_tree(self, tree: ast.AST) -> None:
        """Recursively validate AST tree
        
        中文: 递归验证AST树
        
        Args:
            tree: AST tree
        """
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._validate_function(node)
            elif isinstance(node, ast.AnnAssign) and node.annotation:
                self._validate_annotation(node.annotation)
    
    def _validate_function(self, func_node) -> None:
        """Validate function type annotations
        
        中文: 验证函数类型注解
        
        Args:
            func_node: Function AST node
        """
        # Check return annotation
        if func_node.returns:
            self._validate_annotation(func_node.returns)
        
        # Check argument annotations
        for arg in func_node.args.args:
            if arg.annotation:
                self._validate_annotation(arg.annotation)
    
    def _validate_annotation(self, annotation: ast.expr) -> None:
        """Validate single annotation
        
        中文: 验证单个注解
        
        Args:
            annotation: Annotation AST node
        """
        if isinstance(annotation, ast.Name):
            type_name = annotation.id
            if type_name not in self.VALID_TYPES:
                if type_name not in self.undefined_types:
                    self.undefined_types.add(type_name)
                    issue = ValidationIssue(
                        severity=SeverityLevel.WARNING,
                        code="W001",
                        message_cn=f"未定义的类型: {type_name}",
                        message_en=f"Undefined type: {type_name}",
                        line_no=annotation.lineno,
                    )
                    self.issues.append(issue)
        elif isinstance(annotation, ast.Subscript):
            # Handle List[int], Dict[str, Any], etc.
            if isinstance(annotation.value, ast.Name):
                base_type = annotation.value.id
                if base_type not in self.VALID_TYPES:
                    issue = ValidationIssue(
                        severity=SeverityLevel.WARNING,
                        code="W002",
                        message_cn=f"未定义的泛型类型: {base_type}",
                        message_en=f"Undefined generic type: {base_type}",
                        line_no=annotation.lineno,
                    )
                    self.issues.append(issue)


class ImportValidator:
    """Import dependency validation
    
    中文: 导入依赖验证
    """
    
    def __init__(self):
        """Initialize import validator"""
        self.issues: List[ValidationIssue] = []
        self.missing_modules: List[str] = []
    
    def validate(self, code: str) -> Tuple[bool, List[ValidationIssue]]:
        """Validate imports in code
        
        中文: 验证代码中的导入
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (all_imports_valid, issues)
        """
        self.issues = []
        self.missing_modules = []
        
        try:
            tree = ast.parse(code)
            self._validate_imports(tree)
            return len(self.missing_modules) == 0, self.issues
        except Exception as e:
            logger.error(f"Import validation failed: {e}")
            return False, self.issues
    
    def _validate_imports(self, tree: ast.AST) -> None:
        """Validate imports in AST tree
        
        中文: 验证AST树中的导入
        
        Args:
            tree: AST tree
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_module(alias.name, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._check_module(node.module, node.lineno)
    
    def _check_module(self, module_name: str, line_no: int) -> None:
        """Check if module is available
        
        中文: 检查模块是否可用
        
        Args:
            module_name: Module name
            line_no: Line number
        """
        # Get base module (e.g., "a.b.c" -> "a")
        base_module = module_name.split('.')[0]
        
        try:
            __import__(base_module)
        except ImportError:
            if base_module not in self.missing_modules:
                self.missing_modules.append(base_module)
                issue = ValidationIssue(
                    severity=SeverityLevel.ERROR,
                    code="E003",
                    message_cn=f"缺失模块: {base_module}",
                    message_en=f"Missing module: {base_module}",
                    line_no=line_no,
                    suggestion=f"pip install {base_module}",
                )
                self.issues.append(issue)


class StyleValidator:
    """PEP 8 code style validation
    
    中文: PEP 8代码风格验证
    """
    
    def __init__(self):
        """Initialize style validator"""
        self.issues: List[ValidationIssue] = []
    
    def validate(self, code: str) -> Tuple[bool, List[ValidationIssue]]:
        """Validate code style using flake8 or similar
        
        中文: 使用flake8或类似工具验证代码风格
        
        Args:
            code: Code to validate
        
        Returns:
            Tuple of (style_ok, issues)
        """
        self.issues = []
        
        # Try using flake8 if available
        try:
            result = subprocess.run(
                ["python3", "-m", "flake8", "-"],
                input=code.encode(),
                capture_output=True,
                timeout=10,
            )
            
            if result.returncode != 0:
                output = result.stdout.decode()
                self._parse_flake8_output(output)
                return False, self.issues
            return True, []
        except FileNotFoundError:
            logger.debug("flake8 not available, using basic validation")
            return self._basic_style_check(code)
        except Exception as e:
            logger.warning(f"Style validation failed: {e}")
            return True, []  # Don't fail on style check
    
    def _parse_flake8_output(self, output: str) -> None:
        """Parse flake8 output
        
        中文: 解析flake8输出
        
        Args:
            output: flake8 output text
        """
        for line in output.strip().split('\n'):
            if not line:
                continue
            
            # Format: stdin:line:column: code message
            match = re.match(r'stdin:(\d+):(\d+): ([A-Z]\d+) (.*)', line)
            if match:
                line_no = int(match.group(1))
                column = int(match.group(2))
                code = match.group(3)
                message = match.group(4)
                
                severity = SeverityLevel.WARNING
                if code.startswith('E'):
                    severity = SeverityLevel.ERROR
                
                issue = ValidationIssue(
                    severity=severity,
                    code=code,
                    message_en=message,
                    line_no=line_no,
                    column=column,
                )
                self.issues.append(issue)
    
    def _basic_style_check(self, code: str) -> Tuple[bool, List[ValidationIssue]]:
        """Basic style checks without external tools
        
        中文: 不使用外部工具的基本风格检查
        
        Args:
            code: Code to check
        
        Returns:
            Tuple of (style_ok, issues)
        """
        issues = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, 1):
            # Check line length
            if len(line) > 120:
                issue = ValidationIssue(
                    severity=SeverityLevel.WARNING,
                    code="W002",
                    message_en=f"Line too long ({len(line)} > 120 characters)",
                    line_no=line_no,
                )
                issues.append(issue)
            
            # Check trailing whitespace
            if line.rstrip() != line:
                issue = ValidationIssue(
                    severity=SeverityLevel.WARNING,
                    code="W003",
                    message_en="Trailing whitespace",
                    line_no=line_no,
                )
                issues.append(issue)
        
        return len(issues) == 0, issues


class CodeValidator:
    """Comprehensive code validator
    
    中文: 综合代码验证器
    """
    
    def __init__(self):
        """Initialize code validator"""
        self.syntax_validator = SyntaxValidator()
        self.type_validator = TypeAnnotationValidator()
        self.import_validator = ImportValidator()
        self.style_validator = StyleValidator()
        self.all_issues: List[ValidationIssue] = []
    
    def validate(
        self,
        code: str,
        check_syntax: bool = True,
        check_types: bool = True,
        check_imports: bool = True,
        check_style: bool = True,
    ) -> Tuple[bool, List[ValidationIssue]]:
        """Validate code comprehensively
        
        中文: 全面验证代码
        
        Args:
            code: Code to validate
            check_syntax: Check syntax
            check_types: Check type annotations
            check_imports: Check imports
            check_style: Check code style
        
        Returns:
            Tuple of (all_valid, all_issues)
        """
        self.all_issues = []
        has_errors = False
        
        # Syntax check
        if check_syntax:
            valid, issues = self.syntax_validator.validate(code)
            self.all_issues.extend(issues)
            if not valid:
                has_errors = True
                return False, self.all_issues  # Stop on syntax error
        
        # Type check
        if check_types:
            valid, issues = self.type_validator.validate(code)
            self.all_issues.extend(issues)
        
        # Import check
        if check_imports:
            valid, issues = self.import_validator.validate(code)
            self.all_issues.extend(issues)
        
        # Style check
        if check_style:
            valid, issues = self.style_validator.validate(code)
            self.all_issues.extend(issues)
        
        # Return overall result
        has_errors = any(i.severity == SeverityLevel.ERROR for i in self.all_issues)
        return not has_errors, self.all_issues
    
    def generate_report(self) -> str:
        """Generate validation report
        
        中文: 生成验证报告
        
        Returns:
            Formatted report
        """
        if not self.all_issues:
            return "✓ All checks passed"
        
        lines = []
        
        # Group by severity
        errors = [i for i in self.all_issues if i.severity == SeverityLevel.ERROR]
        warnings = [i for i in self.all_issues if i.severity == SeverityLevel.WARNING]
        infos = [i for i in self.all_issues if i.severity == SeverityLevel.INFO]
        
        if errors:
            lines.append(f"\n❌ Errors ({len(errors)}):")
            for issue in errors:
                lines.append(f"  {issue}")
        
        if warnings:
            lines.append(f"\n⚠️  Warnings ({len(warnings)}):")
            for issue in warnings:
                lines.append(f"  {issue}")
        
        if infos:
            lines.append(f"\nℹ️  Info ({len(infos)}):")
            for issue in infos:
                lines.append(f"  {issue}")
        
        return "\n".join(lines)
