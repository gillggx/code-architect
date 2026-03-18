# Code Architect 改造评估报告

**评估日期:** 2026-03-18  
**评估对象:** `/Users/gill/metagpt_pure/workspace/code-architect-agent-platform/`  
**评估者:** Architect Agent  
**版本:** v1.0

---

## 现状分析

### 1.1 Code Architect 当前做什么？

Code Architect Agent 是一个 **AI 驱动的代码库分析工具**，其核心价值在于：

1. **扫描** — 遍历项目目录树，按优先级（入口文件 > 配置文件 > 业务逻辑）筛选最多 40 个文件
2. **理解** — 调用 LLM（OpenRouter/Claude/Ollama）阅读每个文件，生成结构化 JSON 摘要，包含：purpose、key_components、dependencies、patterns、notes
3. **记忆** — 将摘要存储为 modules.json，支持增量分析（下次只重读变更文件）
4. **问答** — 通过 RAG（BM25 + 向量混合检索）让用户和其他 agent 提问
5. **代码生成** — Code Edit Agent 子系统接收任务，以 function-calling 方式调用文件操作工具，支持 dry_run / apply / interactive 三种模式
6. **A2A API** — 暴露 `/api/a2a/*` 端点，供其他 agent 调用（generate、validate、impact）

### 1.2 代码结构和模块划分

```
src/architect/
├── api/
│   ├── main.py          (1146 行) FastAPI 入口，所有路由
│   ├── schemas.py        Pydantic 请求/响应模型
│   ├── auth.py           API Key + 速率限制
│   ├── errors.py         结构化错误类型
│   ├── websocket.py      WebSocket 连接管理
│   ├── agent_runner.py  (757 行) 代码编辑 Agent 执行循环
│   ├── diff.py           差异计算
│   └── tools/
│       ├── file_tools.py     文件读写
│       ├── git_tools.py      Git 操作
│       ├── search_tools.py   代码搜索
│       └── shell_tools.py    Shell 命令执行
│
├── analysis/
│   ├── llm_analyzer.py  (666 行) 核心 LLM 分析管道
│   └── large_project_handler.py  大项目采样
│
├── llm/
│   ├── client.py        (213 行) OpenRouter/Ollama 客户端
│   ├── chat_engine.py   (318 行) RAG + LLM 流式生成
│   └── model_router.py          查询复杂度路由
│
├── memory/
│   ├── tier1.py         (182 行) 内存 artifact 存储
│   ├── persistence.py            Tier1 ↔ Markdown 同步
│   ├── rag_integration.py        RAG ↔ 内存桥接
│   ├── vector_index.py           向量嵌入
│   └── incremental_analysis.py   文件快照 + diff
│
├── patterns/
│   ├── catalog.py       (618 行) 17 个内置设计模式定义
│   ├── detector.py      (780 行) Regex/AST 模式检测器
│   └── validators.py             证据验证
│
├── rag/
│   ├── chunker.py                Markdown 分块（500 token）
│   ├── embeddings.py             text-embedding-3-small / TF-IDF SVD
│   ├── vector_store.py           NumPy 余弦相似度
│   ├── hybrid_search.py          BM25(0.4) + 向量(0.6) 混合检索
│   └── retriever.py              高层检索 API
│
├── parsers/
│   ├── python_analyzer.py        Python AST
│   ├── cpp_analyzer.py           C++ 解析
│   ├── other_analyzers.py        多语言
│   └── registry.py               语言 → 解析器分发
│
├── mcp/
│   └── server.py                 MCP Protocol（IDE 集成）
│
├── projects/
│   └── manager.py                多项目管理（最多 5 个）
│
├── qa/
│   └── engine.py                 规则型 QA（无 LLM 前置）
│
└── models.py                     Pydantic 数据模型

web/src/
├── App.tsx                       三面板 Shell
├── store/app.ts                  Zustand 全局状态
└── components/
    ├── TopBar.tsx
    ├── FileTree.tsx
    ├── AgentActivityFeed.tsx
    ├── MemoryPanel.tsx
    └── ChatBar.tsx
```

