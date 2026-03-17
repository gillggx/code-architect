"""
Tier 1: In-Memory Cache (hot storage)

Fast in-memory structures with checksums for integrity.
Loaded from Tier 2 (persistent files) on startup.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


@dataclass
class SearchResultRef:
    """Reference to a search result"""
    
    artifact_id: str
    artifact_type: str  # "pattern", "edge_case", "module", etc.
    confidence: float
    relevance: float
    source_file: str


@dataclass
class MemoryTier1:
    """In-memory cache for project analysis"""
    
    project_id: str
    timestamp: datetime
    
    # Core structures
    project_index: Dict[str, Any] = field(default_factory=dict)
    patterns: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, Any] = field(default_factory=dict)
    edge_cases: Dict[str, Any] = field(default_factory=dict)
    decisions: Dict[str, Any] = field(default_factory=dict)
    entry_points: List[str] = field(default_factory=list)
    
    # Integrity tracking
    checksums: Dict[str, str] = field(default_factory=dict)
    versions: Dict[str, int] = field(default_factory=dict)
    last_verified: Optional[datetime] = None
    
    # Search/query cache
    search_index: Dict[str, List[SearchResultRef]] = field(default_factory=dict)
    query_cache: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    languages: List[str] = field(default_factory=list)
    files_analyzed: int = 0
    avg_confidence: float = 0.0
    
    def __post_init__(self):
        """Initialize timestamp if not provided"""
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def add_pattern(self, pattern_id: str, pattern: Dict[str, Any]):
        """Add pattern to memory"""
        self.patterns[pattern_id] = pattern
        self._invalidate_cache()
    
    def add_edge_case(self, case_id: str, edge_case: Dict[str, Any]):
        """Add edge case to memory"""
        self.edge_cases[case_id] = edge_case
        self._invalidate_cache()
    
    def search(self, query: str, confidence_threshold: float = 0.80) -> List[SearchResultRef]:
        """
        In-memory search across patterns, edge cases, and metadata
        
        Simple keyword-based search (Phase 1)
        Phase 2 will add BM25 + vector search
        """
        results = []
        query_lower = query.lower()
        
        # Search patterns
        for pattern_id, pattern in self.patterns.items():
            if self._matches(pattern, query_lower):
                confidence = pattern.get('confidence', 0.0)
                if confidence >= confidence_threshold:
                    results.append(SearchResultRef(
                        artifact_id=pattern_id,
                        artifact_type="pattern",
                        confidence=confidence,
                        relevance=self._calculate_relevance(pattern, query),
                        source_file=pattern.get('source_file', '')
                    ))
        
        # Search edge cases
        for case_id, edge_case in self.edge_cases.items():
            if self._matches(edge_case, query_lower):
                confidence = edge_case.get('confidence', 0.5)
                if confidence >= confidence_threshold:
                    results.append(SearchResultRef(
                        artifact_id=case_id,
                        artifact_type="edge_case",
                        confidence=confidence,
                        relevance=self._calculate_relevance(edge_case, query),
                        source_file=edge_case.get('source_file', '')
                    ))
        
        # Sort by relevance (descending)
        results.sort(key=lambda r: r.relevance, reverse=True)
        
        return results[:5]  # Top 5
    
    def compute_checksum(self) -> str:
        """Compute SHA256 checksum of all artifacts"""
        data = json.dumps({
            'patterns': self.patterns,
            'edge_cases': self.edge_cases,
            'dependencies': self.dependencies,
        }, sort_keys=True, default=str)
        
        return hashlib.sha256(data.encode()).hexdigest()
    
    def verify_integrity(self) -> bool:
        """Verify that checksums match"""
        current = self.compute_checksum()
        stored = self.checksums.get('all', '')
        
        if current != stored:
            logger.warning(f"Memory checksum mismatch: {current} != {stored}")
            return False
        
        self.last_verified = datetime.now()
        return True
    
    # ==================== Private Methods ====================
    
    def _invalidate_cache(self):
        """Invalidate search cache after modifications"""
        self.query_cache.clear()
    
    def _matches(self, artifact: Dict[str, Any], query_lower: str) -> bool:
        """Check if artifact matches query keywords"""
        
        # Search in name
        if 'name' in artifact and query_lower in artifact['name'].lower():
            return True
        
        # Search in description
        if 'description' in artifact and query_lower in artifact['description'].lower():
            return True
        
        # Search in evidence/samples
        evidence = artifact.get('evidence', [])
        if isinstance(evidence, list):
            for sample in evidence:
                if isinstance(sample, str) and query_lower in sample.lower():
                    return True
        
        return False
    
    def _calculate_relevance(self, artifact: Dict[str, Any], query: str) -> float:
        """Calculate relevance score (0.0-1.0)"""
        query_lower = query.lower()
        score = 0.0
        
        # Exact match in name: +1.0
        if 'name' in artifact and artifact['name'].lower() == query_lower:
            score += 1.0
        # Substring match in name: +0.8
        elif 'name' in artifact and query_lower in artifact['name'].lower():
            score += 0.8
        # Match in description: +0.5
        if 'description' in artifact and query_lower in artifact['description'].lower():
            score += 0.5
        
        # Confidence boost
        if 'confidence' in artifact:
            score += artifact['confidence'] * 0.2
        
        return min(score, 1.0)  # Cap at 1.0
