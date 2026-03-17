"""End-to-end integration tests"""

import pytest
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from architect.parsers import ParserRegistry
from architect.memory import MemoryTier1, MemoryPersistenceManager
from architect.qa import QAEngine


@pytest.mark.asyncio
async def test_full_workflow(sample_python_file, sample_cpp_file, temp_project_dir, temp_memory_dir):
    """
    End-to-end test: Analyze project → Save memory → Load memory → Answer query
    """
    
    # Step 1: Analyze project (all 8 languages)
    registry = ParserRegistry()
    lexical_results = await registry.analyze_project_lexical(temp_project_dir)
    
    # Verify we got results for multiple languages
    assert len(lexical_results) >= 8  # All 8 languages
    assert 'python' in lexical_results
    assert 'cpp' in lexical_results
    
    # Check that Python analysis found something
    python_analysis = lexical_results['python']
    assert len(python_analysis.imports) > 0
    assert len(python_analysis.definitions) > 0
    
    # Step 2: Create memory with analysis results
    memory_tier1 = MemoryTier1(
        project_id="test_project",
        timestamp=datetime.now(),
        languages=['python', 'cpp'],
        files_analyzed=len(python_analysis.imports) + len(lexical_results['cpp'].imports),
        avg_confidence=0.90
    )
    
    # Add patterns (simulated from analysis)
    memory_tier1.add_pattern('factory_1', {
        'name': 'Factory Pattern',
        'description': 'Found in MyClass',
        'confidence': 0.85,
        'source_file': sample_python_file
    })
    
    memory_tier1.add_edge_case('edge_1', {
        'description': 'Empty input handling',
        'handling': 'Returns None',
        'confidence': 0.80,
        'severity': 'low'
    })
    
    # Step 3: Persist memory (Tier 1 → Tier 2)
    manager = MemoryPersistenceManager(temp_memory_dir)
    memory_tier1.checksums['all'] = memory_tier1.compute_checksum()
    
    success = await manager.save_to_tier2("test_project", memory_tier1)
    assert success
    
    # Step 4: Verify files were created
    proj_dir = os.path.join(temp_memory_dir, "test_project")
    assert os.path.exists(proj_dir)
    assert os.path.exists(os.path.join(proj_dir, 'PROJECT.md'))
    assert os.path.exists(os.path.join(proj_dir, 'PATTERNS.md'))
    
    # Step 5: Load memory (Tier 2 → Tier 1)
    loaded_memory = await manager.load_from_tier2("test_project")
    
    assert loaded_memory is not None
    assert loaded_memory.project_id == "test_project"
    assert loaded_memory.files_analyzed > 0
    assert 'factory_1' in loaded_memory.patterns
    assert 'edge_1' in loaded_memory.edge_cases
    
    # Step 6: Answer queries from loaded memory
    engine = QAEngine(loaded_memory)
    
    # Query 1: Factory pattern
    response1 = await engine.answer_query("factory pattern")
    assert response1.confidence > 0.0
    assert len(response1.sources) > 0
    
    # Query 2: Edge cases
    response2 = await engine.answer_query("empty input handling")
    assert response2.confidence > 0.0
    
    # Query 3: Non-existent pattern (should have low confidence)
    response3 = await engine.answer_query("nonexistent pattern xyz")
    # Will have low confidence since not in memory
    assert response3.confidence < 0.5


@pytest.mark.asyncio
async def test_multi_language_analysis(temp_project_dir):
    """Test that all 8 languages can be analyzed"""
    
    # Create test files for each language
    files = {
        'test.py': 'class MyClass: pass',
        'test.cpp': 'class MyClass {};',
        'Test.java': 'class Test {}',
        'test.sql': 'CREATE TABLE test (id INT);',
        'test.js': 'class MyClass {}',
        'test.ts': 'class MyClass {}',
        'test.jsx': 'function MyComponent() {}',
        'test.html': '<div>test</div>',
    }
    
    for filename, content in files.items():
        filepath = os.path.join(temp_project_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
    
    # Analyze
    registry = ParserRegistry()
    results = await registry.analyze_project_lexical(temp_project_dir)
    
    # Verify all languages were processed
    assert len(results) == 8
    
    # Each language should have some analysis (even if empty)
    for lang in ['python', 'cpp', 'java', 'sql', 'javascript', 'typescript', 'jsx', 'html']:
        assert lang in results
        assert results[lang] is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
