"""
C++ code analyzer (Phase 1: Basic implementation).

Phase 1: Level 1-2 analysis (syntactic + basic semantic)
Phase 2: Level 3-5 (pattern detection, edge cases, integration)
"""

import os
import re
from typing import Dict, List
import logging

from .base import LexicalAnalysis, LanguageAnalyzer, ParserError

logger = logging.getLogger(__name__)


class CppAnalyzer(LanguageAnalyzer):
    """C++ code analyzer using regex-based lexical scanning (Phase 1)"""
    
    language_name = "cpp"
    file_extensions = [".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"]
    
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """
        Level 1: Lexical analysis of C++ files
        
        Extracts (regex-based, Phase 1):
        - #include statements
        - class/struct definitions
        - namespace declarations
        - function definitions
        
        Note: Phase 2 will use tree-sitter for full AST parsing
        """
        analysis = LexicalAnalysis(language="cpp")
        
        cpp_files = self._find_cpp_files(project_path)
        
        if not cpp_files:
            logger.info(f"No C++ files found in {project_path}")
            return analysis
        
        for cpp_file in cpp_files:
            try:
                with open(cpp_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Extract includes
                includes = self._extract_includes(content)
                analysis.imports[cpp_file] = includes
                
                # Extract definitions (classes, structs, functions)
                definitions = self._extract_definitions(content)
                analysis.definitions[cpp_file] = definitions
                
                # Check for main
                if self._has_main(content):
                    analysis.entry_points.append(cpp_file)
                
                # CMakeLists.txt is config
                if cpp_file.endswith('CMakeLists.txt'):
                    analysis.config_files.append(cpp_file)
                
            except Exception as e:
                analysis.errors.append({
                    'file': cpp_file,
                    'error': f"Analysis failed: {str(e)}"
                })
                logger.error(f"Failed to analyze {cpp_file}: {e}")
        
        analysis.high_frequency_imports = self._calculate_import_frequency(analysis.imports)
        
        return analysis
    
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """Identify key C++ files"""
        key_files = []
        
        # Priority 1: Entry points (main.cpp)
        key_files.extend(lexical.entry_points)
        
        # Priority 2: Headers with public classes
        headers = [f for f in lexical.definitions.keys() if f.endswith('.h') or f.endswith('.hpp')]
        key_files.extend(headers[:10])
        
        # Priority 3: Config files (CMakeLists.txt)
        key_files.extend(lexical.config_files)
        
        # Deduplicate
        seen = set()
        result = []
        for f in key_files:
            if f not in seen:
                result.append(f)
                seen.add(f)
        
        return result[:max_files]
    
    # ==================== Helper Methods ====================
    
    def _find_cpp_files(self, project_path: str) -> List[str]:
        """Find all C++ files"""
        cpp_files = []
        
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['.git', 'build', '.venv', '__pycache__']]
            
            for file in files:
                if any(file.endswith(ext) for ext in self.file_extensions):
                    cpp_files.append(os.path.join(root, file))
                elif file == 'CMakeLists.txt':
                    cpp_files.append(os.path.join(root, file))
        
        return sorted(cpp_files)
    
    def _extract_includes(self, content: str) -> List[str]:
        """Extract #include directives"""
        includes = []
        
        # #include <...> or #include "..."
        pattern = r'#include\s+[<"]([^>"]+)[>"]'
        matches = re.findall(pattern, content)
        includes.extend(matches)
        
        return list(set(includes))
    
    def _extract_definitions(self, content: str) -> List[str]:
        """Extract class/struct/function definitions (regex-based)"""
        definitions = []
        
        # Simple regex for class definitions
        class_pattern = r'(?:class|struct)\s+(\w+)'
        class_matches = re.findall(class_pattern, content)
        for match in class_matches:
            definitions.append(f"class {match}")
        
        # Function definitions (simple heuristic)
        func_pattern = r'(?:void|int|bool|auto|[\w:]+)\s+(\w+)\s*\('
        func_matches = re.findall(func_pattern, content)
        for match in func_matches[:20]:  # Limit to avoid noise
            if match not in ['if', 'while', 'for', 'switch']:  # Filter keywords
                definitions.append(f"func {match}")
        
        return list(set(definitions))
    
    def _has_main(self, content: str) -> bool:
        """Check if file has main function"""
        return bool(re.search(r'int\s+main\s*\(', content))
    
    def _calculate_import_frequency(self, imports_dict: Dict[str, List[str]]) -> Dict[str, int]:
        """Calculate import frequency"""
        frequency = {}
        
        for imports in imports_dict.values():
            for imp in imports:
                frequency[imp] = frequency.get(imp, 0) + 1
        
        return frequency
