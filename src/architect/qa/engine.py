"""
Q&A Engine: Answer questions from project memory.

1. Query routing (classify query)
2. Memory search (find relevant info)
3. Response generation (synthesize answer)
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..memory.tier1 import MemoryTier1, SearchResultRef

logger = logging.getLogger(__name__)


@dataclass
class QAResponse:
    """Response to a user query"""
    
    query: str
    answer: str
    confidence: float
    sources: List[Dict[str, Any]]
    edge_cases: List[Dict[str, Any]]
    limitations: List[str]
    latency_ms: float
    timestamp: datetime


class QueryRouter:
    """Route queries intelligently"""
    
    @staticmethod
    def classify_complexity(query: str) -> str:
        """
        Classify query complexity:
        - simple: Single clause, factual (e.g., "Where is X?", "List Y")
        - moderate: Multi-clause, explanation needed (e.g., "How does X work?")
        - complex: Design, trade-offs, multiple concerns (e.g., "Design X", "Compare X vs Y")
        """
        
        query_lower = query.lower()
        sentence_count = query.count('.') + query.count('?')
        word_count = len(query.split())
        
        # Keywords
        has_design = any(w in query_lower for w in ['design', 'architect', 'build', 'create'])
        has_compare = any(w in query_lower for w in ['compare', 'vs', 'versus', 'difference'])
        has_explain = any(w in query_lower for w in ['how', 'explain', 'work', 'does', 'why'])
        has_how = 'how' in query_lower
        
        # Decision tree
        # Complex: design/architect questions, comparisons
        if has_design or has_compare:
            return 'complex'
        
        # Moderate: explanation questions with "how does"
        if has_how and has_explain and word_count > 4:
            return 'moderate'
        
        # Simple: factual questions
        return 'simple'
    
    @staticmethod
    def extract_intent(query: str) -> Dict[str, Any]:
        """Extract key information from query"""
        
        return {
            'query': query,
            'complexity': QueryRouter.classify_complexity(query),
            'keywords': QueryRouter._extract_keywords(query),
        }
    
    @staticmethod
    def _extract_keywords(query: str) -> List[str]:
        """Extract keywords from query"""
        
        # Simple tokenization (Phase 1)
        words = query.lower().split()
        
        # Filter stop words
        stop_words = {'how', 'does', 'what', 'is', 'the', 'a', 'and', 'or', 'in', 'at', 'to', 'for'}
        keywords = [w.strip('?:;,.') for w in words if w not in stop_words and len(w) > 2]
        
        return keywords


class ResponseGenerator:
    """Generate responses from memory search results"""
    
    @staticmethod
    def generate(
        query: str,
        search_results: List[SearchResultRef],
        memory: MemoryTier1
    ) -> QAResponse:
        """
        Generate response from search results
        
        Template:
        1. Main answer (synthesized from results)
        2. Sources (citations)
        3. Edge cases (if any)
        4. Limitations (what we don't know)
        """
        
        # Build answer from results
        answer_parts = []
        sources = []
        edge_cases = []
        
        for result in search_results:
            artifact = None
            
            if result.artifact_type == 'pattern':
                artifact = memory.patterns.get(result.artifact_id)
            elif result.artifact_type == 'edge_case':
                artifact = memory.edge_cases.get(result.artifact_id)
            
            if artifact:
                # Add to answer
                if 'description' in artifact:
                    answer_parts.append(f"- {artifact['description']}")
                
                # Track source
                sources.append({
                    'type': result.artifact_type,
                    'id': result.artifact_id,
                    'confidence': result.confidence,
                    'file': result.source_file,
                })
                
                # Extract edge cases
                if result.artifact_type == 'edge_case':
                    edge_cases.append({
                        'description': artifact.get('description', ''),
                        'handling': artifact.get('handling', ''),
                        'severity': artifact.get('severity', 'unknown'),
                    })
        
        # Synthesize answer
        if answer_parts:
            answer = "Based on the codebase analysis:\n\n" + "\n".join(answer_parts)
        else:
            answer = "Unable to find relevant information in memory. Fresh analysis may be needed."
        
        # Calculate confidence
        if search_results:
            avg_confidence = sum(r.confidence for r in search_results) / len(search_results)
        else:
            avg_confidence = 0.0
        
        # Limitations
        limitations = []
        if avg_confidence < 0.80:
            limitations.append("Low confidence due to limited search results")
        if not search_results:
            limitations.append("No relevant information found in memory")
        
        return QAResponse(
            query=query,
            answer=answer,
            confidence=avg_confidence,
            sources=sources,
            edge_cases=edge_cases,
            limitations=limitations,
            latency_ms=0.0,
            timestamp=datetime.now(),
        )


class QAEngine:
    """Main Q&A engine"""
    
    def __init__(self, memory: MemoryTier1):
        self.memory = memory
        self.query_router = QueryRouter()
        self.response_generator = ResponseGenerator()
    
    async def answer_query(self, query: str, confidence_threshold: float = 0.80) -> QAResponse:
        """
        Answer a user query from memory
        
        1. Parse intent
        2. Search memory
        3. Generate response
        """
        
        import time
        start_time = time.time()
        
        logger.info(f"Processing query: {query}")
        
        # Step 1: Extract intent
        intent = self.query_router.extract_intent(query)
        logger.info(f"  Complexity: {intent['complexity']}")
        logger.info(f"  Keywords: {intent['keywords']}")
        
        # Step 2: Search memory
        search_results = self.memory.search(query, confidence_threshold)
        logger.info(f"  Found {len(search_results)} results")
        
        # Step 3: Generate response
        response = self.response_generator.generate(query, search_results, self.memory)
        
        # Compute latency
        latency_ms = (time.time() - start_time) * 1000
        response.latency_ms = latency_ms
        
        logger.info(f"  Response confidence: {response.confidence:.2f}")
        logger.info(f"  Latency: {latency_ms:.1f}ms")
        
        return response
