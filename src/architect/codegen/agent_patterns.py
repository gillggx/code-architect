"""
Agent Lifecycle Patterns Template Engine

Generates Agent lifecycle patterns with:
- Agent Session creation patterns
- Memory system integration (short/long-term)
- Knowledge Pack binding
- State transitions (created → active → done)

Version: 1.0
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class AgentState(Enum):
    """Agent lifecycle states
    
    中文: Agent生命周期状态
    """
    CREATED = "created"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    PAUSED = "paused"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"
    TERMINATED = "terminated"


class MemoryType(Enum):
    """Memory system types
    
    中文: 记忆系统类型
    """
    SHORT_TERM = "short_term"  # Working memory
    LONG_TERM = "long_term"    # Persistent memory
    EPISODIC = "episodic"      # Event-based memory
    SEMANTIC = "semantic"      # Knowledge/facts


@dataclass
class MemoryConfig:
    """Memory system configuration
    
    中文: 记忆系统配置
    """
    enabled: bool = True
    short_term_capacity: int = 100  # Max entries
    long_term_persistence: bool = True
    memory_types: List[MemoryType] = field(default_factory=lambda: [
        MemoryType.SHORT_TERM,
        MemoryType.LONG_TERM,
        MemoryType.EPISODIC,
    ])
    description_cn: str = "代理记忆系统"
    description_en: str = "Agent memory system"


@dataclass
class KnowledgePackConfig:
    """Knowledge Pack binding configuration
    
    中文: 知识包绑定配置
    """
    name: str
    version: str = "1.0"
    enabled: bool = True
    auto_load: bool = True
    description_cn: str = ""
    description_en: str = ""


@dataclass
class AgentSessionConfig:
    """Agent Session configuration
    
    中文: Agent Session 配置
    """
    agent_id: str
    agent_name: str
    role: str  # e.g., "architect", "coder", "reviewer"
    description_cn: str = ""
    description_en: str = ""
    memory: Optional[MemoryConfig] = None
    knowledge_packs: List[KnowledgePackConfig] = field(default_factory=list)
    auto_state_transition: bool = True
    max_retries: int = 3
    timeout_seconds: int = 300


class AgentPatternsTemplate:
    """Agent lifecycle patterns code generator
    
    中文: Agent生命周期模式代码生成器
    """
    
    def __init__(self):
        """Initialize Agent patterns template engine"""
        pass
    
    def generate_state_machine_class(self) -> str:
        """Generate Agent state machine class
        
        中文: 生成 Agent 状态机类
        
        Returns:
            State machine class code
        """
        return '''class AgentStateMachine:
    """Agent state machine for lifecycle management
    
    中文: Agent状态机用于生命周期管理
    """
    
    def __init__(self, initial_state: AgentState = AgentState.CREATED):
        """Initialize state machine
        
        Args:
            initial_state: Initial agent state
        """
        self._state = initial_state
        self._state_history: List[Tuple[AgentState, datetime]] = []
        self._lock = asyncio.Lock()
    
    async def transition(self, new_state: AgentState) -> bool:
        """Transition to new state with validation
        
        中文: 验证并转换到新状态
        
        Args:
            new_state: Target state
        
        Returns:
            True if transition successful, False otherwise
        """
        async with self._lock:
            # Validate transition
            if not self._is_valid_transition(self._state, new_state):
                return False
            
            # Record transition
            self._state_history.append((self._state, datetime.utcnow()))
            self._state = new_state
            return True
    
    def _is_valid_transition(self, from_state: AgentState, to_state: AgentState) -> bool:
        """Validate state transition rules
        
        中文: 验证状态转换规则
        """
        valid_transitions = {
            AgentState.CREATED: [AgentState.INITIALIZING],
            AgentState.INITIALIZING: [AgentState.ACTIVE, AgentState.FAILED],
            AgentState.ACTIVE: [AgentState.IDLE, AgentState.EXECUTING, AgentState.PAUSED, AgentState.FAILED],
            AgentState.IDLE: [AgentState.EXECUTING, AgentState.PAUSED, AgentState.DONE],
            AgentState.EXECUTING: [AgentState.IDLE, AgentState.FAILED, AgentState.PAUSED],
            AgentState.PAUSED: [AgentState.EXECUTING, AgentState.DONE, AgentState.TERMINATED],
            AgentState.DONE: [AgentState.TERMINATED],
            AgentState.FAILED: [AgentState.TERMINATED],
        }
        return to_state in valid_transitions.get(from_state, [])
    
    @property
    def current_state(self) -> AgentState:
        """Get current state"""
        return self._state
    
    @property
    def state_history(self) -> List[Tuple[AgentState, datetime]]:
        """Get state transition history"""
        return self._state_history.copy()
'''
    
    def generate_memory_system(self, config: MemoryConfig) -> str:
        """Generate memory system class
        
        中文: 生成记忆系统类
        
        Args:
            config: Memory configuration
        
        Returns:
            Memory system class code
        """
        lines = []
        lines.append("class AgentMemory:")
        lines.append(f'    """{config.description_en}')
        lines.append(f'    {config.description_cn}"""')
        lines.append("")
        
        lines.append("    def __init__(self, config: MemoryConfig):")
        lines.append("        self.config = config")
        lines.append("        self.short_term: Dict[str, Any] = {}")
        lines.append("        self.long_term: Dict[str, Any] = {}")
        lines.append("        self.episodic: List[Dict[str, Any]] = []")
        lines.append("        self.semantic: Dict[str, Any] = {}")
        lines.append("")
        
        lines.append("    async def remember(self, key: str, value: Any, memory_type: MemoryType = MemoryType.SHORT_TERM) -> None:")
        lines.append('        """Store information in memory')
        lines.append('        ')
        lines.append('        中文: 在内存中存储信息"""')
        lines.append("        if memory_type == MemoryType.SHORT_TERM:")
        lines.append("            self.short_term[key] = value")
        lines.append("        elif memory_type == MemoryType.LONG_TERM:")
        lines.append("            self.long_term[key] = value")
        lines.append("            if self.config.long_term_persistence:")
        lines.append("                await self._persist_long_term(key, value)")
        lines.append("        elif memory_type == MemoryType.EPISODIC:")
        lines.append("            self.episodic.append({")
        lines.append("                'timestamp': datetime.utcnow(),")
        lines.append("                'key': key,")
        lines.append("                'value': value,")
        lines.append("            })")
        lines.append("        elif memory_type == MemoryType.SEMANTIC:")
        lines.append("            self.semantic[key] = value")
        lines.append("")
        
        lines.append("    async def recall(self, key: str, memory_type: MemoryType = MemoryType.SHORT_TERM) -> Optional[Any]:")
        lines.append('        """Retrieve information from memory')
        lines.append('        ')
        lines.append('        中文: 从内存中检索信息"""')
        lines.append("        if memory_type == MemoryType.SHORT_TERM:")
        lines.append("            return self.short_term.get(key)")
        lines.append("        elif memory_type == MemoryType.LONG_TERM:")
        lines.append("            return self.long_term.get(key)")
        lines.append("        elif memory_type == MemoryType.SEMANTIC:")
        lines.append("            return self.semantic.get(key)")
        lines.append("        return None")
        lines.append("")
        
        lines.append("    async def _persist_long_term(self, key: str, value: Any) -> None:")
        lines.append('        """Persist long-term memory to storage')
        lines.append('        ')
        lines.append('        中文: 将长期记忆持久化到存储"""')
        lines.append("        # TODO: Implement persistence logic")
        lines.append("        pass")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_knowledge_pack_binding(self, knowledge_pack: KnowledgePackConfig) -> str:
        """Generate knowledge pack binding code
        
        中文: 生成知识包绑定代码
        
        Args:
            knowledge_pack: Knowledge pack configuration
        
        Returns:
            Knowledge pack binding code
        """
        lines = []
        lines.append(f"# Knowledge Pack: {knowledge_pack.name} v{knowledge_pack.version}")
        lines.append(f"# {knowledge_pack.description_en}")
        lines.append(f"# {knowledge_pack.description_cn}")
        lines.append("")
        lines.append(f"KNOWLEDGE_PACK_{knowledge_pack.name.upper()} = {{")
        lines.append(f'    "name": "{knowledge_pack.name}",')
        lines.append(f'    "version": "{knowledge_pack.version}",')
        lines.append(f'    "enabled": {knowledge_pack.enabled},')
        lines.append(f'    "auto_load": {knowledge_pack.auto_load},')
        lines.append(f'    "description": "{knowledge_pack.description_en}",')
        lines.append("}")
        lines.append("")
        return "\n".join(lines)
    
    def generate_agent_session_class(self, config: AgentSessionConfig) -> str:
        """Generate Agent Session creation class
        
        中文: 生成 Agent Session 创建类
        
        Args:
            config: Agent session configuration
        
        Returns:
            Agent session class code
        """
        lines = []
        lines.append("class AgentSession:")
        lines.append(f'    """{config.agent_name} Session')
        lines.append(f'    {config.description_en}')
        lines.append(f'    {config.description_cn}')
        lines.append('    """')
        lines.append("")
        
        lines.append("    def __init__(self, config: AgentSessionConfig):")
        lines.append("        self.config = config")
        lines.append("        self.session_id = str(uuid4())")
        lines.append("        self.created_at = datetime.utcnow()")
        lines.append("        self.state_machine = AgentStateMachine()")
        lines.append("        self.memory = AgentMemory(config.memory or MemoryConfig())")
        lines.append("        self.knowledge_packs = {}")
        lines.append("        self.execution_history: List[Dict[str, Any]] = []")
        lines.append("")
        
        lines.append("    async def initialize(self) -> bool:")
        lines.append('        """Initialize agent session')
        lines.append('        ')
        lines.append('        中文: 初始化 agent session"""')
        lines.append("        try:")
        lines.append("            # Transition to INITIALIZING")
        lines.append("            await self.state_machine.transition(AgentState.INITIALIZING)")
        lines.append("")
        lines.append("            # Load knowledge packs")
        lines.append("            for kp_config in self.config.knowledge_packs:")
        lines.append("                if kp_config.auto_load:")
        lines.append("                    await self._load_knowledge_pack(kp_config)")
        lines.append("")
        lines.append("            # Transition to ACTIVE")
        lines.append("            await self.state_machine.transition(AgentState.ACTIVE)")
        lines.append("            return True")
        lines.append("        except Exception as e:")
        lines.append("            await self.state_machine.transition(AgentState.FAILED)")
        lines.append("            return False")
        lines.append("")
        
        lines.append("    async def _load_knowledge_pack(self, config: KnowledgePackConfig) -> None:")
        lines.append('        """Load knowledge pack')
        lines.append('        ')
        lines.append('        中文: 加载知识包"""')
        lines.append("        # TODO: Implement knowledge pack loading")
        lines.append("        self.knowledge_packs[config.name] = config")
        lines.append("")
        
        lines.append("    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:")
        lines.append('        """Execute task in agent session')
        lines.append('        ')
        lines.append('        中文: 在 agent session 中执行任务"""')
        lines.append("        try:")
        lines.append("            await self.state_machine.transition(AgentState.EXECUTING)")
        lines.append("            # TODO: Implement task execution logic")
        lines.append("            result = {}")
        lines.append("            self.execution_history.append(result)")
        lines.append("            await self.state_machine.transition(AgentState.IDLE)")
        lines.append("            return result")
        lines.append("        except Exception as e:")
        lines.append("            await self.state_machine.transition(AgentState.FAILED)")
        lines.append("            raise")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_complete_agent_module(self, config: AgentSessionConfig) -> str:
        """Generate complete agent module with all patterns
        
        中文: 生成包含所有模式的完整agent模块
        
        Args:
            config: Agent session configuration
        
        Returns:
            Complete module code
        """
        lines = []
        
        # Header
        lines.append(f'"""Agent Module - {config.agent_name}')
        lines.append(f'{config.description_en}')
        lines.append(f'{config.description_cn}')
        lines.append('"""')
        lines.append("")
        
        # Imports
        lines.append("import asyncio")
        lines.append("from typing import Optional, List, Dict, Any, Tuple")
        lines.append("from datetime import datetime")
        lines.append("from uuid import uuid4")
        lines.append("from enum import Enum")
        lines.append("from dataclasses import dataclass, field")
        lines.append("")
        
        # State and Memory enums
        lines.append("class AgentState(Enum):")
        for state in AgentState:
            lines.append(f'    {state.name} = "{state.value}"')
        lines.append("")
        
        lines.append("class MemoryType(Enum):")
        for mem_type in MemoryType:
            lines.append(f'    {mem_type.name} = "{mem_type.value}"')
        lines.append("")
        
        # State machine
        lines.append(self.generate_state_machine_class())
        lines.append("")
        
        # Memory system
        lines.append(self.generate_memory_system(config.memory or MemoryConfig()))
        lines.append("")
        
        # Knowledge packs
        for kp in config.knowledge_packs:
            lines.append(self.generate_knowledge_pack_binding(kp))
        
        # Agent session
        lines.append(self.generate_agent_session_class(config))
        
        return "\n".join(lines)
