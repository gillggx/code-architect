"""
Python-specific code analyzer.

Level 1: Syntactic structure using ast module
Level 2: Semantic relationships (inheritance, types, async)
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Any
from datetime import datetime
import logging

from .base import (
    LexicalAnalysis,
    LanguageAnalyzer,
    ParserError,
)

logger = logging.getLogger(__name__)


class PythonAnalyzer(LanguageAnalyzer):
    """Python code analyzer using Python's built-in ast module"""
    
    language_name = "python"
    file_extensions = [".py"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """
        Level 1: Scan all .py files for syntactic structure
        
        Extracts:
        - Imports (from, import statements)
        - Classes and functions
        - Inheritance relationships
        - Async functions (async def)
        - Entry points (if __name__ == "__main__":)
        - Configuration files (setup.py, etc.)
        """
        analysis = LexicalAnalysis(language="python")
        
        # Find all .py files
        py_files = self._find_python_files(project_path)
        
        if not py_files:
            logger.warning(f"No Python files found in {project_path}")
            return analysis
        
        # Analyze each file
        for py_file in py_files:
            try:
                tree = self._parse_file(py_file)
                
                # Extract imports
                imports = self._extract_imports(tree)
                analysis.imports[py_file] = imports
                
                # Extract definitions (classes, functions)
                definitions = self._extract_definitions(tree)
                analysis.definitions[py_file] = definitions
                
                # Extract inheritance
                inheritance = self._extract_inheritance(tree)
                analysis.inheritance.update(inheritance)
                
                # Detect async functions
                has_async = self._has_async(tree)
                
                # Check for entry point
                if self._has_main_block(tree):
                    analysis.entry_points.append(py_file)
                
                # Check for config files
                if os.path.basename(py_file) in ["setup.py", "pyproject.toml", "__main__.py"]:
                    analysis.config_files.append(py_file)
                
            except ParserError as e:
                analysis.errors.append({
                    'file': py_file,
                    'error': str(e)
                })
                logger.error(f"Failed to parse {py_file}: {e}")
            except Exception as e:
                analysis.errors.append({
                    'file': py_file,
                    'error': f"Unexpected error: {str(e)}"
                })
                logger.error(f"Unexpected error in {py_file}: {e}")
        
        # Calculate import frequency
        analysis.high_frequency_imports = self._calculate_import_frequency(analysis.imports)
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """
        Identify Python key files by heuristics:
        1. Entry points (main.py, __main__.py, if __name__ == "__main__":)
        2. High-frequency imports (imported by >3 modules)
        3. Config files (setup.py, __init__.py)
        """
        key_files = []
        
        # Priority 1: Entry points
        for entry_point in lexical.entry_points:
            key_files.append(entry_point)
        
        # Priority 2: High-frequency imports
        for module, count in sorted(
            lexical.high_frequency_imports.items(),
            key=lambda x: -x[1]
        ):
            if count >= 2 and len(key_files) < max_files:
                key_files.append(module)
        
        # Priority 3: Config files
        for config in lexical.config_files:
            if len(key_files) < max_files:
                key_files.append(config)
        
        # Remove duplicates while preserving order
        seen = set()
        result = []
        for f in key_files:
            if f not in seen:
                result.append(f)
                seen.add(f)
        
        return result[:max_files]
    
    # ==================== Helper Methods ====================
    
    def _find_python_files(self, project_path: str) -> List[str]:
        """Find all .py files in project"""
        py_files = []
        
        for root, dirs, files in os.walk(project_path):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'venv', 'node_modules', '.pytest_cache']]
            
            for file in files:
                if file.endswith('.py'):
                    py_files.append(os.path.join(root, file))
        
        return sorted(py_files)
    
    def _parse_file(self, file_path: str) -> ast.Module:
        """Parse a single Python file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            return tree
        
        except SyntaxError as e:
            raise ParserError(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            raise ParserError(f"Failed to parse {file_path}: {e}")
    
    def _extract_imports(self, tree: ast.Module) -> List[str]:
        """Extract all imports from AST"""
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # import x, y, z
                for alias in node.names:
                    imports.append(alias.name)
            
            elif isinstance(node, ast.ImportFrom):
                # from x import y
                module = node.module or ''
                for alias in node.names:
                    if alias.name != '*':
                        imports.append(f"{module}.{alias.name}")
        
        return list(set(imports))  # Remove duplicates
    
    def _extract_definitions(self, tree: ast.Module) -> List[str]:
        """Extract class and function definitions"""
        definitions = []
        
        for node in tree.body:  # Top-level only
            if isinstance(node, ast.ClassDef):
                definitions.append(f"class {node.name}")
            elif isinstance(node, ast.FunctionDef):
                definitions.append(f"def {node.name}")
            elif isinstance(node, ast.AsyncFunctionDef):
                definitions.append(f"async def {node.name}")
        
        return definitions
    
    def _extract_inheritance(self, tree: ast.Module) -> Dict[str, List[str]]:
        """Extract class inheritance relationships"""
        inheritance = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                parents = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        parents.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        parents.append(base.attr)
                
                if parents:
                    inheritance[node.name] = parents
        
        return inheritance
    
    def _has_async(self, tree: ast.Module) -> bool:
        """Check if file uses async/await"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncWith, ast.AsyncFor)):
                return True
        return False
    
    def _has_main_block(self, tree: ast.Module) -> bool:
        """Check if file has if __name__ == '__main__': block"""
        for node in tree.body:
            if isinstance(node, ast.If):
                # Check for __name__ == "__main__" or __name__ == '__main__'
                if self._is_main_check(node.test):
                    return True
        return False
    
    def _is_main_check(self, node: ast.expr) -> bool:
        """Check if expression is __name__ == '__main__'"""
        if isinstance(node, ast.Compare):
            left = node.left
            if isinstance(left, ast.Name) and left.id == '__name__':
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant):
                        if comparator.value == '__main__':
                            return True
        return False
    
    def _calculate_import_frequency(self, imports_dict: Dict[str, List[str]]) -> Dict[str, int]:
        """Calculate how many files import each module"""
        frequency = {}
        
        for imports in imports_dict.values():
            for imp in imports:
                # Get module name (first component)
                module = imp.split('.')[0]
                frequency[module] = frequency.get(module, 0) + 1
        
        return frequency