**代码量统计:**
- 后端 Python: ~6,000+ 行（核心业务逻辑 ~4,700 行）
- 前端 TypeScript: ~2,000 行
- 模块数: 30+ Python 模块

### 1.3 核心功能和局限性

**✅ 现有优势:**

| 功能 | 状态 | 说明 |
|------|------|------|
| LLM 文件分析 | ✅ 完整 | 支持 20+ 语言，JSON 输出 |
| 增量分析 | ✅ 完整 | 基于文件快照的 diff |
| 异步流水线 | ✅ 完整 | asyncio + WebSocket 实时推送 |
| A2A REST API | ✅ 完整 | generate/validate/impact |
| RAG 检索 | ✅ 完整 | BM25 + 向量混合 |
| 代码编辑 Agent | ✅ 可用 | function-calling 工具链 |
| 多种执行模式 | ✅ 完整 | dry_run/apply/interactive |
| 设计模式检测 | ✅ 17种 | 通用设计模式 |

**❌ 现有局限性（面向 agent-platform 需求）:**

| 局限性 | 影响 | 详情 |
|--------|------|------|
| 分析 prompt 太泛 | 高 | `_build_file_prompt()` 只问通用问题，无专项 agent-platform 感知 |
| 代码生成 prompt 无专项模板 | 高 | AgentRunner 用通用 system prompt，不知 Pydantic/FastAPI/async 惯例 |
| 无 Python async 代码生成模式 | 高 | patterns/catalog.py 里无 async/await 模式专项 |
| 无 Pydantic v2 模式支持 | 中 | 未定义 BaseModel 工厂模式、validators |
| 无 DI（依赖注入）模式 | 中 | FastAPI Depends() 模式未在 catalog 里定义 |
| 无 agent-platform 专项错误处理规范 | 中 | 现有 validate 端点逻辑简化、占位 |
| 模式检测为通用设计模式 | 中 | 无异步并发、无 agent-to-agent 通信模式 |
| 工具调用生成无类型注解约束 | 低 | 生成代码不保证类型完整性 |
| 文档生成能力弱 | 低 | 仅分析文件，不生成 docstrings |

### 1.4 与 agent-platform 需求的对齐度

```
对齐度总评: 65/100

✅ 高对齐 (80%+):
  - A2A API 架构  ← 原生设计就是 A2A
  - 异步执行管道  ← 全面 asyncio
  - FastAPI 服务结构  ← 已用 FastAPI
  - WebSocket 实时流  ← 完整实现

⚠️ 中对齐 (40-79%):
  - 代码生成能力  ← 有但缺乏 agent-platform 专项模板
  - 错误处理规范  ← 有框架但 validate 是占位实现
  - 设计模式库  ← 通用 17 种，缺 async/DI 专项

❌ 低对齐 (<40%):
  - Pydantic v2 代码生成  ← 完全缺失
  - FastAPI DI 模式感知  ← 完全缺失
  - Agent 间通信模式生成  ← 完全缺失
  - 类型安全代码生成  ← 无专项约束
```

---

## 改造需求

### 2.1 agent-platform 需要什么样的代码生成能力？

基于对 code-architect 的理解和 agent-platform 的常见需求，代码生成能力需要：

**必要能力 (Must Have):**
1. 生成符合 agent-platform 惯例的 Python async 代码
2. 生成 Pydantic v2 数据模型（BaseModel、field validators、model_config）
3. 生成 FastAPI 路由/依赖注入链
4. 生成 Agent 工厂函数（create_agent、工厂模式）
5. 理解并延续项目已有命名规范、模块结构

**推荐能力 (Should Have):**
1. 生成含类型注解的代码（全面使用 Python typing）
2. 生成标准化错误处理（HTTPException、自定义异常层级）
3. 自动生成 docstrings（Google/NumPy 风格）
4. 生成对应测试骨架（pytest + pytest-asyncio）
5. A2A 消息模型生成（符合 A2A 协议的 Pydantic 模型）

