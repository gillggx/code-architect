"""Unit tests for language parsers"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from architect.parsers import ParserRegistry, PythonAnalyzer, LexicalAnalysis


class TestPythonAnalyzer:
    """Tests for Python analyzer"""
    
    @pytest.mark.asyncio
    async def test_lexical_scan_extracts_imports(self, sample_python_file, temp_project_dir):
        """Test that lexical scan extracts imports"""
        analyzer = PythonAnalyzer()
        analysis = await analyzer.lexical_scan(temp_project_dir)
        
        assert isinstance(analysis, LexicalAnalysis)
        assert analysis.language == "python"
        assert len(analysis.imports) > 0
    
    @pytest.mark.asyncio
    async def test_lexical_scan_extracts_definitions(self, sample_python_file, temp_project_dir):
        """Test that lexical scan extracts class definitions"""
        analyzer = PythonAnalyzer()
        analysis = await analyzer.lexical_scan(temp_project_dir)
        
        assert len(analysis.definitions) > 0
        # Check for MyClass definition
        definitions = [d for file_defs in analysis.definitions.values() for d in file_defs]
        assert any('MyClass' in d for d in definitions)
    
    @pytest.mark.asyncio
    async def test_lexical_scan_finds_entry_points(self, sample_python_file, temp_project_dir):
        """Test that lexical scan finds entry points"""
        analyzer = PythonAnalyzer()
        analysis = await analyzer.lexical_scan(temp_project_dir)
        
        # Should find if __name__ == "__main__":
        assert len(analysis.entry_points) > 0
    
    def test_identify_key_files(self, temp_project_dir):
        """Test key file identification"""
        analyzer = PythonAnalyzer()
        
        # Create a minimal LexicalAnalysis
        analysis = LexicalAnalysis(language="python")
        analysis.entry_points = [f"{temp_project_dir}/main.py"]
        analysis.imports = {
            f"{temp_project_dir}/module_a.py": ["os", "sys"],
            f"{temp_project_dir}/module_b.py": ["os"],
        }
        analysis.high_frequency_imports = {"os": 2, "sys": 1}
        
        key_files = analyzer.identify_key_files(analysis)
        
        assert len(key_files) > 0
        # Should include entry point
        assert any("main.py" in f for f in key_files)


class TestParserRegistry:
    """Tests for parser registry"""
    
    def test_get_analyzer_python(self):
        """Test getting Python analyzer"""
        registry = ParserRegistry()
        analyzer = registry.get_analyzer('python')
        
        assert analyzer is not None
        assert analyzer.language_name == 'python'
    
    def test_get_analyzer_cpp(self):
        """Test getting C++ analyzer"""
        registry = ParserRegistry()
        analyzer = registry.get_analyzer('cpp')
        
        assert analyzer is not None
        assert analyzer.language_name == 'cpp'
    
    def test_supported_languages(self):
        """Test that all 8 languages are supported"""
        registry = ParserRegistry()
        languages = registry.supported_languages()
        
        expected_languages = [
            'python', 'cpp', 'java', 'sql',
            'javascript', 'typescript', 'jsx', 'html'
        ]
        
        assert len(languages) == 8
        for lang in expected_languages:
            assert lang in languages
    
    def test_is_supported(self):
        """Test language support check"""
        registry = ParserRegistry()
        
        assert registry.is_supported('python')
        assert registry.is_supported('cpp')
        assert not registry.is_supported('cobol')
    
    @pytest.mark.asyncio
    async def test_analyze_project_lexical(self, sample_python_file, sample_cpp_file, temp_project_dir):
        """Test analyzing project across multiple languages"""
        registry = ParserRegistry()
        results = await registry.analyze_project_lexical(temp_project_dir)
        
        assert len(results) > 0
        # Should have results for at least Python and C++
        assert 'python' in results
        assert 'cpp' in results


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
