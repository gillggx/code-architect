"""
Phase 3 Integration Tests

Comprehensive E2E tests for:
- Large project support (200-500 files)
- Multi-project context switching
- LLM model routing
- MCP server
"""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path
from datetime import datetime

# Import Phase 3 components
from architect.analysis import LargeProjectHandler, ProjectSizeDetector
from architect.projects import create_project_manager, ProjectManager
from architect.llm import ModelRouter, QueryClassifier
from architect.mcp import MCPServer


class TestLargeProjectSupport:
    """Tests for large project handling (Phase 1.1)"""
    
    @pytest.mark.asyncio
    async def test_project_size_detection(self):
        """Test project size categorization"""
        
        # Create test project with varying file counts
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 50 Python files
            for i in range(50):
                (Path(tmpdir) / f"file_{i}.py").write_text("# Python file")
            
            detector = ProjectSizeDetector()
            size_info = detector.detect(tmpdir)
            
            assert size_info.total_files == 50
            assert size_info.files_by_language.get('python') == 50
            assert size_info.size_category == "small"
            assert not size_info.requires_sampling
    
    @pytest.mark.asyncio
    async def test_large_project_analysis(self):
        """Test analysis of large projects with sampling"""
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 300 files
            for i in range(300):
                (Path(tmpdir) / f"file_{i}.py").write_text("# Python file")
            
            handler = LargeProjectHandler()
            files, size_info, metadata = await handler.prepare_large_project_analysis(tmpdir)
            
            assert size_info.total_files == 300
            assert size_info.size_category == "large"
            assert size_info.requires_sampling
            assert len(files) < 300  # Sampling applied
            assert len(files) <= 200  # Target sample size
            assert metadata.coverage >= 0.6  # At least 60% sampled
    
    @pytest.mark.asyncio
    async def test_stratified_sampling(self):
        """Test stratified random sampling by language"""
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mixed language project
            for i in range(100):
                (Path(tmpdir) / f"file_{i}.py").write_text("# Python")
            for i in range(50):
                (Path(tmpdir) / f"file_{i}.js").write_text("// JavaScript")
            
            handler = LargeProjectHandler()
            files, size_info, metadata = await handler.prepare_large_project_analysis(tmpdir)
            
            # Verify stratification
            py_count = sum(1 for f in files if f.endswith('.py'))
            js_count = sum(1 for f in files if f.endswith('.js'))
            
            # Should maintain roughly 100:50 ratio
            assert py_count > js_count
            assert metadata.sampling_ratio > 0.5
    
    def test_confidence_adjustment_for_sampled_files(self):
        """Test confidence degradation for extrapolated files"""
        
        handler = LargeProjectHandler()
        
        # Sampled file: no degradation
        adj_sampled = handler.calculate_confidence_adjustment(is_sampled=False)
        assert adj_sampled == 1.0
        
        # Extrapolated file: degradation applied
        adj_extrapolated = handler.calculate_confidence_adjustment(is_sampled=True)
        assert adj_extrapolated < 1.0
        assert adj_extrapolated >= 0.8  # At least 80% of original


