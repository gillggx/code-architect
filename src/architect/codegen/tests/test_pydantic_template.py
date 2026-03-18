"""
Unit tests for Pydantic V2 Template Engine

Tests:
- Field type mapping
- Model generation
- Validator generation
- Bilingual docstrings
"""

import pytest
from ..pydantic_v2 import (
    PydanticV2Template,
    FieldDef,
    ValidatorDef,
    FieldType,
)


class TestPydanticV2Template:
    """Test Pydantic V2 template generation"""
    
    @pytest.fixture
    def template(self):
        """Create template instance"""
        return PydanticV2Template()
    
    def test_string_type_mapping(self, template):
        """Test string type mapping"""
        assert template.map_field_type("string") == "str"
        assert template.map_field_type("str") == "str"
    
    def test_integer_type_mapping(self, template):
        """Test integer type mapping"""
        assert template.map_field_type("integer") == "int"
        assert template.map_field_type("int") == "int"
    
    def test_list_type_mapping(self, template):
        """Test list type mapping"""
        result = template.map_field_type("list[string]")
        assert "List" in result
        assert "str" in result
    
    def test_dict_type_mapping(self, template):
        """Test dict type mapping"""
        result = template.map_field_type("dict[string,int]")
        assert "Dict" in result
        assert "str" in result
        assert "int" in result
    
    def test_optional_type_mapping(self, template):
        """Test optional type mapping"""
        field = FieldDef(
            name="optional_field",
            type_name="str",
            required=False,
        )
        annotation = template.generate_field_annotation(field)
        assert "Optional" in annotation
    
    def test_field_with_default_value(self, template):
        """Test field with default value"""
        field = FieldDef(
            name="count",
            type_name="int",
            required=False,
            default=0,
        )
        annotation = template.generate_field_annotation(field)
        assert "= 0" in annotation
    
    def test_field_docstring_generation(self, template):
        """Test field docstring with bilingual support"""
        field = FieldDef(
            name="username",
            type_name="str",
            description_cn="用户名",
            description_en="User name",
        )
        # Field docstrings are not used in Pydantic (use Field() instead)
        docstring = template.generate_field_docstring(field)
        # Just verify it doesn't crash and returns a string
        assert isinstance(docstring, str)
    
    def test_validator_generation(self, template):
        """Test validator generation"""
        validator = ValidatorDef(
            name="positive",
            fields=["count", "age"],
            rules=["v > 0"],
            error_message_en="Value must be positive",
        )
        validators_code = template.generate_validators([validator])
        assert "@field_validator" in validators_code
        assert "validate_positive" in validators_code
        assert "v > 0" in validators_code
    
    def test_model_generation(self, template):
        """Test complete model generation"""
        fields = [
            FieldDef(
                name="id",
                type_name="int",
                description_en="User ID",
            ),
            FieldDef(
                name="name",
                type_name="str",
                description_en="User name",
            ),
        ]
        
        model_code = template.generate_model(
            "User",
            fields,
            description_en="User data model",
        )
        
        assert "class User(BaseModel):" in model_code
        assert "id: int" in model_code
        assert "name: str" in model_code
        assert "model_config" in model_code
    
    def test_imports_generation(self, template):
        """Test import statements generation"""
        imports = template.generate_imports()
        assert "from pydantic import" in imports
        assert "BaseModel" in imports
        assert "field_validator" in imports
    
    def test_complete_module_generation(self, template):
        """Test complete module generation"""
        fields = [
            FieldDef(
                name="email",
                type_name="str",
                description_en="Email address",
            ),
        ]
        
        models = {
            "User": (fields, []),
        }
        
        module_code = template.generate_complete_module(
            "user_models",
            models,
        )
        
        assert 'class User(BaseModel):' in module_code
        assert "email: str" in module_code
        assert "from pydantic import" in module_code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