**可选能力 (Nice to Have):**
1. 生成 Docker / compose 配置片段
2. 生成 OpenAPI schema 描述
3. 自动检测和修复 async/await 误用

### 2.2 需要支持的代码类型

```python
# 类型 1: Python async 服务
async def create_agent_service(...) -> AgentService:
    async with lifespan_context():
        ...

# 类型 2: Pydantic v2 模型
class AgentMessage(BaseModel):
    model_config = ConfigDict(...)
    agent_id: str = Field(...)
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v): ...

# 类型 3: FastAPI 路由 + DI
@router.post("/agents/{agent_id}/task")
async def submit_task(
    agent_id: str,
    request: TaskRequest,
    service: AgentService = Depends(get_agent_service),
) -> TaskResponse: ...

# 类型 4: 工厂函数
def create_agent(
    agent_type: AgentType,
    config: AgentConfig,
) -> BaseAgent: ...

# 类型 5: 异步上下文管理器
@asynccontextmanager
async def managed_agent(agent_id: str) -> AsyncIterator[Agent]:
    agent = await Agent.create(agent_id)
    try:
        yield agent
    finally:
        await agent.cleanup()
```

### 2.3 需要支持的设计模式

| 模式 | 当前状态 | 需要新增/扩展 |
|------|---------|-------------|
| Factory Function | 有基础定义 | 需扩展为 async 工厂 |
| Dependency Injection (FastAPI Depends) | ❌ 无 | 需新增 |
| Async Context Manager | ❌ 无 | 需新增 |
| Repository Pattern (async) | 有基础 | 需 async 版本 |
| Event Bus / Pub-Sub | ❌ 无 | 需新增 |
| Circuit Breaker | ❌ 无 | 需新增（agent 通信容错） |
| Retry with Exponential Backoff | ❌ 无 | 需新增 |
| Pydantic Model Builder | ❌ 无 | 需新增 |
| A2A Message Protocol | ❌ 无 | 需新增 |
| Agent Lifecycle Manager | ❌ 无 | 需新增 |

### 2.4 需要支持的错误处理和文档

**错误处理规范:**
- 结构化异常层级（AgentPlatformError → AgentError → TaskError）
- FastAPI HTTPException 映射规范
- async 错误传播规范（不丢失 traceback）
- 超时和重试策略

**文档规范:**
- 函数/类 docstring 自动生成
- API endpoint 描述生成（FastAPI summary/description）
- 类型注解完整性检查

---

## 改造方案

### 方案 A: 最小改造（只改 prompts 和 patterns）

**改造范围:**

```
修改文件:
├── src/architect/analysis/llm_analyzer.py
│   └── _build_file_prompt()  ← 增加 agent-platform 感知提示词
│
├── src/architect/api/agent_runner.py
│   └── SYSTEM_PROMPT  ← 添加 agent-platform 代码规范
│
└── src/architect/patterns/catalog.py
    └── 新增 8 个 agent-platform 专项模式定义
```

**实施步骤:**

1. **扩展 `_build_file_prompt()`** — 检测 agent-platform 特征（FastAPI、Pydantic、asyncio），动态生成专项分析问题：
```python
# 当前:
"Analyze this {language} file. Return a JSON..."

# 改造后:
def _build_file_prompt(self, file_path, content):
    platform_hints = self._detect_platform_features(content)
    if platform_hints.get('is_fastapi'):
        extra = "Pay special attention to: dependency injection chains, route patterns, lifespan handlers."
    if platform_hints.get('has_pydantic'):
        extra += "Document all Pydantic models, validators, and model_config settings."
    if platform_hints.get('is_async'):
        extra += "Document async patterns: coroutines, context managers, event loops."
    ...
```

