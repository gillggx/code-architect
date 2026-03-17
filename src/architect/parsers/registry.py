"""
Parser registry for all 8 supported languages.

Maintains a registry of language analyzers and provides unified interface.
All languages must implement equal depth analysis (5 levels).
"""

import logging
from typing import Dict, Optional
from .base import LanguageAnalyzer, UnsupportedLanguageError, LexicalAnalysis
from .python_analyzer import PythonAnalyzer
from .cpp_analyzer import CppAnalyzer
from .other_analyzers import (
    JavaAnalyzer,
    SqlAnalyzer,
    JavaScriptAnalyzer,
    TypeScriptAnalyzer,
    JsxAnalyzer,
    HtmlAnalyzer,
)

logger = logging.getLogger(__name__)

# All 8 supported languages (equal priority)
SUPPORTED_LANGUAGES = [
    'python',
    'cpp',
    'java',
    'sql',
    'javascript',
    'typescript',
    'jsx',
    'html',
]


class ParserRegistry:
    """Registry of language analyzers"""
    
    def __init__(self):
        self._analyzers: Dict[str, LanguageAnalyzer] = {
            'python': PythonAnalyzer(),
            'cpp': CppAnalyzer(),
            'java': JavaAnalyzer(),
            'sql': SqlAnalyzer(),
            'javascript': JavaScriptAnalyzer(),
            'typescript': TypeScriptAnalyzer(),
            'jsx': JsxAnalyzer(),
            'html': HtmlAnalyzer(),
        }
    
    def get_analyzer(self, language: str) -> LanguageAnalyzer:
        """Get analyzer for language"""
        if language not in self._analyzers:
            raise UnsupportedLanguageError(f"Language {language} not supported")
        return self._analyzers[language]
    
    def is_supported(self, language: str) -> bool:
        """Check if language is supported"""
        return language in self._analyzers
    
    def supported_languages(self) -> list:
        """Get list of all supported languages"""
        return list(self._analyzers.keys())
    
    async def analyze_project_lexical(self, project_path: str) -> Dict[str, LexicalAnalysis]:
        """
        Analyze entire project across all 8 languages
        
        Returns lexical analysis for each language
        """
        results = {}
        
        for lang, analyzer in self._analyzers.items():
            try:
                logger.info(f"Lexical scan for {lang}...")
                analysis = await analyzer.lexical_scan(project_path)
                results[lang] = analysis
                
                logger.info(f"  Files analyzed: {len(analysis.imports)}")
                logger.info(f"  Parse errors: {len(analysis.errors)}")
                logger.info(f"  Entry points: {len(analysis.entry_points)}")
                
            except Exception as e:
                logger.error(f"Failed to analyze {lang}: {e}")
                # Continue with other languages (graceful degradation)
                results[lang] = LexicalAnalysis(language=lang)
                results[lang].errors.append({
                    'file': 'all',
                    'error': f"Analysis failed: {str(e)}"
                })
        
        return results
