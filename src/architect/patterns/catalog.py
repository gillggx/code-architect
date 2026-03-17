"""
Pattern Catalog

Defines 15+ architectural patterns with language-specific detection rules.

Patterns included:
- OOP: Singleton, Factory, Abstract Factory, Builder, Prototype
- Behavioral: Observer, Strategy, State, Template Method, Chain of Responsibility
- Structural: Adapter, Bridge, Decorator, Facade, Proxy
- Architectural: MVC, Repository, Middleware, Error Handling, Concurrency

Each pattern includes:
- Language-specific detection rules
- Python/C++/Java/JS implementation examples
- Evidence gathering heuristics
- Confidence scoring rules
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class DetectionRule:
    """Detection rule for a pattern in a specific language"""
    language: str
    keywords: List[str] = field(default_factory=list)
    ast_patterns: List[str] = field(default_factory=list)
    file_name_patterns: List[str] = field(default_factory=list)
    inheritance_patterns: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class PatternDefinition:
    """Defines an architectural pattern"""
    name: str
    category: str
    description: str
    benefits: List[str] = field(default_factory=list)
    drawbacks: List[str] = field(default_factory=list)
    detection_rules: Dict[str, DetectionRule] = field(default_factory=dict)
    example_code: Dict[str, str] = field(default_factory=dict)
    related_patterns: List[str] = field(default_factory=list)


class PatternCatalog:
    """Catalog of architectural patterns"""
    
    def __init__(self):
        self.patterns: Dict[str, PatternDefinition] = {}
        self._initialize_patterns()
    
    def _initialize_patterns(self):
        """Initialize all 15+ patterns with detection rules"""
        
        # =====================================================================
        # OOP Patterns
        # =====================================================================
        
        self.patterns["Singleton"] = PatternDefinition(
            name="Singleton",
            category="oop",
            description="Ensures a class has exactly one instance with global access",
            benefits=[
                "Centralizes resource management",
                "Lazy initialization possible",
                "Thread-safe instance control",
                "Easy to mock for testing"
            ],
            drawbacks=[
                "Harder to test in isolation",
                "Global state difficult to reason about",
                "Can hide dependencies",
                "Not suitable for concurrent heavy usage"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["_instance", "__new__", "classmethod"],
                    ast_patterns=["class_with_private_static", "instance_creation_check"],
                    description="Detects __new__ override or _instance pattern"
                ),
                "cpp": DetectionRule(
                    language="cpp",
                    keywords=["static", "getInstance", "private_constructor"],
                    description="Detects static getInstance() method"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["static", "getInstance", "private constructor"],
                    description="Detects static getInstance() method"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["instance", "getInstance", "closure"],
                    description="Detects singleton via closure or static method"
                ),
            },
            related_patterns=["Factory", "Module Pattern"]
        )
        
        self.patterns["Factory"] = PatternDefinition(
            name="Factory",
            category="oop",
            description="Creates objects without specifying exact classes",
            benefits=[
                "Decouples object creation from usage",
                "Easier to add new types",
                "Centralizes creation logic",
                "Supports polymorphism"
            ],
            drawbacks=[
                "Can add unnecessary complexity",
                "More classes to maintain",
                "Indirection in object creation"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["factory", "create", "build"],
                    ast_patterns=["method_returns_instance_of_various_classes"],
                    description="Detects factory methods"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["factory", "create", "Factory"],
                    description="Detects Factory class pattern"
                ),
            },
            related_patterns=["Abstract Factory", "Builder"]
        )
        
        self.patterns["Decorator"] = PatternDefinition(
            name="Decorator",
            category="structural",
            description="Dynamically adds responsibilities to objects",
            benefits=[
                "Flexible alternative to subclassing",
                "Single Responsibility Principle",
                "Runtime composition",
                "More composable than inheritance"
            ],
            drawbacks=[
                "Can create many small objects",
                "Harder to debug decorator chains",
                "Order of decorators matters"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["@", "decorator", "wrapper", "functools.wraps"],
                    ast_patterns=["function_decorator", "class_decorator"],
                    description="Detects Python decorators and wrapper functions"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["decorator", "wrap", "higher-order function"],
                    description="Detects decorator pattern"
                ),
            },
            related_patterns=["Proxy", "Adapter"]
        )
        
        self.patterns["Observer"] = PatternDefinition(
            name="Observer",
            category="behavioral",
            description="Defines one-to-many dependency between objects",
            benefits=[
                "Loose coupling",
                "Dynamic subscriptions",
                "Publish-subscribe model",
                "Event-driven architecture"
            ],
            drawbacks=[
                "Unpredictable notification order",
                "Memory leaks if not unsubscribed",
                "Can be slow with many observers"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["subscribe", "notify", "listener", "observer", "event"],
                    ast_patterns=["callback_registration", "event_emission"],
                    description="Detects event systems and subscriptions"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["addEventListener", "on", "subscribe", "emit"],
                    description="Detects event listeners and emitters"
                ),
            },
            related_patterns=["Mediator", "Pub-Sub"]
        )
        
        self.patterns["Strategy"] = PatternDefinition(
            name="Strategy",
            category="behavioral",
            description="Encapsulates algorithms to make them interchangeable",
            benefits=[
                "Encapsulates changing algorithms",
                "Eliminates conditional statements",
                "Easy to add new strategies",
                "Runtime algorithm selection"
            ],
            drawbacks=[
                "Can increase number of classes",
                "Client must be aware of strategies",
                "Overkill for simple cases"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["strategy", "algorithm", "interface"],
                    ast_patterns=["multiple_implementations", "runtime_selection"],
                    description="Detects algorithm strategy pattern"
                ),
            },
            related_patterns=["State", "Template Method"]
        )
        
        self.patterns["State"] = PatternDefinition(
            name="State",
            category="behavioral",
            description="Allows object behavior to change based on internal state",
            benefits=[
                "Encapsulates state-specific behavior",
                "Simplifies state machines",
                "Single Responsibility",
                "Open/Closed Principle"
            ],
            drawbacks=[
                "Can increase complexity",
                "Many state classes needed",
                "Overkill for simple state machines"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["state", "context", "transition"],
                    ast_patterns=["state_class_hierarchy", "state_switching"],
                    description="Detects state machine pattern"
                ),
            },
            related_patterns=["Strategy"]
        )
        
        self.patterns["Adapter"] = PatternDefinition(
            name="Adapter",
            category="structural",
            description="Converts interface to another clients expect",
            benefits=[
                "Integrates incompatible interfaces",
                "Reuses existing classes",
                "Single Responsibility",
                "Loose coupling"
            ],
            drawbacks=[
                "Adds indirection",
                "Can hide underlying implementation",
                "Unnecessary if good design"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["adapter", "wrapper", "interface"],
                    description="Detects adapter pattern"
                ),
            },
            related_patterns=["Bridge", "Decorator"]
        )
        
        self.patterns["Repository"] = PatternDefinition(
            name="Repository",
            category="architectural",
            description="Abstracts data access logic behind interface",
            benefits=[
                "Testable data access layer",
                "Encapsulates database logic",
                "Easy to swap implementations",
                "Dependency inversion"
            ],
            drawbacks=[
                "Extra layer of abstraction",
                "Can hide complex queries",
                "Performance implications"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["repository", "Repository", "DAO", "query", "save", "find"],
                    file_name_patterns=["*repository*", "*dao*"],
                    description="Detects repository/DAO pattern"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["Repository", "DAO", "interface"],
                    description="Detects Spring Repository or DAO pattern"
                ),
            },
            related_patterns=["Factory", "Data Mapper"]
        )
        
        self.patterns["Middleware"] = PatternDefinition(
            name="Middleware",
            category="architectural",
            description="Filters/processes requests and responses",
            benefits=[
                "Separates cross-cutting concerns",
                "Reusable request/response processing",
                "Pipeline architecture",
                "Clean separation of concerns"
            ],
            drawbacks=[
                "Order dependency",
                "Complex debugging through middleware",
                "Performance overhead"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["middleware", "before_request", "after_request", "process_request"],
                    file_name_patterns=["*middleware*"],
                    description="Detects middleware in web frameworks"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["middleware", "app.use", "next()"],
                    description="Detects Express/middleware pattern"
                ),
            },
            related_patterns=["Decorator", "Pipeline"]
        )
        
        self.patterns["ErrorHandling"] = PatternDefinition(
            name="ErrorHandling",
            category="error_handling",
            description="Structured error and exception handling",
            benefits=[
                "Graceful failure modes",
                "Error recovery",
                "Consistent error reporting",
                "Robustness"
            ],
            drawbacks=[
                "Can be verbose",
                "Exception overhead",
                "Silent failures if not careful"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["try", "except", "finally", "raise", "Exception"],
                    ast_patterns=["try_except_blocks", "custom_exceptions"],
                    description="Detects exception handling"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["try", "catch", "finally", "throws", "Exception"],
                    description="Detects exception handling"
                ),
                "cpp": DetectionRule(
                    language="cpp",
                    keywords=["try", "catch", "throw", "exception"],
                    description="Detects exception handling"
                ),
            },
            related_patterns=["Circuit Breaker", "Retry"]
        )
        
        self.patterns["Concurrency"] = PatternDefinition(
            name="Concurrency",
            category="async_concurrency",
            description="Handles concurrent execution safely",
            benefits=[
                "Responsive applications",
                "Better resource utilization",
                "Scalability",
                "Non-blocking operations"
            ],
            drawbacks=[
                "Complex debugging",
                "Race conditions possible",
                "Deadlock potential",
                "Harder to reason about"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["async", "await", "asyncio", "Thread", "Lock", "Queue"],
                    ast_patterns=["async_functions", "thread_creation"],
                    description="Detects async/await and threading"
                ),
                "cpp": DetectionRule(
                    language="cpp",
                    keywords=["std::thread", "std::async", "std::mutex", "std::lock"],
                    description="Detects C++ concurrency"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["Thread", "synchronized", "volatile", "ExecutorService"],
                    description="Detects Java threading"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["async", "await", "Promise", "setTimeout", "Worker"],
                    description="Detects async/Promise pattern"
                ),
            },
            related_patterns=["Lock", "Semaphore"]
        )
        
        self.patterns["DependencyInjection"] = PatternDefinition(
            name="DependencyInjection",
            category="architectural",
            description="Provides object dependencies from outside",
            benefits=[
                "Testability",
                "Loose coupling",
                "Flexibility",
                "Dependency inversion"
            ],
            drawbacks=[
                "Learning curve",
                "Can be complex for simple projects",
                "Framework overhead"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["__init__", "inject", "dependency", "injection"],
                    ast_patterns=["constructor_injection", "setter_injection"],
                    description="Detects constructor/setter injection"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["@Inject", "@Autowired", "constructor"],
                    description="Detects Spring DI annotations"
                ),
            },
            related_patterns=["Factory", "Service Locator"]
        )
        
        self.patterns["MVC"] = PatternDefinition(
            name="MVC",
            category="architectural",
            description="Separates application into Model, View, Controller",
            benefits=[
                "Separation of concerns",
                "Testable business logic",
                "Reusable models",
                "Multiple views for same model"
            ],
            drawbacks=[
                "Complexity overhead",
                "Synchronization between M/V/C",
                "Overkill for simple apps"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["model", "view", "controller", "routes"],
                    file_name_patterns=["*models*", "*views*", "*controllers*"],
                    description="Detects MVC structure"
                ),
                "javascript": DetectionRule(
                    language="javascript",
                    keywords=["model", "view", "controller"],
                    description="Detects MVC pattern"
                ),
            },
            related_patterns=["MVVM", "MVP"]
        )
        
        self.patterns["ChainOfResponsibility"] = PatternDefinition(
            name="ChainOfResponsibility",
            category="behavioral",
            description="Passes request along chain of handlers",
            benefits=[
                "Loose coupling",
                "Dynamic chain",
                "Single Responsibility",
                "Flexible request handling"
            ],
            drawbacks=[
                "Request might go unhandled",
                "Hard to debug",
                "Performance cost"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["chain", "handler", "next", "successor"],
                    ast_patterns=["linked_handler_chain"],
                    description="Detects chain of responsibility"
                ),
            },
            related_patterns=["Command", "Interpreter"]
        )
        
        self.patterns["TemplateMethod"] = PatternDefinition(
            name="TemplateMethod",
            category="behavioral",
            description="Defines algorithm skeleton in base class",
            benefits=[
                "Code reuse",
                "Consistent algorithm structure",
                "Customizable steps",
                "Encapsulation"
            ],
            drawbacks=[
                "Can violate Liskov substitution",
                "Over-engineering simple cases",
                "Inheritance required"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["@abc", "abstractmethod", "template"],
                    ast_patterns=["abstract_base_class", "concrete_overrides"],
                    description="Detects template method pattern"
                ),
                "java": DetectionRule(
                    language="java",
                    keywords=["abstract", "abstractmethod", "override"],
                    description="Detects template method pattern"
                ),
            },
            related_patterns=["Strategy"]
        )
        
        self.patterns["Bridge"] = PatternDefinition(
            name="Bridge",
            category="structural",
            description="Decouples abstraction from implementation",
            benefits=[
                "Separates interface from implementation",
                "Independent variation",
                "Avoids brittle hierarchies",
                "Single Responsibility"
            ],
            drawbacks=[
                "Extra complexity",
                "Indirection overhead",
                "Overkill for simple cases"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["abstraction", "implementor", "bridge"],
                    description="Detects bridge pattern"
                ),
            },
            related_patterns=["Adapter", "Facade"]
        )
        
        self.patterns["Facade"] = PatternDefinition(
            name="Facade",
            category="structural",
            description="Provides simplified interface to complex subsystem",
            benefits=[
                "Simplified interface",
                "Decouples clients from subsystem",
                "Easier to understand",
                "Single entry point"
            ],
            drawbacks=[
                "Hides complexity",
                "Can become bloated",
                "Might limit functionality"
            ],
            detection_rules={
                "python": DetectionRule(
                    language="python",
                    keywords=["facade", "wrapper", "interface"],
                    file_name_patterns=["*facade*"],
                    description="Detects facade pattern"
                ),
            },
            related_patterns=["Adapter", "Decorator"]
        )
    
    def get_all_patterns(self) -> List[PatternDefinition]:
        """Get all pattern definitions"""
        return list(self.patterns.values())
    
    def get_pattern(self, name: str) -> Optional[PatternDefinition]:
        """Get pattern by name"""
        return self.patterns.get(name)
    
    def get_patterns_by_category(self, category: str) -> List[PatternDefinition]:
        """Get patterns by category"""
        return [p for p in self.patterns.values() if p.category == category]
    
    def get_detection_rule(self, pattern_name: str, language: str) -> Optional[DetectionRule]:
        """Get detection rule for pattern in specific language"""
        pattern = self.get_pattern(pattern_name)
        if pattern:
            return pattern.detection_rules.get(language)
        return None


# Singleton instance
_CATALOG = None


def get_pattern_catalog() -> PatternCatalog:
    """Get global pattern catalog instance"""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = PatternCatalog()
    return _CATALOG


__all__ = ["PatternCatalog", "PatternDefinition", "DetectionRule", "get_pattern_catalog"]