2. **扩展 AgentRunner system prompt** — 添加 agent-platform 编码规范：
```python
AGENT_PLATFORM_RULES = """
When generating code for this project:
- Use Python type hints everywhere
- All I/O operations must be async
- Use Pydantic v2 BaseModel for all data structures
- Use FastAPI Depends() for dependency injection
- Follow existing naming conventions from project analysis
- Generate corresponding docstrings
"""
```

3. **扩展 patterns/catalog.py** — 新增 8 种模式：
- AsyncContextManager
- FastAPIDepends
- PydanticV2Model
- AgentFactoryFunction
- AsyncRepository
- RetryWithBackoff
- AgentLifecycle
- A2AMessageProtocol

**工作量估计:** 3-5 天，~800 行代码改动  
**风险:** 低（不改动架构，回退容易）  
**质量:** 提升幅度有限，LLM 仍需要"猜"规范

---

### 方案 B: 中等改造（新增专用模块）

**改造范围:** 在方案 A 基础上，新增 3 个专用模块：

```
新增文件:
├── src/architect/codegen/
│   ├── __init__.py
│   ├── templates.py          代码模板引擎（Jinja2 或纯字符串）
│   ├── agent_platform_gen.py  agent-platform 专项代码生成器
│   └── type_checker.py       生成后类型注解验证
│
├── src/architect/patterns/
│   └── agent_platform_patterns.py  ← 新增，独立文件
│
└── src/architect/api/
    └── codegen_endpoints.py   ← 新增专用端点

修改文件:
├── src/architect/analysis/llm_analyzer.py
│   └── 增加平台特征检测方法
│
├── src/architect/api/agent_runner.py
│   └── 增加 agent-platform 工具集
│
└── src/architect/api/main.py
    └── 注册新端点
```

**核心新增模块详细设计:**

**`src/architect/codegen/agent_platform_gen.py`:**
```python
class AgentPlatformCodeGen:
    """专用于 agent-platform 的代码生成器"""
    
    def __init__(self, project_modules: List[dict], llm_client: LLMClient):
        self.modules = project_modules
        self.llm = llm_client
        self.conventions = self._extract_conventions()
    
    def _extract_conventions(self) -> ProjectConventions:
        """从 modules.json 提取项目惯例"""
        # 分析命名风格、import 风格、类结构等
        ...
    
    async def generate_pydantic_model(self, spec: ModelSpec) -> str:
        """生成 Pydantic v2 模型，遵循项目惯例"""
        ...
    
    async def generate_fastapi_route(self, spec: RouteSpec) -> str:
        """生成 FastAPI 路由 + DI"""
        ...
    
    async def generate_async_service(self, spec: ServiceSpec) -> str:
        """生成 async 服务类"""
        ...
    
    async def generate_factory_function(self, spec: FactorySpec) -> str:
        """生成工厂函数"""
        ...
```

**`src/architect/codegen/templates.py`:**
```python
# Pydantic v2 模板
PYDANTIC_MODEL_TEMPLATE = '''
class {name}(BaseModel):
    """
    {description}
    
    Attributes:
{attributes_doc}
    """
    model_config = ConfigDict(
        {config_options}
    )
    
{fields}
    
{validators}
'''

# FastAPI 路由模板
FASTAPI_ROUTE_TEMPLATE = '''
@router.{method}(
    "/{path}",
    response_model={response_model},
    summary="{summary}",
)
async def {handler_name}(
{params}
) -> {return_type}:
    """
    {description}
    
    Args:
{args_doc}
    
    Returns:
{returns_doc}
    """
{body}
'''
```

**新增 API 端点:**
```python
# POST /api/codegen/pydantic-model
# POST /api/codegen/fastapi-route
# POST /api/codegen/async-service
# POST /api/codegen/factory-function
```

**工作量估计:** 10-15 天，~3,000 行新增代码  
**风险:** 中（需要为新模块写测试，模板维护成本）  
**质量:** 显著提升，生成代码质量稳定可预期

---

### 方案 C: 完整改造（重构核心）

