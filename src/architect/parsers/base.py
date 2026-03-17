"""
Base parser interface for all supported languages.

All 8 languages must implement 5 analysis levels:
1. Level 1: Syntactic structure (AST parsing)
2. Level 2: Semantic relationships (types, inheritance)
3. Level 3: Pattern detection (15+ patterns per category)
4. Level 4: Edge case analysis (boundary conditions)
5. Level 5: Integration documentation (how components interact)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from datetime import datetime


@dataclass
class LexicalAnalysis:
    """Level 1: Syntactic structure from AST parsing"""
    
    language: str
    imports: Dict[str, List[str]] = field(default_factory=dict)  # file -> [imports]
    definitions: Dict[str, List[str]] = field(default_factory=dict)  # file -> [classes/funcs]
    inheritance: Dict[str, List[str]] = field(default_factory=dict)  # class -> [parents]
    entry_points: List[str] = field(default_factory=list)  # Main files
    config_files: List[str] = field(default_factory=list)  # Config files
    high_frequency_imports: Dict[str, int] = field(default_factory=dict)  # module -> count
    errors: List[Dict[str, str]] = field(default_factory=list)  # Parse errors
    
    def __post_init__(self):
        """Validate language support"""
        valid_languages = ['python', 'cpp', 'java', 'sql', 'javascript', 'typescript', 'jsx', 'html']
        if self.language not in valid_languages:
            raise ValueError(f"Unsupported language: {self.language}")


@dataclass
class Pattern:
    """Detected architectural pattern"""
    
    id: str
    name: str  # "Singleton", "Factory", "Decorator", etc.
    language: str
    evidence: List[str]  # Code samples showing pattern
    confidence: float  # 0.0-1.0
    implementations: List[str] = field(default_factory=list)  # Where found
    description: str = ""
    category: str = ""  # "OOP", "Async", "Middleware", etc.
    
    def __post_init__(self):
        assert 0.0 <= self.confidence <= 1.0, "Confidence must be 0.0-1.0"


@dataclass
class EdgeCase:
    """Known boundary condition / error path"""
    
    id: str
    description: str  # "Empty input", "Concurrent access", etc.
    handling: str  # How it's handled
    confidence: float  # How sure we are
    severity: str = "low"  # low, medium, high
    
    def __post_init__(self):
        assert 0.0 <= self.confidence <= 1.0
        assert self.severity in ['low', 'medium', 'high']


@dataclass
class SemanticAnalysis:
    """Levels 2-5: Semantic understanding from lexical + LLM"""
    
    patterns: List[Pattern] = field(default_factory=list)
    edge_cases: List[EdgeCase] = field(default_factory=list)
    integration_points: List[str] = field(default_factory=list)
    error_handling_strategies: List[str] = field(default_factory=list)
    summary: str = ""
    
    def avg_confidence(self) -> float:
        """Average confidence across all patterns"""
        if not self.patterns:
            return 0.0
        return sum(p.confidence for p in self.patterns) / len(self.patterns)


@dataclass
class ProjectAnalysis:
    """Complete project analysis (all files, all languages)"""
    
    project_id: str
    project_path: str
    timestamp: datetime
    languages: Set[str] = field(default_factory=set)
    files_analyzed: int = 0
    key_files: List[str] = field(default_factory=list)
    
    lexical_results: Dict[str, LexicalAnalysis] = field(default_factory=dict)  # lang -> analysis
    semantic_results: Dict[str, List[SemanticAnalysis]] = field(default_factory=dict)  # file -> analyses
    
    all_patterns: Dict[str, Pattern] = field(default_factory=dict)  # pattern_id -> pattern
    all_edge_cases: Dict[str, EdgeCase] = field(default_factory=dict)
    
    confidence_scores: Dict[str, float] = field(default_factory=dict)  # file -> confidence
    
    def avg_confidence(self) -> float:
        """Project-wide average confidence"""
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores.values()) / len(self.confidence_scores)


class LanguageAnalyzer(ABC):
    """Base class for language-specific analyzers"""
    
    language_name: str
    file_extensions: List[str]
    
    @abstractmethod
    async def lexical_scan(self, project_path: str) -> LexicalAnalysis:
        """
        Level 1: Scan all files with lexical analysis (AST parsing)
        
        Returns syntactic structure:
        - Imports
        - Class/function definitions
        - Inheritance relationships
        - Entry points
        - Configuration files
        """
        pass
    
    @abstractmethod
    def identify_key_files(self, lexical: LexicalAnalysis, max_files: int = 20) -> List[str]:
        """
        Identify top key files for semantic analysis using language-specific heuristics
        
        Examples:
        - Python: main.py, app.py, entry points, high-frequency imports
        - JavaScript: package.json main field, index.js, framework entry points
        - C++: main.cpp, headers with public classes
        """
        pass
    
    def analyze_level1_syntax(self, analysis: LexicalAnalysis) -> Dict[str, Any]:
        """Verify Level 1 analysis completeness"""
        return {
            'has_imports': len(analysis.imports) > 0,
            'has_definitions': len(analysis.definitions) > 0,
            'has_entry_points': len(analysis.entry_points) > 0,
            'parse_errors': len(analysis.errors),
        }
    
    def analyze_level2_semantics(self, lexical: LexicalAnalysis) -> Dict[str, Any]:
        """Level 2: Extract semantic relationships (types, inheritance)"""
        return {
            'has_inheritance': len(lexical.inheritance) > 0,
            'inheritance_depth': max(len(parents) for parents in lexical.inheritance.values()) if lexical.inheritance else 0,
            'total_imports': sum(len(imports) for imports in lexical.imports.values()),
        }
    
    @staticmethod
    def is_supported(file_path: str, extensions: List[str]) -> bool:
        """Check if file is supported by this analyzer"""
        return any(file_path.endswith(ext) for ext in extensions)


# Error handling (graceful degradation)
class UnsupportedLanguageError(Exception):
    """Raised when language is not supported"""
    pass


class ParserError(Exception):
    """Raised when parsing fails"""
    pass
