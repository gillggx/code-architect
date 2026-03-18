"""
Pydantic V2 Template Engine

Generates Pydantic V2 models with:
- Schema generation (BaseModel with validators)
- Field type mapping (str, int, list, dict, Optional, etc.)
- Validator generation (@field_validator)
- Bilingual docstrings (Chinese + English)

Version: 1.0
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple, Any, Union
from enum import Enum
import re


class FieldType(Enum):
    """Python type categories for field mapping"""
    STRING = "str"
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    LIST = "list"
    DICT = "dict"
    OPTIONAL = "Optional"
    CUSTOM = "custom"


@dataclass
class FieldDef:
    """Field definition for Pydantic model
    
    中文: Pydantic 模型的字段定义
    """
    name: str
    type_name: str
    required: bool = True
    default: Optional[Any] = None
    description_cn: str = ""
    description_en: str = ""
    validators: List[str] = None  # List of validator names
    
    def __post_init__(self):
        if self.validators is None:
            self.validators = []


@dataclass
class ValidatorDef:
    """Validator definition for @field_validator decorator
    
    中文: @field_validator 装饰器的验证器定义
    """
    name: str
    fields: List[str]  # Fields this validator applies to
    rules: List[str]  # Validation rules (e.g., "len(v) > 0", "v >= 0")
    error_message_cn: str = ""
    error_message_en: str = ""


class PydanticV2Template:
    """Pydantic V2 model code generator
    
    中文: Pydantic V2 模型代码生成器
    """
    
    def __init__(self):
        """Initialize Pydantic V2 template engine"""
        self.type_map = {
            "string": FieldType.STRING,
            "str": FieldType.STRING,
            "integer": FieldType.INTEGER,
            "int": FieldType.INTEGER,
            "number": FieldType.FLOAT,
            "float": FieldType.FLOAT,
            "boolean": FieldType.BOOLEAN,
            "bool": FieldType.BOOLEAN,
            "list": FieldType.LIST,
            "array": FieldType.LIST,
            "dict": FieldType.DICT,
            "object": FieldType.DICT,
            "mapping": FieldType.DICT,
        }
    
    def map_field_type(self, type_hint: str) -> str:
        """Map input type hint to Python type annotation
        
        中文: 将输入类型提示映射到Python类型注解
        
        Args:
            type_hint: Input type string (e.g., "string", "int", "list[dict]")
        
        Returns:
            Python type annotation string (e.g., "str", "int", "List[Dict]")
        """
        type_hint = type_hint.lower().strip()
        
        # Handle List/Dict with generics
        if "list" in type_hint or "array" in type_hint:
            inner = self._extract_generic(type_hint)
            if inner:
                return f"List[{self.map_field_type(inner)}]"
            return "List[Any]"
        
        if "dict" in type_hint or "object" in type_hint or "mapping" in type_hint:
            inner = self._extract_generic(type_hint)
            if inner:
                # Parse key,value format
                parts = [p.strip() for p in inner.split(",")]
                if len(parts) == 2:
                    key_type = self.map_field_type(parts[0])
                    val_type = self.map_field_type(parts[1])
                    return f"Dict[{key_type}, {val_type}]"
            return "Dict[str, Any]"
        
        # Standard types
        base_type = self.type_map.get(type_hint, FieldType.CUSTOM)
        if base_type == FieldType.CUSTOM:
            return type_hint  # Return as-is (custom class name)
        
        return base_type.value
    
    def _extract_generic(self, type_hint: str) -> Optional[str]:
        """Extract generic type parameter from type hint
        
        中文: 从类型提示中提取泛型参数
        
        Examples:
            "list[string]" -> "string"
            "dict[string,int]" -> "string,int"
        """
        match = re.search(r'\[(.+)\]', type_hint)
        return match.group(1) if match else None
    
    def generate_field_annotation(self, field: FieldDef) -> str:
        """Generate field annotation line
        
        中文: 生成字段注解行
        
        Args:
            field: Field definition
        
        Returns:
            Field annotation line (e.g., "name: str" or "age: int = 0")
        """
        type_str = field.type_name
        
        # Wrap in Optional if not required
        if not field.required and "Optional" not in type_str:
            type_str = f"Optional[{type_str}]"
        
        line = f"    {field.name}: {type_str}"
        
        # Add default value
        if field.default is not None:
            if isinstance(field.default, str):
                line += f' = "{field.default}"'
            else:
                line += f" = {field.default}"
        elif not field.required:
            line += " = None"
        
        return line
    
    def generate_field_docstring(self, field: FieldDef) -> str:
        """Generate field docstring with bilingual description
        
        中文: 生成带有双语描述的字段文档字符串
        
        Args:
            field: Field definition
        
        Returns:
            Docstring block for field
        """
        # Field docstrings are not standard in Pydantic - use Field() instead
        # Return empty to avoid syntax errors
        return ""
    
    def generate_validators(self, validators: List[ValidatorDef]) -> str:
        """Generate @field_validator decorator blocks
        
        中文: 生成 @field_validator 装饰器块
        
        Args:
            validators: List of validator definitions
        
        Returns:
            Validator code block
        """
        if not validators:
            return ""
        
        lines = []
        for validator in validators:
            # Decorator
            fields_str = ", ".join([f'"{f}"' for f in validator.fields])
            lines.append(f"    @field_validator({fields_str})")
            
            # Method signature
            lines.append(f"    @classmethod")
            lines.append(f"    def validate_{validator.name}(cls, v):")
            
            # Docstring
            lines.append('        """')
            if validator.error_message_cn:
                lines.append(f"        {validator.error_message_cn}")
            if validator.error_message_en:
                lines.append(f"        {validator.error_message_en}")
            lines.append('        """')
            
            # Validation logic
            for rule in validator.rules:
                lines.append(f"        if not ({rule}):")
                error_msg = validator.error_message_en or f"Validation failed for {validator.name}"
                lines.append(f'            raise ValueError("{error_msg}")')
            
            lines.append("        return v")
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_model(
        self,
        model_name: str,
        fields: List[FieldDef],
        validators: List[ValidatorDef] = None,
        description_cn: str = "",
        description_en: str = "",
        base_class: str = "BaseModel",
    ) -> str:
        """Generate complete Pydantic V2 model
        
        中文: 生成完整的 Pydantic V2 模型
        
        Args:
            model_name: Model class name
            fields: List of field definitions
            validators: List of validator definitions
            description_cn: Chinese description
            description_en: English description
            base_class: Base class (default: BaseModel)
        
        Returns:
            Complete model code
        """
        lines = []
        
        # Class definition with docstring
        lines.append(f"class {model_name}({base_class}):")
        lines.append('    """')
        if description_cn:
            lines.append(f"    {description_cn}")
        if description_en:
            lines.append(f"    {description_en}")
        lines.append('    """')
        lines.append("")
        
        # Field annotations
        for field in fields:
            lines.append(self.generate_field_annotation(field))
            docstring = self.generate_field_docstring(field)
            if docstring:
                lines.append(docstring)
        
        # Model config (Pydantic V2)
        lines.append("")
        lines.append("    model_config = ConfigDict(")
        lines.append("        validate_assignment=True,")
        lines.append("        use_enum_values=False,")
        lines.append("    )")
        lines.append("")
        
        # Validators
        if validators:
            lines.append(self.generate_validators(validators))
        
        # Meta info
        lines.append(f"    # Generated model for {model_name}")
        lines.append(f"    # Schema version: 1.0")
        
        return "\n".join(lines)
    
    def generate_imports(self) -> str:
        """Generate required imports for Pydantic V2
        
        中文: 生成 Pydantic V2 所需的导入
        
        Returns:
            Import statements
        """
        return (
            "from pydantic import BaseModel, Field, field_validator, ConfigDict\n"
            "from typing import Optional, List, Dict, Any\n"
            "from enum import Enum\n"
        )
    
    def generate_complete_module(
        self,
        module_name: str,
        models: Dict[str, Tuple[List[FieldDef], List[ValidatorDef]]],
        enums: Dict[str, List[str]] = None,
    ) -> str:
        """Generate complete Python module with models and enums
        
        中文: 生成包含模型和枚举的完整Python模块
        
        Args:
            module_name: Module name
            models: Dict of {model_name: (fields, validators)}
            enums: Dict of {enum_name: [values]}
        
        Returns:
            Complete module code
        """
        lines = []
        
        # Header
        lines.append(f'"""\n{module_name}\n')
        lines.append('Auto-generated Pydantic V2 models\n')
        lines.append('"""\n')
        
        # Imports
        lines.append(self.generate_imports())
        lines.append("")
        
        # Enums
        if enums:
            for enum_name, values in enums.items():
                lines.append(f"class {enum_name}(str, Enum):")
                for val in values:
                    lines.append(f'    {val.upper()} = "{val}"')
                lines.append("")
        
        # Models
        for model_name, (fields, validators) in models.items():
            desc_cn = f"Model for {model_name}"
            desc_en = f"{model_name} data model"
            model_code = self.generate_model(
                model_name,
                fields,
                validators or [],
                desc_cn,
                desc_en,
            )
            lines.append(model_code)
            lines.append("\n")
        
        return "\n".join(lines)