**改造范围:** 深度重构，将 Code Architect 变成 agent-platform 专用开发助手：

```
架构变更:
├── 分析层重构
│   ├── 多维度分析 (一般 + agent-platform 专项)
│   ├── AST 级深度解析 (利用已有 tree-sitter)
│   └── 依赖图构建 (模块间关系)
│
├── 知识库重构
│   ├── agent-platform 最佳实践库
│   ├── 代码风格规则引擎
│   └── 反模式检测（anti-pattern detection）
│
├── 生成层重构
│   ├── 意图理解 → 代码规划 → 代码生成 三阶段
│   ├── 生成后自动验证（AST 解析、类型检查）
│   └── 自动生成对应测试
│
└── 新 API 层
    ├── 完整 REST API 重设计
    ├── GraphQL 可选接口
    └── 双向 WebSocket (push + pull)
```

**核心重构内容:**

1. **LLMAnalyzer 深度扩展** — 两阶段分析：
   - 第一阶段：现有通用分析（保留）
   - 第二阶段：agent-platform 专项深度分析（新增）
     - 检测所有 Pydantic 模型的字段定义
     - 分析所有 FastAPI Depends 链
     - 绘制 async 函数调用图
     - 识别 Agent 生命周期模式

2. **知识驱动生成 (Knowledge-Driven Generation):**
```python
class KnowledgeDrivenCodeGen:
    """基于项目知识图谱的代码生成"""
    
    def __init__(
        self,
        knowledge_graph: ProjectKnowledgeGraph,
        rule_engine: CodingRuleEngine,
        llm_client: LLMClient,
    ):
        ...
    
    async def generate(self, task: GenerationTask) -> GenerationResult:
        # 1. 理解意图
        intent = await self._understand_intent(task)
        # 2. 检索相似代码片段
        similar = self.knowledge_graph.find_similar(intent)
        # 3. 提取项目惯例
        conventions = self.knowledge_graph.get_conventions(intent.domain)
        # 4. LLM 生成（带丰富上下文）
        code = await self._generate_with_context(intent, similar, conventions)
        # 5. 自动验证
        validated = await self._validate(code)
        # 6. 返回
        return GenerationResult(code=validated, tests=self._generate_tests(validated))
```

3. **规则引擎 (CodingRuleEngine):**
```python
class AgentPlatformRules:
    RULES = [
        Rule("all_io_must_be_async", "所有 I/O 操作必须是 async"),
        Rule("pydantic_v2_required", "数据模型必须继承 Pydantic BaseModel"),
        Rule("type_hints_required", "所有函数参数和返回值必须有类型注解"),
        Rule("docstring_required", "公共函数/类必须有 docstring"),
        Rule("error_handling_pattern", "必须使用项目标准异常层级"),
    ]
```

**工作量估计:** 35-45 天，~8,000 行新增/重构代码  
**风险:** 高（大规模重构，可能破坏现有功能）  
**质量:** 最高，但开发成本和维护成本也最高

---

### 推荐方案

**推荐: 方案 B（中等改造）**

**理由：**

1. **性价比最优** — 10-15 天的工作量可以获得实质性的能力提升，相比方案 C 减少 60% 工作量，相比方案 A 质量提升 40%+

2. **风险可控** — 新增模块不破坏现有功能，原有 A2A API 完整保留，可以渐进部署

3. **架构合理** — 专用 `codegen/` 模块具有清晰的关注点分离，易于测试和维护

4. **可扩展** — 方案 B 建立的 template 引擎和 pattern 库为日后向方案 C 演进提供基础

5. **现有优势保留** — 分析、记忆、RAG、A2A 等成熟功能完全继承

---

## 工作量估计

### 4.1 方案 A 工作量明细

