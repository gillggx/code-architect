"""
Async Patterns Template Engine

Generates async patterns with:
- async def function signatures
- asyncio.gather() concurrent patterns
- AsyncSession (SQLAlchemy)
- try/except/finally async error handling

Version: 1.0
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum


class ConcurrencyPattern(Enum):
    """Concurrency patterns for async operations
    
    中文: 异步操作的并发模式
    """
    GATHER = "gather"          # asyncio.gather - run all concurrently
    TASK = "task"              # asyncio.create_task - fire and forget
    WAIT = "wait"              # asyncio.wait - wait with conditions
    POOL = "pool"              # Semaphore-based concurrency limiting
    QUEUE = "queue"            # asyncio.Queue - producer-consumer
    LOCK = "lock"              # asyncio.Lock - mutual exclusion


@dataclass
class AsyncFunctionDef:
    """Async function definition
    
    中文: 异步函数定义
    """
    name: str
    parameters: List[Tuple[str, str]]  # [(param_name, type_hint)]
    return_type: str = "Any"
    description_cn: str = ""
    description_en: str = ""
    concurrent_calls: List[str] = None  # List of async calls to run concurrently
    error_handlers: Dict[str, str] = None  # {exception_type: handler_name}
    timeout_seconds: Optional[float] = None
    is_generator: bool = False  # async generator
    
    def __post_init__(self):
        if self.concurrent_calls is None:
            self.concurrent_calls = []
        if self.error_handlers is None:
            self.error_handlers = {}


@dataclass
class AsyncSessionDef:
    """AsyncSession (SQLAlchemy) definition
    
    中文: AsyncSession (SQLAlchemy) 定义
    """
    name: str
    engine_url: str  # Database connection string
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False
    description_cn: str = ""
    description_en: str = ""


class AsyncPatternsTemplate:
    """Async patterns code generator
    
    中文: 异步模式代码生成器
    """
    
    def __init__(self):
        """Initialize async patterns template engine"""
        pass
    
    def generate_async_function_signature(self, func_def: AsyncFunctionDef) -> str:
        """Generate async function signature
        
        中文: 生成异步函数签名
        
        Args:
            func_def: Function definition
        
        Returns:
            Function signature
        """
        params = ", ".join([f"{name}: {type_hint}" for name, type_hint in func_def.parameters])
        
        if func_def.is_generator:
            return f"async def {func_def.name}({params}) -> AsyncGenerator[{func_def.return_type}, None]:"
        else:
            return f"async def {func_def.name}({params}) -> {func_def.return_type}:"
    
    def generate_docstring(self, func_def: AsyncFunctionDef) -> str:
        """Generate bilingual docstring for async function
        
        中文: 为异步函数生成双语文档字符串
        
        Args:
            func_def: Function definition
        
        Returns:
            Docstring block
        """
        lines = ['    """']
        
        if func_def.description_cn:
            lines.append(f"    {func_def.description_cn}")
        if func_def.description_en:
            lines.append(f"    {func_def.description_en}")
        
        if func_def.timeout_seconds:
            lines.append("")
            lines.append(f"    Timeout: {func_def.timeout_seconds}s")
        
        lines.append('    """')
        return "\n".join(lines)
    
    def generate_gather_pattern(self, func_def: AsyncFunctionDef) -> str:
        """Generate asyncio.gather() concurrent pattern
        
        中文: 生成 asyncio.gather() 并发模式
        
        Args:
            func_def: Function definition with concurrent_calls
        
        Returns:
            Function code with gather pattern
        """
        lines = []
        lines.append(self.generate_async_function_signature(func_def))
        lines.append(self.generate_docstring(func_def))
        
        lines.append("    try:")
        if func_def.concurrent_calls:
            calls_str = ",\n            ".join(func_def.concurrent_calls)
            lines.append(f"        results = await asyncio.gather(")
            lines.append(f"            {calls_str},")
            lines.append(f"            return_exceptions=True")
            lines.append(f"        )")
        else:
            lines.append("        results = []")
        
        # Error handling
        if func_def.error_handlers:
            lines.append("")
            lines.append("        # Check for exceptions in results")
            lines.append("        for i, result in enumerate(results):")
            lines.append("            if isinstance(result, Exception):")
            lines.append('                logger.error(f"Task {i} failed: {result}")')
        
        lines.append("        return results")
        lines.append("    except Exception as e:")
        lines.append('        logger.error(f"Gather pattern failed: {e}")')
        lines.append("        raise")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_semaphore_pool_pattern(self, func_def: AsyncFunctionDef, max_concurrent: int = 5) -> str:
        """Generate semaphore-based concurrency limiting pattern
        
        中文: 生成基于信号量的并发限制模式
        
        Args:
            func_def: Function definition
            max_concurrent: Maximum concurrent tasks
        
        Returns:
            Function code with semaphore pattern
        """
        lines = []
        lines.append(self.generate_async_function_signature(func_def))
        lines.append(self.generate_docstring(func_def))
        
        lines.append(f"    semaphore = asyncio.Semaphore({max_concurrent})")
        lines.append("    ")
        lines.append("    async def bounded_call(task):")
        lines.append("        async with semaphore:")
        lines.append("            return await task")
        lines.append("")
        
        lines.append("    try:")
        if func_def.concurrent_calls:
            calls_str = ",\n            ".join([f"bounded_call({call})" for call in func_def.concurrent_calls])
            lines.append(f"        results = await asyncio.gather(")
            lines.append(f"            {calls_str},")
            lines.append(f"            return_exceptions=True")
            lines.append(f"        )")
        lines.append("        return results")
        lines.append("    except Exception as e:")
        lines.append('        logger.error(f"Semaphore pool pattern failed: {e}")')
        lines.append("        raise")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_timeout_pattern(self, func_def: AsyncFunctionDef) -> str:
        """Generate asyncio.wait_for() timeout pattern
        
        中文: 生成 asyncio.wait_for() 超时模式
        
        Args:
            func_def: Function definition with timeout_seconds
        
        Returns:
            Function code with timeout pattern
        """
        lines = []
        lines.append(self.generate_async_function_signature(func_def))
        lines.append(self.generate_docstring(func_def))
        
        timeout = func_def.timeout_seconds or 30
        
        lines.append("    try:")
        if func_def.concurrent_calls:
            lines.append(f"        results = await asyncio.wait_for(")
            calls_str = ",\n                ".join(func_def.concurrent_calls)
            lines.append(f"            asyncio.gather({calls_str}),")
            lines.append(f"            timeout={timeout}")
            lines.append(f"        )")
        lines.append("        return results")
        lines.append("    except asyncio.TimeoutError:")
        lines.append(f'        logger.error(f"Operation timed out after {timeout}s")')
        lines.append("        raise")
        lines.append("    except Exception as e:")
        lines.append('        logger.error(f"Timeout pattern failed: {e}")')
        lines.append("        raise")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_queue_pattern(self, func_def: AsyncFunctionDef) -> str:
        """Generate asyncio.Queue producer-consumer pattern
        
        中文: 生成 asyncio.Queue 生产者-消费者模式
        
        Args:
            func_def: Function definition
        
        Returns:
            Function code with queue pattern
        """
        lines = []
        lines.append(self.generate_async_function_signature(func_def))
        lines.append(self.generate_docstring(func_def))
        
        lines.append("    queue = asyncio.Queue()")
        lines.append("    results = []")
        lines.append("")
        
        lines.append("    async def producer():")
        lines.append('        """Generate items for queue"""')
        for call in func_def.concurrent_calls:
            lines.append(f"        item = {call}")
            lines.append("        await queue.put(item)")
        lines.append("        await queue.put(None)  # Sentinel")
        lines.append("")
        
        lines.append("    async def consumer():")
        lines.append('        """Process items from queue"""')
        lines.append("        while True:")
        lines.append("            item = await queue.get()")
        lines.append("            if item is None:")
        lines.append("                break")
        lines.append("            results.append(item)")
        lines.append("            queue.task_done()")
        lines.append("")
        
        lines.append("    try:")
        lines.append("        await asyncio.gather(")
        lines.append("            producer(),")
        lines.append("            consumer(),")
        lines.append("        )")
        lines.append("        return results")
        lines.append("    except Exception as e:")
        lines.append('        logger.error(f"Queue pattern failed: {e}")')
        lines.append("        raise")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_async_context_manager(self, name: str, setup: str, teardown: str) -> str:
        """Generate async context manager (async with)
        
        中文: 生成异步上下文管理器 (async with)
        
        Args:
            name: Manager class name
            setup: Setup code
            teardown: Teardown code
        
        Returns:
            Context manager class
        """
        lines = []
        lines.append(f"class {name}:")
        lines.append('    """Async context manager"""')
        lines.append("")
        
        lines.append("    async def __aenter__(self):")
        lines.append(f"        {setup}")
        lines.append("        return self")
        lines.append("")
        
        lines.append("    async def __aexit__(self, exc_type, exc_val, exc_tb):")
        lines.append(f"        {teardown}")
        lines.append("        return False")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_async_session_init(self, session_def: AsyncSessionDef) -> str:
        """Generate AsyncSession initialization
        
        中文: 生成 AsyncSession 初始化
        
        Args:
            session_def: AsyncSession definition
        
        Returns:
            Initialization code
        """
        lines = []
        lines.append(f"# AsyncSession: {session_def.name}")
        lines.append(f"# {session_def.description_en}")
        lines.append(f"# {session_def.description_cn}")
        lines.append("")
        
        lines.append("from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession")
        lines.append("from sqlalchemy.orm import sessionmaker")
        lines.append("")
        
        lines.append(f'engine_{session_def.name} = create_async_engine(')
        lines.append(f'    "{session_def.engine_url}",')
        lines.append(f'    pool_size={session_def.pool_size},')
        lines.append(f'    max_overflow={session_def.max_overflow},')
        lines.append(f'    echo={session_def.echo},')
        lines.append(")")
        lines.append("")
        
        lines.append(f"async_session_{session_def.name} = sessionmaker(")
        lines.append(f"    engine_{session_def.name},")
        lines.append("    class_=AsyncSession,")
        lines.append("    expire_on_commit=False,")
        lines.append(")")
        lines.append("")
        
        lines.append(f"async def get_session_{session_def.name}() -> AsyncSession:")
        lines.append(f'    """Get AsyncSession instance"""')
        lines.append(f"    async with async_session_{session_def.name}() as session:")
        lines.append(f"        try:")
        lines.append(f"            yield session")
        lines.append(f"        finally:")
        lines.append(f"            await session.close()")
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_error_handling_pattern(self, func_def: AsyncFunctionDef) -> str:
        """Generate comprehensive try/except/finally async error handling
        
        中文: 生成综合的异步错误处理
        
        Args:
            func_def: Function definition with error handlers
        
        Returns:
            Function code with error handling
        """
        lines = []
        lines.append(self.generate_async_function_signature(func_def))
        lines.append(self.generate_docstring(func_def))
        
        lines.append("    try:")
        if func_def.concurrent_calls:
            calls_str = ",\n            ".join(func_def.concurrent_calls)
            lines.append(f"        results = await asyncio.gather(")
            lines.append(f"            {calls_str},")
            lines.append(f"            return_exceptions=False")
            lines.append(f"        )")
        lines.append("        return results")
        
        # Exception handlers
        for exc_type, handler in func_def.error_handlers.items():
            lines.append(f"    except {exc_type} as e:")
            lines.append(f'        logger.error(f"Error: {{e}}")')
            lines.append(f"        await {handler}(e)")
        
        # Generic exception handler
        lines.append("    except Exception as e:")
        lines.append('        logger.error(f"Unexpected error: {e}")')
        lines.append("        raise")
        
        # Finally block
        lines.append("    finally:")
        lines.append('        logger.debug("Cleanup")')
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_imports(self) -> str:
        """Generate required imports for async patterns
        
        中文: 生成异步模式所需的导入
        
        Returns:
            Import statements
        """
        return (
            "import asyncio\n"
            "import logging\n"
            "from typing import Optional, List, Dict, Any, AsyncGenerator\n"
            "from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession\n"
            "from sqlalchemy.orm import sessionmaker\n"
            "\n"
            "logger = logging.getLogger(__name__)\n"
        )
    
    def generate_complete_async_module(
        self,
        module_name: str,
        functions: List[AsyncFunctionDef],
        sessions: List[AsyncSessionDef] = None,
    ) -> str:
        """Generate complete async module
        
        中文: 生成完整的异步模块
        
        Args:
            module_name: Module name
            functions: List of async functions
            sessions: List of async sessions
        
        Returns:
            Complete module code
        """
        lines = []
        
        # Header
        lines.append(f'"""{module_name}')
        lines.append('Auto-generated async patterns')
        lines.append('"""')
        lines.append("")
        
        # Imports
        lines.append(self.generate_imports())
        lines.append("")
        
        # Sessions
        if sessions:
            for session in sessions:
                lines.append(self.generate_async_session_init(session))
        
        # Functions
        for func in functions:
            if func.concurrent_calls:
                lines.append(self.generate_gather_pattern(func))
            else:
                lines.append(self.generate_async_function_signature(func))
                lines.append(self.generate_docstring(func))
                lines.append("    pass")
                lines.append("")
        
        return "\n".join(lines)
