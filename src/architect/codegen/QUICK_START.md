# Code Generation Module - Quick Start Guide

## 🚀 快速开始

### 安装

```bash
cd /Users/gill/metagpt_pure/workspace/code-architect-agent-platform
pip install -e .
```

### 基础使用

#### 1. 生成 Pydantic 模型

```python
from architect.codegen import PydanticV2Template, FieldDef

template = PydanticV2Template()

# 定义字段
fields = [
    FieldDef(name="id", type_name="int", required=True),
    FieldDef(name="name", type_name="str", required=True),
    FieldDef(name="email", type_name="str", required=True),
    FieldDef(name="age", type_name="int", required=False, default=None),
]

# 生成模型
code = template.generate_model(
    "User",
    fields,
    description_en="User data model"
)

print(code)
```

#### 2. 生成 FastAPI 路由

```python
from architect.codegen import FastAPIRoutesTemplate, EndpointDef, HTTPMethod

template = FastAPIRoutesTemplate()

endpoints = [
    EndpointDef(
        method=HTTPMethod.GET,
        path="/users/{user_id}",
        name="get_user",
        response_model="UserSchema",
    ),
    EndpointDef(
        method=HTTPMethod.POST,
        path="/users",
        name="create_user",
        request_model="UserCreateSchema",
        response_model="UserSchema",
    ),
]

code = template.generate_router_module(
    "user_routes",
    "router",
    endpoints,
    prefix="/api/v1/users"
)

print(code)
```

#### 3. 生成 Agent 模式

```python
from architect.codegen import AgentPatternsTemplate, AgentSessionConfig, MemoryConfig

template = AgentPatternsTemplate()

config = AgentSessionConfig(
    agent_id="coder-001",
    agent_name="Code Coder",
    role="coder",
    description_en="Code implementation agent",
    memory=MemoryConfig(
        enabled=True,
        short_term_capacity=100,
    ),
)

code = template.generate_complete_agent_module(config)
print(code)
```

#### 4. 生成异步模式

```python
from architect.codegen import AsyncPatternsTemplate, AsyncFunctionDef

template = AsyncPatternsTemplate()

func = AsyncFunctionDef(
    name="process_batch",
    parameters=[("items", "List[Dict]")],
    return_type="List[Result]",
    concurrent_calls=["process(item) for item in items"],
)

code = template.generate_gather_pattern(func)
print(code)
```

#### 5. 使用代码生成器

```python
import asyncio
from architect.codegen import CodeGenerator, GenerationConfig, SimpleStringTemplate

async def main():
    config = GenerationConfig(
        use_black=True,
        validate_syntax=True,
    )
    
    generator = CodeGenerator(config)
    
    template = SimpleStringTemplate(
        "hello",
        "def {{name}}():\n    return 'Hello, {{greeting}}!'"
    )
    
    context = {
        "name": "greet",
        "greeting": "World"
    }
    
    code = await generator.generate(template, context, format_code=True)
    print(code)

asyncio.run(main())
```

#### 6. 验证代码

```python
from architect.codegen import CodeValidator

validator = CodeValidator()

code = '''
def add(a: int, b: int) -> int:
    return a + b
'''

valid, issues = validator.validate(code)
report = validator.generate_report()

print(f"Valid: {valid}")
print(report)
```

#### 7. 使用 A2A API 生成

```python
import asyncio
from architect.codegen import A2ACodegenAdapter, GenerateRequest

async def main():
    adapter = A2ACodegenAdapter()
    
    # 生成 Pydantic 模型
    request = GenerateRequest(
        request_id="gen-001",
        template_type="pydantic",
        template_name="user",
        context={
            "model_name": "User",
            "fields": [
                {"name": "id", "type": "int", "required": True},
                {"name": "email", "type": "str", "required": True},
            ],
        }
    )
    
    response = await adapter.handle_generate_request(request)
    
    print(f"Success: {response.success}")
    if response.success:
        print(f"Generated code:\n{response.code}")
    else:
        print(f"Errors: {response.errors}")

asyncio.run(main())
```

---

## 📚 API 参考

### Template Engines

| 模块 | 类 | 主要方法 |
|------|-----|---------|
| pydantic_v2 | PydanticV2Template | generate_model(), map_field_type() |
| fastapi_routes | FastAPIRoutesTemplate | generate_endpoint(), generate_router_module() |
| agent_patterns | AgentPatternsTemplate | generate_complete_agent_module() |
| async_patterns | AsyncPatternsTemplate | generate_gather_pattern() |

### Core Generators

| 模块 | 类 | 主要方法 |
|------|-----|---------|
| generator | CodeGenerator | generate(), generate_pipeline() |
| validators | CodeValidator | validate(), generate_report() |
| api_adapter | A2ACodegenAdapter | handle_generate_request(), handle_validate_request() |

---

## 🧪 运行测试

