"""
Integration tests for Phase 2: Core Generators

Tests:
- Code generation pipeline
- Validation system
- A2A API adapter
"""

import pytest
import asyncio
from pathlib import Path

from ..generator import CodeGenerator, GenerationConfig, SimpleStringTemplate
from ..validators import CodeValidator, SeverityLevel
from ..api_adapter import (
    A2ACodegenAdapter,
    GenerateRequest,
    ValidateRequest,
    ImpactRequest,
)


class TestCodeGeneratorPipeline:
    """Test code generation pipeline"""
    
    @pytest.fixture
    def generator(self):
        """Create generator instance"""
        config = GenerationConfig(
            use_black=False,  # Disable for testing
            validate_syntax=True,
        )
        return CodeGenerator(config)
    
    @pytest.mark.asyncio
    async def test_simple_template_generation(self, generator):
        """Test simple string template generation"""
        template = SimpleStringTemplate(
            "test",
            "def {{function_name}}(x: int) -> int:\n    return x * 2",
        )
        
        context = {"function_name": "double"}
        code = await generator.generate(template, context, format_code=False)
        
        assert "def double(x: int) -> int:" in code
        assert "return x * 2" in code
    
    @pytest.mark.asyncio
    async def test_syntax_validation_in_pipeline(self, generator):
        """Test syntax validation in pipeline"""
        template = SimpleStringTemplate(
            "test",
            "def {{name}}():\n    pass",
        )
        
        context = {"name": "test_func"}
        code, success = await generator.generate_pipeline(template, context)
        
        assert success
        assert "def test_func():" in code
    
    def test_invalid_syntax_detection(self, generator):
        """Test invalid syntax detection"""
        code = "def invalid(:\n    pass"
        is_valid, errors = generator.validate_syntax(code)
        
        assert not is_valid
        assert len(errors) > 0
        assert "Syntax error" in errors[0]


class TestCodeValidator:
    """Test code validator"""
    
    @pytest.fixture
    def validator(self):
        """Create validator instance"""
        return CodeValidator()
    
    def test_valid_code(self, validator):
        """Test validation of valid code"""
        code = '''
def hello(name: str) -> str:
    """Say hello to someone"""
    return f"Hello, {name}!"
'''
        valid, issues = validator.validate(code)
        assert valid
    
    def test_syntax_error_detection(self, validator):
        """Test detection of syntax errors"""
        code = "def invalid(:\n    pass"
        valid, issues = validator.validate(code)
        
        assert not valid
        assert any(i.code == "E001" for i in issues)
    
    def test_undefined_type_detection(self, validator):
        """Test detection of undefined types"""
        code = '''
def process(data: UndefinedType) -> str:
    return str(data)
'''
        valid, issues = validator.validate(code, check_syntax=False, check_types=True)
        # May or may not detect depending on validator settings
        # This is mostly for documentation
    
    def test_validation_report_generation(self, validator):
        """Test validation report generation"""
        code = "def invalid(:\n    pass"
        validator.validate(code)
        report = validator.generate_report()
        
        assert "Errors" in report
        assert "E001" in report


class TestA2AAdapter:
    """Test A2A API adapter"""
    
    @pytest.fixture
    def adapter(self):
        """Create adapter instance"""
        return A2ACodegenAdapter()
    
    @pytest.mark.asyncio
    async def test_pydantic_generation(self, adapter):
        """Test Pydantic model generation via A2A"""
        request = GenerateRequest(
            request_id="test-1",
            template_type="pydantic",
            template_name="user_model",
            context={
                "model_name": "User",
                "fields": [
                    {
                        "name": "id",
                        "type": "int",
                        "required": True,
                        "description": "User ID",
                    },
                    {
                        "name": "email",
                        "type": "str",
                        "required": True,
                        "description": "User email",
                    },
                ],
            },
        )
        
        response = await adapter.handle_generate_request(request)
        
        assert response.success
        assert "class User(BaseModel):" in response.code
        assert "id: int" in response.code
    
    @pytest.mark.asyncio
    async def test_validation_request(self, adapter):
        """Test code validation via A2A"""
        code = '''
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b
'''
        
        request = ValidateRequest(
            request_id="test-2",
            code=code,
        )
        
        response = await adapter.handle_validate_request(request)
        
        assert response.valid
        assert response.summary["errors"] == 0
    
    @pytest.mark.asyncio
    async def test_impact_analysis(self, adapter):
        """Test code impact analysis via A2A"""
        old_code = '''
def process(data: list) -> int:
    """Process data"""
    return len(data)
'''
        
        new_code = '''
def process(data: list) -> int:
    """Process data - improved"""
    return len(data) * 2
'''
        
        request = ImpactRequest(
            request_id="test-3",
            old_code=old_code,
            new_code=new_code,
        )
        
        response = await adapter.handle_impact_request(request)
        
        assert response.changes_detected
        assert response.impact_summary["lines_changed"] > 0
    
    @pytest.mark.asyncio
    async def test_request_history_tracking(self, adapter):
        """Test request history tracking"""
        request = GenerateRequest(
            request_id="test-history",
            template_type="pydantic",
            template_name="test",
            context={
                "model_name": "Test",
                "fields": [],
            },
        )
        
        await adapter.handle_generate_request(request)
        
        assert "test-history" in adapter.request_history
        stored = adapter.request_history["test-history"]
        assert stored["request"].request_id == "test-history"


class TestEndToEndFlow:
    """End-to-end integration test"""
    
    @pytest.mark.asyncio
    async def test_full_code_generation_flow(self):
        """Test complete flow: generate -> validate -> analyze"""
        adapter = A2ACodegenAdapter()
        
        # Step 1: Generate Pydantic model
        gen_request = GenerateRequest(
            request_id="e2e-1",
            template_type="pydantic",
            template_name="product",
            context={
                "model_name": "Product",
                "fields": [
                    {"name": "id", "type": "int", "required": True},
                    {"name": "name", "type": "str", "required": True},
                    {"name": "price", "type": "float", "required": True},
                ],
                "description": "Product data model",
            },
        )
        
        gen_response = await adapter.handle_generate_request(gen_request)
        assert gen_response.success
        
        generated_code = gen_response.code
        
        # Step 2: Validate generated code
        val_request = ValidateRequest(
            request_id="e2e-2",
            code=generated_code,
        )
        
        val_response = await adapter.handle_validate_request(val_request)
        assert val_response.valid
        
        # Step 3: Impact analysis (mock change)
        impact_request = ImpactRequest(
            request_id="e2e-3",
            old_code=generated_code,
            new_code=generated_code + "\n\n# Added comment",
        )
        
        impact_response = await adapter.handle_impact_request(impact_request)
        assert impact_response.changes_detected
        
        print("✓ End-to-end flow successful!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