| 任务 | 代码行数 | 工时 |
|------|---------|------|
| 扩展 `_build_file_prompt()` | 80 行 | 4h |
| 添加平台特征检测方法 | 100 行 | 6h |
| 扩展 AgentRunner system prompt | 60 行 | 3h |
| 新增 8 个 catalog 模式 | 400 行 | 8h |
| 更新 pattern detector 规则 | 120 行 | 6h |
| 单元测试 | 50 行 | 4h |
| **合计** | **~810 行** | **31h (~4天)** |

### 4.2 方案 B 工作量明细

| 模块 | 任务 | 代码行数 | 工时 |
|------|------|---------|------|
| 方案 A | 全部 | 810 行 | 31h |
| codegen/templates.py | 代码模板引擎 | 400 行 | 12h |
| codegen/agent_platform_gen.py | 核心生成器 | 600 行 | 20h |
| codegen/type_checker.py | 类型验证器 | 250 行 | 10h |
| patterns/agent_platform_patterns.py | 专项模式 | 350 行 | 10h |
| api/codegen_endpoints.py | 新 API 端点 | 300 行 | 10h |
| api/schemas.py 扩展 | 新 Pydantic 模型 | 200 行 | 6h |
| api/main.py 集成 | 路由注册 | 80 行 | 3h |
| 测试: codegen/ | 单元测试 | 400 行 | 16h |
| 测试: 集成测试 | E2E 测试 | 200 行 | 8h |
| 文档更新 | README + API 文档 | - | 6h |
| **合计** | | **~3,590 行** | **132h (~17天)** |

### 4.3 方案 C 工作量明细

| 模块 | 任务 | 代码行数 | 工时 |
|------|------|---------|------|
| 方案 B | 全部 | 3,590 行 | 132h |
| 知识图谱构建 | ProjectKnowledgeGraph | 800 行 | 30h |
| 规则引擎 | CodingRuleEngine | 500 行 | 20h |
| 意图理解层 | IntentUnderstanding | 400 行 | 16h |
| 自动测试生成 | TestGenerator | 600 行 | 24h |
| AST 深度解析 | 扩展现有 parsers/ | 600 行 | 24h |
| 依赖图 | DependencyGraph | 400 行 | 16h |
| API 重设计 | 新路由结构 | 500 行 | 20h |
| 测试: 新模块 | | 800 行 | 32h |
| 迁移 & 兼容 | 旧 API 兼容层 | 200 行 | 8h |
| **合计** | | **~8,390 行** | **322h (~40天)** |

### 4.4 各方案对比

| 维度 | 方案 A | 方案 B | 方案 C |
|------|--------|--------|--------|
| 开发周期 | 4 天 | 17 天 | 40 天 |
| 代码改动 | ~810 行 | ~3,590 行 | ~8,390 行 |
| 风险等级 | 🟢 低 | 🟡 中 | 🔴 高 |
| 质量提升 | +30% | +65% | +90% |
| 架构破坏性 | 无 | 无（新增） | 中（重构） |
| 可维护性 | 高 | 高 | 中（复杂度高） |
| 测试覆盖要求 | 低 | 中 | 高 |

### 4.5 风险评估

**方案 B 主要风险:**

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 模板引擎生成代码质量不稳定 | 中 | 高 | 添加 AST 后验证，失败时降级到无模板模式 |
| agent-platform 惯例理解不准确 | 中 | 中 | 先手动定义规则，后通过实际项目校正 |
| 新模块与现有 agent_runner.py 集成冲突 | 低 | 中 | 新模块设计为独立组件，通过 DI 注入 |
| LLM 成本上升（更复杂 prompt） | 低 | 低 | 对 codegen 请求使用更轻量模型 |

**关键路径:**
```
1. templates.py (12h) → 2. agent_platform_gen.py (20h) → 3. codegen_endpoints.py (10h)
                                  ↑
               agent_platform_patterns.py (10h) [并行]
```

---

## 集成策略

### 5.1 集成到 agent-platform 的两种方式

**方式一：A2A API 集成（推荐）**

Code Architect 作为独立服务运行，agent-platform 通过 REST API 调用：

