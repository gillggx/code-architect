"""Unit tests for memory system"""

import pytest
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from architect.memory import MemoryTier1, SearchResultRef, MemoryPersistenceManager


class TestMemoryTier1:
    """Tests for in-memory cache"""
    
    def test_create_memory(self):
        """Test creating memory instance"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        assert memory.project_id == "test_project"
        assert memory.timestamp is not None
    
    def test_add_pattern(self):
        """Test adding patterns to memory"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        pattern = {
            'name': 'Singleton',
            'description': 'Singleton pattern found',
            'confidence': 0.95
        }
        
        memory.add_pattern('singleton_1', pattern)
        
        assert 'singleton_1' in memory.patterns
        assert memory.patterns['singleton_1']['name'] == 'Singleton'
    
    def test_add_edge_case(self):
        """Test adding edge cases"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        edge_case = {
            'description': 'Empty input',
            'handling': 'Returns empty list',
            'confidence': 0.85,
            'severity': 'low'
        }
        
        memory.add_edge_case('edge_1', edge_case)
        
        assert 'edge_1' in memory.edge_cases
        assert memory.edge_cases['edge_1']['description'] == 'Empty input'
    
    def test_search_empty_memory(self):
        """Test searching empty memory"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        results = memory.search("some query")
        
        assert len(results) == 0
    
    def test_search_finds_pattern(self):
        """Test search finds pattern"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        pattern = {
            'name': 'Factory Pattern',
            'description': 'Factory pattern for object creation',
            'confidence': 0.95,
            'source_file': 'patterns.md'
        }
        
        memory.add_pattern('factory_1', pattern)
        
        results = memory.search("factory")
        
        assert len(results) > 0
        assert results[0].artifact_id == 'factory_1'
    
    def test_search_respects_confidence_threshold(self):
        """Test search respects confidence threshold"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        # Low confidence pattern
        pattern = {
            'name': 'Possible Singleton',
            'description': 'Might be singleton',
            'confidence': 0.50,
            'source_file': 'patterns.md'
        }
        
        memory.add_pattern('low_conf', pattern)
        
        # Search with high threshold
        results = memory.search("singleton", confidence_threshold=0.80)
        assert len(results) == 0
        
        # Search with low threshold
        results = memory.search("singleton", confidence_threshold=0.40)
        assert len(results) > 0
    
    def test_compute_checksum(self):
        """Test checksum computation"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        pattern = {
            'name': 'Test Pattern',
            'confidence': 0.90,
        }
        
        memory.add_pattern('test_1', pattern)
        
        checksum1 = memory.compute_checksum()
        assert isinstance(checksum1, str)
        assert len(checksum1) == 64  # SHA256 hex
        
        # Same content → same checksum
        memory2 = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        memory2.add_pattern('test_1', pattern)
        checksum2 = memory2.compute_checksum()
        
        assert checksum1 == checksum2
    
    def test_verify_integrity(self):
        """Test integrity verification"""
        memory = MemoryTier1(
            project_id="test_project",
            timestamp=datetime.now()
        )
        
        pattern = {'name': 'Test', 'confidence': 0.90}
        memory.add_pattern('test_1', pattern)
        
        # Store checksum
        memory.checksums['all'] = memory.compute_checksum()
        
        # Verify should pass
        assert memory.verify_integrity()


class TestMemoryPersistence:
    """Tests for Tier 1 ↔ Tier 2 synchronization"""
    
    @pytest.mark.asyncio
    async def test_save_to_tier2(self, temp_memory_dir):
        """Test saving to persistent storage"""
        manager = MemoryPersistenceManager(temp_memory_dir)
        
        memory = MemoryTier1(
            project_id="test_proj",
            timestamp=datetime.now(),
            files_analyzed=10,
            languages=['python', 'cpp']
        )
        
        pattern = {
            'name': 'Test Pattern',
            'confidence': 0.95,
            'description': 'A test pattern'
        }
        memory.add_pattern('pat_1', pattern)
        
        # Save
        success = await manager.save_to_tier2("test_proj", memory)
        assert success
        
        # Check files were created
        proj_dir = os.path.join(temp_memory_dir, "test_proj")
        assert os.path.exists(os.path.join(proj_dir, 'PROJECT.md'))
        assert os.path.exists(os.path.join(proj_dir, 'PATTERNS.md'))
    
    @pytest.mark.asyncio
    async def test_load_from_tier2(self, temp_memory_dir):
        """Test loading from persistent storage"""
        manager = MemoryPersistenceManager(temp_memory_dir)
        
        # First save
        memory = MemoryTier1(
            project_id="test_proj",
            timestamp=datetime.now(),
            files_analyzed=5
        )
        
        pattern = {'name': 'Singleton', 'confidence': 0.88}
        memory.add_pattern('sing_1', pattern)
        memory.checksums['all'] = memory.compute_checksum()
        
        await manager.save_to_tier2("test_proj", memory)
        
        # Then load
        loaded = await manager.load_from_tier2("test_proj")
        
        assert loaded is not None
        assert loaded.project_id == "test_proj"
        assert loaded.files_analyzed == 5
        assert 'sing_1' in loaded.patterns
    
    @pytest.mark.asyncio
    async def test_load_nonexistent_project(self, temp_memory_dir):
        """Test loading nonexistent project returns None"""
        manager = MemoryPersistenceManager(temp_memory_dir)
        
        loaded = await manager.load_from_tier2("nonexistent")
        
        assert loaded is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