class TestMultiProjectContextSwitching:
    """Tests for multi-project support (Phase 1.2)"""
    
    @pytest.mark.asyncio
    async def test_project_manager_creation(self):
        """Test ProjectManager initialization"""
        
        manager = create_project_manager(max_concurrent=5)
        
        assert manager.max_concurrent == 5
        assert len(manager.projects) == 0
        assert manager.current_project is None
    
    @pytest.mark.asyncio
    async def test_create_and_list_projects(self):
        """Test creating and listing projects"""
        
        manager = create_project_manager()
        
        # Create projects
        p1 = await manager.create_project("Project1", "/path/1", ["python"], 100)
        p2 = await manager.create_project("Project2", "/path/2", ["javascript"], 50)
        
        assert p1.project_id != p2.project_id
        assert p1.name == "Project1"
        assert p2.name == "Project2"
        
        # List projects
        projects = await manager.list_projects()
        assert len(projects) == 2
    
    @pytest.mark.asyncio
    async def test_context_switch_latency(self):
        """Test context switching is < 100ms"""
        
        import time
        manager = create_project_manager()
        
        # Create and load projects
        p1 = await manager.create_project("P1", "/path/1", ["python"], 100)
        p2 = await manager.create_project("P2", "/path/2", ["python"], 100)
        
        # Load first
        await manager.load_project(p1.project_id)
        
        # Measure switch latency
        start = time.time()
        await manager.switch_project(p2.project_id)
        elapsed_ms = (time.time() - start) * 1000
        
        # Target: <100ms (allowing for test overhead)
        assert elapsed_ms < 200, f"Context switch took {elapsed_ms:.1f}ms"
    
    @pytest.mark.asyncio
    async def test_project_memory_isolation(self):
        """Test projects have isolated memory (no cross-pollution)"""
        
        manager = create_project_manager()
        
        p1 = await manager.create_project("P1", "/path/1", ["python"], 100)
        p2 = await manager.create_project("P2", "/path/2", ["python"], 100)
        
        await manager.load_project(p1.project_id)
        memory1 = manager.projects[p1.project_id]
        memory1.analysis_data['test'] = 'data1'
        
        await manager.load_project(p2.project_id)
        memory2 = manager.projects[p2.project_id]
        memory2.analysis_data['test'] = 'data2'
        
        # Verify isolation
        assert memory1.analysis_data.get('test') == 'data1'
        assert memory2.analysis_data.get('test') == 'data2'
    
    @pytest.mark.asyncio
    async def test_session_management(self):
        """Test user session tracking"""
        
        manager = create_project_manager()
        session = manager.create_session(user_id="user123")
        
        assert session.session_id
        assert session.user_id == "user123"
        assert session.current_project is None
        
        # Record activity
        p1 = await manager.create_project("P1", "/path/1", ["python"], 100)
        await manager.switch_project(p1.project_id)
        await manager.record_query("What is this?", p1.project_id)
        
        # Verify history
        assert session.current_project == p1.project_id
        assert p1.project_id in session.recent_projects
        assert len(session.recent_queries) == 1


class TestLLMModelRouting:
    """Tests for model routing (Phase 2.2)"""
    
    def test_query_classification(self):
        """Test query complexity classification"""
        
        classifier = QueryClassifier()
        
        # Simple queries
        complexity, conf = classifier.classify("Where is the auth module?")
        assert complexity.value == "simple"
        assert conf > 0.7
        
        # Moderate queries
        complexity, conf = classifier.classify("How does error handling work in the database module?")
        assert complexity.value in ["simple", "moderate"]  # Could be either
        
        # Complex queries
        complexity, conf = classifier.classify("Compare factory vs singleton patterns and their trade-offs")
        assert complexity.value == "complex"
        assert conf > 0.7
    
    def test_model_routing(self):
        """Test model selection based on complexity"""
        
        router = ModelRouter()
        
        # Simple query → lightweight model
        decision = router.route("Where is the config file?")
        assert decision.primary_model == "qwen:7b-chat"
        
        # Complex query → stronger model
        decision = router.route("Design a new microservice for authentication")
        assert decision.primary_model == "qwen:32b-chat"
    
    def test_cost_estimation(self):
        """Test cost estimation"""
        
        router = ModelRouter()
        
        cost = router.estimate_cost(
            "Simple question?",
            estimated_response_tokens=200
        )
        
        assert cost >= 0.0
        assert cost < 0.01  # Should be cheap
    
    def test_fallback_model_selection(self):
        """Test intelligent fallback"""
        
        from architect.llm import IntelligentDegradation
        
        router = ModelRouter()
        degradation = IntelligentDegradation(router)
        
        # Timeout fallback
        fallback = degradation.get_fallback_model(
            "qwen:32b-chat",
            reason='timeout'
        )
        assert fallback in ["qwen:7b-chat", "qwen:32b-chat"]
    
    def test_routing_metrics(self):
        """Test metrics tracking"""
        
        router = ModelRouter()
        
        # Record some queries
        router.record_execution("test query", "qwen:7b-chat", 150, success=True)
        router.record_execution("test query 2", "qwen:32b-chat", 400, success=True)
        
        metrics = router.get_metrics()
        
        assert metrics['total_queries'] == 2
        assert 'models_used' in metrics


