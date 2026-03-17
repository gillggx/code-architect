"""
Analyzers for Java, SQL, JavaScript, TypeScript, JSX, HTML.

Phase 1: Basic lexical analysis (Level 1-2)
Phase 2+: Advanced pattern detection (Level 3-5)
"""

import os
import re
from typing import Dict, List
import logging

from .base import LexicalAnalysis, LanguageAnalyzer

logger = logging.getLogger(__name__)


class JavaAnalyzer(LanguageAnalyzer):
    """Java code analyzer"""
    
    language_name = "java"
    file_extensions = [".java"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for Java files"""
        analysis = LexicalAnalysis(language="java")
        java_files = self._find_files(project_path, self.file_extensions)
        
        for java_file in java_files:
            try:
                with open(java_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                analysis.imports[java_file] = self._extract_imports(content)
                analysis.definitions[java_file] = self._extract_definitions(content)
                analysis.inheritance.update(self._extract_inheritance(content))
                
                if self._has_main(content):
                    analysis.entry_points.append(java_file)
                
            except Exception as e:
                analysis.errors.append({'file': java_file, 'error': str(e)})
        
        analysis.high_frequency_imports = self._calculate_frequency(analysis.imports)
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """Identify key Java files"""
        key_files = list(lexical.entry_points)
        
        # Add high-frequency imports
        for module, count in sorted(lexical.high_frequency_imports.items(), key=lambda x: -x[1]):
            if count >= 2 and len(key_files) < max_files:
                key_files.append(module)
        
        return list(dict.fromkeys(key_files))[:max_files]  # Deduplicate
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'target', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_imports(self, content: str) -> List[str]:
        pattern = r'import\s+([^\s;]+)'
        return list(set(re.findall(pattern, content)))
    
    def _extract_definitions(self, content: str) -> List[str]:
        defs = []
        for match in re.findall(r'(?:class|interface|enum)\s+(\w+)', content):
            defs.append(f"class {match}")
        return defs
    
    def _extract_inheritance(self, content: str) -> Dict[str, List[str]]:
        inheritance = {}
        for match in re.finditer(r'class\s+(\w+)\s+(?:extends|implements)\s+([^{]+)', content):
            class_name, parents_str = match.groups()
            parents = [p.strip() for p in parents_str.split(',')]
            inheritance[class_name] = parents
        return inheritance
    
    def _has_main(self, content: str) -> bool:
        return bool(re.search(r'public\s+static\s+void\s+main', content))
    
    def _calculate_frequency(self, imports_dict: Dict[str, List[str]]) -> Dict[str, int]:
        frequency = {}
        for imports in imports_dict.values():
            for imp in imports:
                module = imp.split('.')[0]
                frequency[module] = frequency.get(module, 0) + 1
        return frequency


class SqlAnalyzer(LanguageAnalyzer):
    """SQL code analyzer"""
    
    language_name = "sql"
    file_extensions = [".sql"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for SQL files"""
        analysis = LexicalAnalysis(language="sql")
        sql_files = self._find_files(project_path, self.file_extensions)
        
        for sql_file in sql_files:
            try:
                with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # SQL: extract table definitions, foreign keys, etc.
                analysis.definitions[sql_file] = self._extract_tables(content)
                analysis.imports[sql_file] = []  # SQL doesn't have imports in traditional sense
                
            except Exception as e:
                analysis.errors.append({'file': sql_file, 'error': str(e)})
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """Identify key SQL files (migrations, schemas)"""
        return list(lexical.definitions.keys())[:max_files]
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_tables(self, content: str) -> List[str]:
        """Extract CREATE TABLE statements"""
        tables = re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', content, re.IGNORECASE)
        return [f"table {t}" for t in set(tables)]


class JavaScriptAnalyzer(LanguageAnalyzer):
    """JavaScript code analyzer"""
    
    language_name = "javascript"
    file_extensions = [".js", ".mjs"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for JavaScript files"""
        analysis = LexicalAnalysis(language="javascript")
        js_files = self._find_files(project_path, self.file_extensions)
        
        for js_file in js_files:
            try:
                with open(js_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                analysis.imports[js_file] = self._extract_imports(content)
                analysis.definitions[js_file] = self._extract_definitions(content)
                
                if self._is_entry_point(js_file, content):
                    analysis.entry_points.append(js_file)
                
            except Exception as e:
                analysis.errors.append({'file': js_file, 'error': str(e)})
        
        analysis.high_frequency_imports = self._calculate_frequency(analysis.imports)
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """Identify key JavaScript files"""
        key_files = list(lexical.entry_points)
        
        for module, count in sorted(lexical.high_frequency_imports.items(), key=lambda x: -x[1]):
            if count >= 2 and len(key_files) < max_files:
                key_files.append(module)
        
        return list(dict.fromkeys(key_files))[:max_files]
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_imports(self, content: str) -> List[str]:
        imports = []
        # import / require patterns
        for match in re.findall(r'(?:import|require)\s*\(?[\'"]([^\'"]+)[\'"]', content):
            imports.append(match)
        return list(set(imports))
    
    def _extract_definitions(self, content: str) -> List[str]:
        defs = []
        # class definitions
        for match in re.findall(r'class\s+(\w+)', content):
            defs.append(f"class {match}")
        # function definitions
        for match in re.findall(r'(?:async\s+)?function\s+(\w+)', content):
            defs.append(f"function {match}")
        return defs
    
    def _is_entry_point(self, filename: str, content: str) -> bool:
        return filename.endswith('index.js') or filename.endswith('main.js')
    
    def _calculate_frequency(self, imports_dict: Dict[str, List[str]]) -> Dict[str, int]:
        frequency = {}
        for imports in imports_dict.values():
            for imp in imports:
                module = imp.split('/')[0]
                frequency[module] = frequency.get(module, 0) + 1
        return frequency


class TypeScriptAnalyzer(LanguageAnalyzer):
    """TypeScript code analyzer"""
    
    language_name = "typescript"
    file_extensions = [".ts"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for TypeScript files"""
        analysis = LexicalAnalysis(language="typescript")
        ts_files = self._find_files(project_path, self.file_extensions)
        
        for ts_file in ts_files:
            try:
                with open(ts_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                analysis.imports[ts_file] = self._extract_imports(content)
                analysis.definitions[ts_file] = self._extract_definitions(content)
                
            except Exception as e:
                analysis.errors.append({'file': ts_file, 'error': str(e)})
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        return list(lexical.definitions.keys())[:max_files]
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_imports(self, content: str) -> List[str]:
        imports = []
        for match in re.findall(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content):
            imports.append(match)
        return list(set(imports))
    
    def _extract_definitions(self, content: str) -> List[str]:
        defs = []
        for match in re.findall(r'(?:class|interface|type|enum)\s+(\w+)', content):
            defs.append(f"class {match}")
        return defs


class JsxAnalyzer(LanguageAnalyzer):
    """React/JSX code analyzer"""
    
    language_name = "jsx"
    file_extensions = [".jsx", ".tsx"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for JSX/TSX files"""
        analysis = LexicalAnalysis(language="jsx")
        jsx_files = self._find_files(project_path, self.file_extensions)
        
        for jsx_file in jsx_files:
            try:
                with open(jsx_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                analysis.imports[jsx_file] = self._extract_imports(content)
                analysis.definitions[jsx_file] = self._extract_components(content)
                
            except Exception as e:
                analysis.errors.append({'file': jsx_file, 'error': str(e)})
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        return list(lexical.definitions.keys())[:max_files]
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_imports(self, content: str) -> List[str]:
        imports = []
        for match in re.findall(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content):
            imports.append(match)
        return list(set(imports))
    
    def _extract_components(self, content: str) -> List[str]:
        """Extract React component definitions"""
        components = []
        
        # Functional components
        for match in re.findall(r'(?:const|function)\s+(\w+)\s*=?\s*(?:\(|function)', content):
            if match[0].isupper():  # Components start with capital
                components.append(f"component {match}")
        
        return components


class HtmlAnalyzer(LanguageAnalyzer):
    """HTML code analyzer"""
    
    language_name = "html"
    file_extensions = [".html", ".htm"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """Lexical analysis for HTML files"""
        analysis = LexicalAnalysis(language="html")
        html_files = self._find_files(project_path, self.file_extensions)
        
        for html_file in html_files:
            try:
                with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                analysis.definitions[html_file] = self._extract_tags(content)
                analysis.imports[html_file] = self._extract_external_refs(content)
                
            except Exception as e:
                analysis.errors.append({'file': html_file, 'error': str(e)})
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        return list(lexical.definitions.keys())[:max_files]
    
    def _find_files(self, project_path: str, extensions: List[str]) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__']]
            for f in filenames:
                if any(f.endswith(ext) for ext in extensions):
                    files.append(os.path.join(root, f))
        return sorted(files)
    
    def _extract_tags(self, content: str) -> List[str]:
        """Extract HTML tag usage"""
        tags = re.findall(r'<(\w+)(?:\s|>)', content)
        return [f"tag {t}" for t in set(tags)]
    
    def _extract_external_refs(self, content: str) -> List[str]:
        """Extract script and link references"""
        refs = []
        refs.extend(re.findall(r'<script\s+src=[\'"]([^\'"]+)[\'"]', content))
        refs.extend(re.findall(r'<link\s+href=[\'"]([^\'"]+)[\'"]', content))
        return list(set(refs))