```bash
# 运行所有测试
python3 -m pytest src/architect/codegen/tests/ -v

# 运行特定测试
python3 -m pytest src/architect/codegen/tests/test_pydantic_template.py -v

# 生成覆盖率报告
python3 -m pytest src/architect/codegen/tests/ --cov=src.architect.codegen --cov-report=html
```

---

## 🎯 常见用例

### 用例 1: 从 OpenAPI Schema 生成模型

```python
from architect.codegen import PydanticV2Template, FieldDef

# 从 OpenAPI schema 解析字段
openapi_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "email": {"type": "string", "format": "email"}
    },
    "required": ["id", "name", "email"]
}

# 转换为 FieldDef
fields = []
for prop_name, prop_schema in openapi_schema["properties"].items():
    field = FieldDef(
        name=prop_name,
        type_name=prop_schema.get("type", "str"),
        required=prop_name in openapi_schema.get("required", [])
    )
    fields.append(field)

# 生成代码
template = PydanticV2Template()
code = template.generate_model("APIModel", fields)
```

### 用例 2: CRUD API 生成

```python
from architect.codegen import FastAPIRoutesTemplate, EndpointDef, HTTPMethod, RouteParameter

template = FastAPIRoutesTemplate()

endpoints = [
    EndpointDef(HTTPMethod.GET, "/items", "list_items", response_model="List[Item]"),
    EndpointDef(HTTPMethod.POST, "/items", "create_item", request_model="ItemCreate", response_model="Item"),
    EndpointDef(HTTPMethod.GET, "/items/{item_id}", "get_item", response_model="Item"),
    EndpointDef(HTTPMethod.PUT, "/items/{item_id}", "update_item", request_model="ItemUpdate", response_model="Item"),
    EndpointDef(HTTPMethod.DELETE, "/items/{item_id}", "delete_item"),
]

code = template.generate_router_module("item_routes", "router", endpoints, "/api/v1")
```

### 用例 3: 并发数据处理

```python
from architect.codegen import AsyncPatternsTemplate, AsyncFunctionDef

template = AsyncPatternsTemplate()

func = AsyncFunctionDef(
    name="batch_process",
    parameters=[
        ("items", "List[DataItem]"),
        ("max_concurrent", "int"),
    ],
    return_type="List[ProcessResult]",
    concurrent_calls=[
        "process_item(item) for item in items"
    ],
    timeout_seconds=60,
)

code = template.generate_semaphore_pool_pattern(func, max_concurrent=5)
```

---

## 🔧 配置

### 代码生成配置

```python
from architect.codegen import GenerationConfig, CodeGenerator

config = GenerationConfig(
    template_dir=Path("./templates"),
    output_dir=Path("./generated"),
    use_black=True,              # 使用 black 格式化
    use_autopep8=False,           # 不使用 autopep8
    validate_syntax=True,         # 验证生成的代码
    bilingual_comments=True,      # 包含中英注释
    cache_templates=True,         # 缓存模板
)

generator = CodeGenerator(config)
```

---

## ⚡ 性能提示

1. **模板缓存:** 启用缓存以加快重复生成
   ```python
   generator.register_template(template)  # 缓存模板
   cached = generator.get_template(name)  # 检索缓存
   ```

2. **并发生成:** 使用 asyncio 并发生成多个代码文件
   ```python
   tasks = [
       generator.generate(template1, context1),
       generator.generate(template2, context2),
       generator.generate(template3, context3),
   ]
   results = await asyncio.gather(*tasks)
   ```

3. **批量验证:** 一次性验证多个文件
   ```python
   codes = [code1, code2, code3]
   for code in codes:
       valid, issues = validator.validate(code)
   ```

---

## 📖 更多信息

- **完整文档:** 见 `CODEGEN_IMPLEMENTATION_REPORT.md`
- **API 文档:** 每个模块都有详细的 docstring
- **示例代码:** 见 `tests/` 目录
- **GitHub:** 提交 issue 或 PR

---

## 💡 提示和技巧

### 调试生成的代码

```python
# 保存生成的代码到文件以便检查
import asyncio
from pathlib import Path

async def debug_generate():
    code = await generator.generate(template, context)
    
    # 保存到文件
    output_path = Path("debug_output.py")
    await generator.save_generated_code(code, output_path)
    
    # 验证
    valid, issues = validator.validate(code)
    
    # 查看报告
    print(validator.generate_report())

asyncio.run(debug_generate())
```

### 自定义模板

```python
# 创建自定义模板
from architect.codegen import CodeTemplate

class CustomTemplate(CodeTemplate):
    def __init__(self, name: str, content: str):
        super().__init__(name)
        self.content = content
    
    def render(self, context: Dict[str, Any]) -> str:
        # 自定义渲染逻辑
        result = self.content
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

# 使用
custom = CustomTemplate("my_template", "...")
code = generator.generate(custom, context)
```

---

**版本:** 1.0  
**最后更新:** 2026-03-18  
**状态:** 生产就绪 ✅