```
agent-platform          code-architect-agent-platform
     │                           │
     │  POST /api/a2a/generate   │
     │ ─────────────────────────►│
     │                           │ (分析项目记忆)
     │                           │ (生成代码)
     │    GenerateResponse       │
     │ ◄─────────────────────────│
     │                           │
     │  POST /api/codegen/      │  (新增，方案B)
     │     pydantic-model        │
     │ ─────────────────────────►│
     │                           │
```

**优势:**
- 服务解耦，独立扩展
- Code Architect 可为多个 agent-platform 实例服务
- 版本独立更新
- 故障隔离

**方式二：直接嵌入（备选）**

将 `codegen/` 模块作为 Python 包引入 agent-platform：

```python
# agent-platform 代码中
from code_architect.codegen import AgentPlatformCodeGen

codegen = AgentPlatformCodeGen(project_modules=modules)
code = await codegen.generate_pydantic_model(spec)
```

**劣势:** 紧耦合、环境依赖冲突风险

### 5.2 数据流设计（推荐 A2A 方式）

```
                    ┌─────────────────────────────────────────────┐
                    │        agent-platform (消费方)               │
                    │                                             │
                    │  ┌──────────┐    ┌──────────────────────┐  │
                    │  │ Task     │───►│ CodeGenOrchestrator   │  │
                    │  │ Manager  │    │  (新建，调 Code Arch)  │  │
                    │  └──────────┘    └──────────┬───────────┘  │
                    └────────────────────────────│────────────────┘
                                                 │ HTTP
                                                 ▼
                    ┌─────────────────────────────────────────────┐
                    │    code-architect-agent-platform (服务方)    │
                    │                                             │
                    │  ┌──────────────┐   ┌──────────────────┐  │
                    │  │  分析引擎     │──►│  代码生成引擎      │  │
                    │  │ LLMAnalyzer  │   │ AgentPlatformGen  │  │
                    │  └──────────────┘   └──────────────────┘  │
                    │         │                    │              │
                    │  ┌──────▼────────────────────▼──────────┐  │
                    │  │          项目记忆 (modules.json)       │  │
                    │  │          + patterns 知识库             │  │
                    │  └───────────────────────────────────────┘  │
                    └─────────────────────────────────────────────┘
```

**调用流程:**

1. agent-platform 先调用 `POST /api/analyze` 分析目标项目（一次性）
2. 得到 `project_id` 和分析记忆
3. 后续代码生成调用 `POST /api/a2a/generate`，传入 project_id 和任务描述
4. Code Architect 从记忆加载项目上下文，生成符合项目惯例的代码
5. 可选：调用 `POST /api/a2a/validate` 验证生成结果
6. 可选：调用 `POST /api/a2a/impact` 评估改动影响

### 5.3 新增 API 端点规范（方案 B）

```yaml
# 新增专用端点

POST /api/codegen/pydantic-model:
  description: 生成 Pydantic v2 模型
  request:
    project_id: string
    model_name: string
    fields: list[FieldSpec]
    inherit_from: string?
    config_options: dict?
  response:
    code: string     # 生成的完整 Python 代码
    imports: list    # 需要的 import 语句
    tests: string    # 对应测试骨架

POST /api/codegen/fastapi-route:
  description: 生成 FastAPI 路由 + 依赖注入
  request:
    project_id: string
    method: GET|POST|PUT|DELETE|PATCH
    path: string
    handler_name: string
    request_model: string?
    response_model: string
    dependencies: list[string]
  response:
    code: string
    imports: list

POST /api/codegen/async-service:
  description: 生成 async 服务类
  request:
    project_id: string
    class_name: string
    methods: list[MethodSpec]
    dependencies: list[string]
  response:
    code: string
    tests: string

POST /api/codegen/factory-function:
  description: 生成工厂函数
  request:
    project_id: string
    factory_name: string
    return_type: string
    variants: list[string]
  response:
    code: string
```

---

## 时间表