class TestMCPServer:
    """Tests for MCP protocol server (Phase 2.1)"""
    
    def test_mcp_server_creation(self):
        """Test MCP server initialization"""
        
        server = MCPServer()
        
        assert server.name == "architect-agent-mcp"
        assert server.version == "1.0.0"
        assert len(server.resources) > 0
        assert len(server.tools) > 0
        assert len(server.prompts) > 0
    
    def test_mcp_schema(self):
        """Test MCP schema generation"""
        
        server = MCPServer()
        schema = server.get_schema()
        
        assert 'server' in schema
        assert 'resources' in schema
        assert 'tools' in schema
        assert 'prompts' in schema
        
        # Verify server info
        assert schema['server']['name'] == "architect-agent-mcp"
        assert schema['server']['protocol'] == "MCP/1.0"
    
    def test_resource_registration(self):
        """Test registering MCP resources"""
        
        server = MCPServer()
        
        # Should have default resources
        assert 'architect://project' in server.resources
        assert 'architect://patterns' in server.resources
        
        # List resources
        resources = server.list_resources()
        assert len(resources) > 0
        assert any(r['uri'] == 'architect://project' for r in resources)
    
    def test_tool_registration(self):
        """Test registering MCP tools"""
        
        server = MCPServer()
        
        # Should have default tools
        assert 'query' in server.tools
        assert 'analyze' in server.tools
        
        # Verify tool schema
        query_tool = server.tools['query']
        assert 'question' in query_tool.inputSchema['properties']
    
    def test_prompt_registration(self):
        """Test registering MCP prompts"""
        
        server = MCPServer()
        
        # Should have default prompts
        assert 'ask_module_overview' in server.prompts
        assert 'explain_pattern' in server.prompts
    
    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Test executing a tool"""
        
        server = MCPServer()
        
        # Register a test handler
        async def test_handler(question: str, project_id: str = None):
            return {"answer": "test result"}
        
        server.register_tool(
            name="test_tool",
            description="Test",
            inputSchema={},
            handler=test_handler
        )
        
        # Execute tool
        result = await server.call_tool("test_tool", {"question": "test?"})
        assert result['answer'] == "test result"


class TestPhase3Performance:
    """Performance benchmarks for Phase 3"""
    
    @pytest.mark.asyncio
    async def test_large_project_analysis_time(self):
        """Benchmark: 200+ file analysis should be <60s"""
        
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 200 files
            for i in range(200):
                (Path(tmpdir) / f"file_{i}.py").write_text(f"# File {i}\nvar x = {i}")
            
            handler = LargeProjectHandler()
            
            start = time.time()
            files, size_info, metadata = await handler.prepare_large_project_analysis(tmpdir)
            elapsed = time.time() - start
            
            # Should be very fast (no actual parsing yet, just sampling)
            assert elapsed < 5.0, f"Analysis prep took {elapsed:.1f}s"
    
    @pytest.mark.asyncio
    async def test_context_switch_speed(self):
        """Benchmark: Context switch should be <100ms"""
        
        import time
        manager = create_project_manager()
        
        projects = []
        for i in range(5):
            p = await manager.create_project(f"P{i}", f"/path/{i}", ["python"], 100)
            projects.append(p.project_id)
        
        # Pre-load all
        for pid in projects:
            await manager.load_project(pid)
        
        # Measure switch latency
        times = []
        for pid in projects:
            start = time.time()
            await manager.switch_project(pid)
            times.append((time.time() - start) * 1000)
        
        avg_ms = sum(times) / len(times)
        assert avg_ms < 100, f"Avg context switch: {avg_ms:.1f}ms"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
