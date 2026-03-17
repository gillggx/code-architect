"""Unit tests for Q&A engine"""

import pytest
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from architect.qa import QueryRouter, ResponseGenerator, QAEngine
from architect.memory import MemoryTier1


class TestQueryRouter:
    """Tests for query routing"""
    
    def test_classify_simple_query(self):
        """Test classifying simple query"""
        complexity = QueryRouter.classify_complexity("Where is the auth module?")
        assert complexity == "simple"
    
    def test_classify_moderate_query(self):
        """Test classifying moderate complexity query"""
        complexity = QueryRouter.classify_complexity("How does request validation work in the auth module?")
        assert complexity == "moderate"
    
    def test_classify_complex_query(self):
        """Test classifying complex query"""
        complexity = QueryRouter.classify_complexity("Design a new payment processor following the current architecture patterns.")
        assert complexity == "complex"
    
    def test_extract_intent(self):
        """Test extracting intent from query"""
        intent = QueryRouter.extract_intent("How does authentication work?")
        
        assert 'query' in intent
        assert 'complexity' in intent
        assert 'keywords' in intent
        assert len(intent['keywords']) > 0
    
    def test_extract_keywords(self):
        """Test keyword extraction"""
        keywords = QueryRouter._extract_keywords("How does database connection pooling work?")
        
        assert len(keywords) > 0
        assert 'database' in keywords
        assert 'connection' in keywords
        # Stop words should be filtered
        assert 'how' not in keywords
        assert 'does' not in keywords


class TestResponseGenerator:
    """Tests for response generation"""
    
    def test_generate_from_empty_results(self):
        """Test generating response with no search results"""
        memory = MemoryTier1(
            project_id="test",
            timestamp=datetime.now()
        )
        
        response = ResponseGenerator.generate(
            "test query",
            [],
            memory
        )
        
        assert response.query == "test query"
        assert response.confidence == 0.0
        assert len(response.limitations) > 0
    
    def test_generate_from_pattern_results(self):
        """Test generating response from pattern results"""
        memory = MemoryTier1(
            project_id="test",
            timestamp=datetime.now()
        )
        
        # Add pattern
        pattern = {
            'description': 'Singleton pattern used for database connection',
            'confidence': 0.95
        }
        memory.add_pattern('pat_1', pattern)
        
        # Create search result
        from architect.memory import SearchResultRef
        result = SearchResultRef(
            artifact_id='pat_1',
            artifact_type='pattern',
            confidence=0.95,
            relevance=0.9,
            source_file='patterns.md'
        )
        
        response = ResponseGenerator.generate("singleton", [result], memory)
        
        assert response.confidence >= 0.90
        assert len(response.sources) > 0
        assert 'Singleton' in response.answer or 'pattern' in response.answer.lower()


class TestQAEngine:
    """Tests for complete Q&A engine"""
    
    @pytest.mark.asyncio
    async def test_answer_empty_memory(self):
        """Test answering query on empty memory"""
        memory = MemoryTier1(
            project_id="test",
            timestamp=datetime.now()
        )
        
        engine = QAEngine(memory)
        response = await engine.answer_query("test query")
        
        assert response.query == "test query"
        assert response.confidence == 0.0
        assert response.latency_ms >= 0
    
    @pytest.mark.asyncio
    async def test_answer_with_pattern(self):
        """Test answering query with patterns in memory"""
        memory = MemoryTier1(
            project_id="test",
            timestamp=datetime.now()
        )
        
        # Add pattern
        pattern = {
            'name': 'Factory Pattern',
            'description': 'Factory pattern for creating objects',
            'confidence': 0.92
        }
        memory.add_pattern('factory', pattern)
        
        engine = QAEngine(memory)
        response = await engine.answer_query("factory pattern")
        
        assert response.query == "factory pattern"
        assert response.confidence >= 0.8
        assert len(response.sources) > 0
    
    @pytest.mark.asyncio
    async def test_answer_respects_confidence_threshold(self):
        """Test that answer respects confidence threshold"""
        memory = MemoryTier1(
            project_id="test",
            timestamp=datetime.now()
        )
        
        # Add low confidence pattern
        pattern = {
            'name': 'Unknown Pattern',
            'description': 'Might be a pattern',
            'confidence': 0.40
        }
        memory.add_pattern('unknown', pattern)
        
        engine = QAEngine(memory)
        
        # High threshold → no results
        response_high = await engine.answer_query("pattern", confidence_threshold=0.80)
        assert response_high.confidence < 0.80
        
        # Low threshold → results
        response_low = await engine.answer_query("pattern", confidence_threshold=0.30)
        # Should find something or at least not fail
        assert response_low is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