### 6.1 方案 B 里程碑

```
Week 1 (Day 1-5):
  Day 1-2:  方案 A 内容（prompt 扩展 + 基础模式新增）
  Day 3-4:  agent_platform_patterns.py 新增 10 个专项模式
  Day 5:    集成测试，验证分析能力提升

Week 2 (Day 6-10):
  Day 6-7:  codegen/templates.py 模板引擎设计与实现
  Day 8-9:  codegen/agent_platform_gen.py 核心生成器
  Day 10:   单元测试 + 代码评审

Week 3 (Day 11-15):
  Day 11-12: codegen/type_checker.py 类型验证
  Day 13-14: api/codegen_endpoints.py 新 API + main.py 集成
  Day 15:    完整 E2E 测试

Week 4 (Day 16-17):
  Day 16:   性能优化（缓存模板渲染，批量生成）
  Day 17:   文档更新（README、API 文档）+ 部署准备
```

### 6.2 关键路径分析

```
关键路径（不可并行部分）:
方案A基础 (4天) → templates.py (2天) → agent_platform_gen.py (2天) → API端点 (2天)
= 最短 10 天（关键路径）

可并行部分:
- type_checker.py 可与 agent_platform_gen.py 同时开发
- agent_platform_patterns.py 可与模板引擎并行
- 单元测试可随开发同步编写

总计: 17 天（加 7 天缓冲建议保留 3 周）
```

### 6.3 完成时间预估

| 方案 | 乐观估计 | 正常估计 | 悲观估计 |
|------|---------|---------|---------|
| A | 3 天 | 4 天 | 6 天 |
| B | 14 天 | 17 天 | 22 天 |
| C | 35 天 | 40 天 | 55 天 |

**方案 B 预计完成日期:** 如从 2026-03-18 开始，正常 2026-04-07，最迟 2026-04-08

---

## 最终建议

### 核心建议

**立即采用方案 B（中等改造）。**

### 行动计划（按优先级）

**第一周（立即开始）:**
1. 在复制件 `code-architect-agent-platform/` 上开始工作，保护原始版本
2. 扩展 `_build_file_prompt()` — 最快能看到效果的改动（1天可完成）
3. 新增 `patterns/agent_platform_patterns.py` — 奠定模式识别基础

**第二周:**
4. 实现 `codegen/templates.py` — 关键基础组件
5. 实现 `codegen/agent_platform_gen.py` — 核心价值

**第三周:**
6. 实现 API 端点并集成到 agent-platform
7. 端对端测试

### 关键风险和缓解措施

| 风险 | 建议 |
|------|------|
| 生成代码质量不稳定 | 先实现 type_checker.py 自动验证，不通过则标记人工审查 |
| LLM prompt 效果不确定 | 对每个新功能做 A/B 测试，记录生成质量指标 |
| 范围蔓延 | 严格按优先级执行，Nice-to-have 放第二阶段 |
| 项目惯例理解偏差 | 先人工定义 agent-platform 规则集，后续通过项目分析自动更新 |

### 与方案 A 和 C 的取舍

- **不选方案 A** 的原因：纯 prompt 改造效果有限，LLM 缺乏结构化约束，生成代码质量不可控
- **不选方案 C** 的原因：40 天开发周期过长，当前需求不需要知识图谱的复杂度；可以在方案 B 稳定后作为下一阶段迭代

### 预期收益

完成方案 B 后，Code Architect 将能够：

1. ✅ 生成符合项目惯例的 Pydantic v2 模型（质量提升 ~65%）
2. ✅ 生成正确的 FastAPI 路由 + 依赖注入链
3. ✅ 识别 10 种 agent-platform 专项设计模式
4. ✅ 通过专用端点支持结构化代码生成请求
5. ✅ 对生成代码进行类型注解完整性验证
6. ✅ 全程通过 A2A API 与 agent-platform 集成，无需嵌入

---

*报告生成时间: 2026-03-18 | 评估者: Architect Agent*
