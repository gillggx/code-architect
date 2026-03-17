"""
LLM Model Routing for Code Architect Agent - Phase 3

Intelligent query classification and model selection for cost optimization.
Targets 49% cost reduction through smart routing to local models.

Version: 3.0
Status: PRODUCTION
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Literal, List, Optional, Tuple, Any
from enum import Enum

logger = logging.getLogger(__name__)


class QueryComplexity(str, Enum):
    """Query complexity classification"""
    SIMPLE = "simple"          # Single clause, fast answer
    MODERATE = "moderate"      # Multi-clause, explanation
    COMPLEX = "complex"        # Design, trade-offs


@dataclass
class ModelConfig:
    """Configuration for an LLM model"""
    name: str
    provider: str  # 'ollama', 'openai', 'together.ai', etc
    context_window: int
    max_tokens: int = 4096
    latency_target_ms: int = 3000
    cost_per_1k_tokens: float = 0.0
    deployment: Literal['local', 'cloud'] = 'local'
    timeout_sec: float = 30.0
    
    def is_available(self) -> bool:
        """Check if model is available"""
        # In production: check actual availability
        return True


@dataclass
class ModelRoutingDecision:
    """Decision for model routing"""
    primary_model: str
    fallback_models: List[str]
    confidence: float
    reason: str
    estimated_cost: float
    estimated_latency_ms: int


@dataclass
class RoutingMetrics:
    """Track routing metrics"""
    total_queries: int = 0
    queries_by_complexity: Dict[str, int] = field(default_factory=lambda: {
        'simple': 0,
        'moderate': 0,
        'complex': 0
    })
    models_used: Dict[str, int] = field(default_factory=dict)
    total_cost: float = 0.0
    total_tokens: int = 0
    fallback_count: int = 0
    
    def record_query(
        self,
        complexity: str,
        model: str,
        tokens: int,
        cost: float
    ):
        """Record a query execution"""
        self.total_queries += 1
        self.queries_by_complexity[complexity] = self.queries_by_complexity.get(complexity, 0) + 1
        self.models_used[model] = self.models_used.get(model, 0) + 1
        self.total_tokens += tokens
        self.total_cost += cost
    
    def cost_per_query(self) -> float:
        """Average cost per query"""
        return self.total_cost / max(1, self.total_queries)
    
    def haiku_ratio(self) -> float:
        """Ratio of Haiku (fast/cheap) model usage"""
        haiku_queries = self.models_used.get('anthropic/claude-haiku-4-5', 0)
        return haiku_queries / max(1, self.total_queries)
    
    def summary(self) -> Dict:
        """Get summary statistics"""
        return {
            'total_queries': self.total_queries,
            'by_complexity': self.queries_by_complexity,
            'models_used': self.models_used,
            'total_cost': f"${self.total_cost:.2f}",
            'avg_cost_per_query': f"${self.cost_per_query():.4f}",
            'haiku_ratio': f"{self.haiku_ratio():.1%}",
            'fallback_count': self.fallback_count,
        }


class QueryClassifier:
    """
    Classify query complexity for model routing
    
    Categories:
    - SIMPLE: Single clause, direct answers
    - MODERATE: Multi-clause, explanations
    - COMPLEX: Design questions, trade-offs
    """
    
    # Keywords for classification
    SIMPLE_KEYWORDS = {
        'where', 'what', 'which', 'list', 'show', 'find',
        'is', 'exists', 'count', 'get'
    }
    
    COMPLEX_KEYWORDS = {
        'compare', 'versus', 'vs',
        'design', 'architect', 'build',
        'tradeoff', 'trade-off', 'pros', 'cons',
        'alternative', 'refactor', 'improve',
        'why', 'explain why', 'how would you'
    }
    
    def classify(self, query: str) -> Tuple[QueryComplexity, float]:
        """
        Classify query complexity
        
        Returns:
        - Complexity level
        - Confidence (0.0-1.0)
        """
        
        # Normalize
        q = query.lower().strip()
        
        # Feature extraction
        sentence_count = q.count('.') + q.count('?')
        clause_count = q.count(',') + q.count(';')
        word_count = len(q.split())
        
        # Keyword matching
        simple_score = sum(1 for kw in self.SIMPLE_KEYWORDS if kw in q)
        complex_score = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in q)
        
        # Decision tree
        if complex_score > 0:
            # Has complex keywords
            complexity = QueryComplexity.COMPLEX
            confidence = 0.85 + (complex_score * 0.05)
        
        elif sentence_count > 1 or clause_count > 1:
            # Multi-clause/sentence
            complexity = QueryComplexity.MODERATE
            confidence = 0.80 + (clause_count * 0.05)
        
        elif word_count > 15:
            # Longer queries tend to be moderate
            complexity = QueryComplexity.MODERATE
            confidence = 0.70
        
        else:
            # Short, simple queries
            complexity = QueryComplexity.SIMPLE
            confidence = 0.85 + (simple_score * 0.05)
        
        # Cap confidence
        confidence = min(1.0, confidence)
        
        logger.debug(f"Classified query (complexity={complexity.value}, confidence={confidence:.2f}): {q[:50]}")
        
        return complexity, confidence
    
    def explain_classification(self, query: str) -> Dict[str, Any]:
        """Explain why query was classified"""
        
        complexity, confidence = self.classify(query)
        
        q = query.lower()
        
        return {
            'complexity': complexity.value,
            'confidence': confidence,
            'features': {
                'sentence_count': q.count('.') + q.count('?'),
                'clause_count': q.count(','),
                'word_count': len(q.split()),
                'has_complex_keywords': any(kw in q for kw in self.COMPLEX_KEYWORDS),
                'has_simple_keywords': any(kw in q for kw in self.SIMPLE_KEYWORDS),
            }
        }


class ModelRouter:
    """
    Route queries to optimal LLM models based on complexity
    
    Strategy:
    - SIMPLE → lightweight (qwen:7b-local) - $0
    - MODERATE → moderate (qwen:32b-local) - $0
    - COMPLEX → moderate (qwen:32b) with fallback to heavy
    
    Cost target: 90% local models, 10% cloud
    Estimated savings: 49% vs all-cloud
    """
    
    # Model registry — all via OpenRouter
    MODELS: Dict[str, ModelConfig] = {
        'anthropic/claude-sonnet-4-5': ModelConfig(
            name='anthropic/claude-sonnet-4-5',
            provider='openrouter',
            context_window=200000,
            latency_target_ms=2000,
            cost_per_1k_tokens=0.003,
            deployment='cloud',
            max_tokens=4096
        ),
        'anthropic/claude-opus-4-5': ModelConfig(
            name='anthropic/claude-opus-4-5',
            provider='openrouter',
            context_window=200000,
            latency_target_ms=4000,
            cost_per_1k_tokens=0.015,
            deployment='cloud',
            max_tokens=4096
        ),
        'anthropic/claude-haiku-4-5': ModelConfig(
            name='anthropic/claude-haiku-4-5',
            provider='openrouter',
            context_window=200000,
            latency_target_ms=1000,
            cost_per_1k_tokens=0.00025,
            deployment='cloud',
            max_tokens=4096
        ),
        'openai/gpt-4o': ModelConfig(
            name='openai/gpt-4o',
            provider='openrouter',
            context_window=128000,
            latency_target_ms=3000,
            cost_per_1k_tokens=0.005,
            deployment='cloud',
            max_tokens=4096
        ),
    }

    # Routing rules by complexity — all use Claude Sonnet as default
    # Can be overridden via DEFAULT_LLM_MODEL env var in LLMClient
    ROUTING_RULES = {
        'simple': {
            'primary': 'anthropic/claude-haiku-4-5',
            'fallbacks': ['anthropic/claude-sonnet-4-5'],
        },
        'moderate': {
            'primary': 'anthropic/claude-sonnet-4-5',
            'fallbacks': ['anthropic/claude-haiku-4-5', 'openai/gpt-4o'],
        },
        'complex': {
            'primary': 'anthropic/claude-opus-4-5',
            'fallbacks': ['anthropic/claude-sonnet-4-5', 'openai/gpt-4o'],
        },
    }
    
    def __init__(self):
        self.classifier = QueryClassifier()
        self.metrics = RoutingMetrics()
        self._available_models = set(self.MODELS.keys())
        logger.info(f"ModelRouter initialized with {len(self.MODELS)} models")
    
    def route(self, query: str) -> ModelRoutingDecision:
        """
        Route query to optimal model
        
        Returns routing decision with primary + fallback models
        """
        
        # Step 1: Classify
        complexity, classification_confidence = self.classifier.classify(query)
        
        # Step 2: Get routing rules
        rules = self.ROUTING_RULES.get(complexity.value)
        if not rules:
            # Default to moderate
            rules = self.ROUTING_RULES['moderate']
        
        # Step 3: Select primary model
        primary = rules['primary']
        if primary not in self._available_models:
            # Fallback if primary unavailable
            primary = [m for m in rules['fallbacks'] if m in self._available_models][0]
        
        # Step 4: Prepare fallbacks
        fallbacks = [
            m for m in rules['fallbacks']
            if m in self._available_models and m != primary
        ]
        
        # Get model configs
        primary_config = self.MODELS[primary]
        fallback_configs = [self.MODELS[m] for m in fallbacks]
        
        # Calculate metrics
        reason = f"Query classified as {complexity.value} (confidence: {classification_confidence:.2%})"
        estimated_cost = self._estimate_cost(primary, len(query))
        estimated_latency = primary_config.latency_target_ms
        
        decision = ModelRoutingDecision(
            primary_model=primary,
            fallback_models=fallbacks,
            confidence=classification_confidence,
            reason=reason,
            estimated_cost=estimated_cost,
            estimated_latency_ms=estimated_latency
        )
        
        logger.info(
            f"Routed query to {primary} (fallbacks: {fallbacks})\n"
            f"  Complexity: {complexity.value}\n"
            f"  Cost: ${estimated_cost:.4f}\n"
            f"  Reason: {reason}"
        )
        
        return decision
    
    def record_execution(
        self,
        query: str,
        model: str,
        tokens_used: int,
        success: bool = True
    ):
        """Record query execution for metrics"""
        
        complexity, _ = self.classifier.classify(query)
        
        # Calculate cost
        cost = 0.0
        if model in self.MODELS:
            config = self.MODELS[model]
            cost = (tokens_used / 1000) * config.cost_per_1k_tokens
        
        # Record metrics
        self.metrics.record_query(
            complexity=complexity.value,
            model=model,
            tokens=tokens_used,
            cost=cost
        )
    
    def record_fallback(self):
        """Record that fallback was used"""
        self.metrics.fallback_count += 1
    
    def get_metrics(self) -> Dict:
        """Get routing metrics"""
        return self.metrics.summary()
    
    def estimate_cost(
        self,
        query: str,
        estimated_response_tokens: int = 400
    ) -> float:
        """Estimate cost for a query"""
        
        decision = self.route(query)
        primary_config = self.MODELS[decision.primary_model]
        
        # Query tokens + response tokens
        query_tokens = len(query.split())  # Rough estimate
        total_tokens = query_tokens + estimated_response_tokens
        
        return (total_tokens / 1000) * primary_config.cost_per_1k_tokens
    
    def _estimate_cost(self, model: str, query_length: int) -> float:
        """Quick cost estimate"""
        
        if model not in self.MODELS:
            return 0.0
        
        config = self.MODELS[model]
        query_tokens = max(50, query_length // 4)  # Rough estimate
        response_tokens = 400  # Average response
        total_tokens = query_tokens + response_tokens
        
        return (total_tokens / 1000) * config.cost_per_1k_tokens
    
    def explain_routing(self, query: str) -> Dict[str, Any]:
        """Explain routing decision"""
        
        decision = self.route(query)
        classification = self.classifier.explain_classification(query)
        
        return {
            'query': query[:100],
            'classification': classification,
            'routing': {
                'primary_model': decision.primary_model,
                'fallback_models': decision.fallback_models,
                'reason': decision.reason,
                'estimated_cost': f"${decision.estimated_cost:.4f}",
                'estimated_latency_ms': decision.estimated_latency_ms,
            },
            'model_configs': {
                decision.primary_model: {
                    'context_window': self.MODELS[decision.primary_model].context_window,
                    'deployment': self.MODELS[decision.primary_model].deployment,
                    'cost_per_1k': self.MODELS[decision.primary_model].cost_per_1k_tokens,
                }
            }
        }


class IntelligentDegradation:
    """
    Handle model degradation when primary model fails
    
    Strategies:
    1. Timeout → try fallback with lower timeout
    2. Rate limit → use cheaper model
    3. API error → use local model
    4. Complete failure → return cached/memory results
    """
    
    def __init__(self, router: ModelRouter):
        self.router = router
    
    def get_fallback_model(
        self,
        original_model: str,
        reason: Literal['timeout', 'rate_limit', 'error']
    ) -> Optional[str]:
        """
        Get fallback model based on failure reason
        
        Returns: model name or None
        """
        
        if original_model not in self.router.MODELS:
            return None
        
        if reason == 'timeout':
            fallbacks = ['anthropic/claude-haiku-4-5', 'anthropic/claude-sonnet-4-5']
        elif reason == 'rate_limit':
            fallbacks = ['anthropic/claude-haiku-4-5']
        else:  # error
            fallbacks = ['anthropic/claude-sonnet-4-5', 'anthropic/claude-haiku-4-5']
        
        # Return first available
        for model in fallbacks:
            if model in self.router._available_models and model != original_model:
                logger.info(f"Degradation ({reason}): {original_model} → {model}")
                self.router.record_fallback()
                return model
        
        return None
    
    def get_timeout_for_model(self, model: str) -> float:
        """Get appropriate timeout for model"""
        
        if model not in self.router.MODELS:
            return 30.0
        
        config = self.router.MODELS[model]
        
        # Add buffer to latency target
        return (config.latency_target_ms / 1000) * 2


def create_model_router() -> ModelRouter:
    """Create and initialize model router"""
    return ModelRouter()


def create_intelligent_degradation(router: ModelRouter) -> IntelligentDegradation:
    """Create degradation handler"""
    return IntelligentDegradation(router)
