"""
AgentControl Model Router
Provider-agnostic LLM router with multi-provider abstraction, capability/cost/latency routing,
and resilient fallback chains.
"""

import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class TaskComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelSpec(BaseModel):
    id: str
    provider: ModelProvider
    model_name: str
    cost_tier: str  # low, medium, high
    latency_tier: str  # fast, moderate, slow
    max_context_tokens: int = 128000
    supports_tools: bool = True
    is_available: bool = True


class ModelGenerateRequest(BaseModel):
    task: str
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    prompt: str
    system_prompt: str | None = None
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout_seconds: float = 15.0


class ModelGenerateResponse(BaseModel):
    content: str
    model_used: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    fallback_used: bool = False
    attempted_models: list[str] = Field(default_factory=list)


# Standard catalog of registered models
DEFAULT_MODEL_SPECS: list[ModelSpec] = [
    ModelSpec(id="fast-classifier", provider=ModelProvider.GEMINI, model_name="gemini-1.5-flash", cost_tier="low", latency_tier="fast"),
    ModelSpec(id="cheap-analyzer", provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", cost_tier="low", latency_tier="fast"),
    ModelSpec(id="local-offline", provider=ModelProvider.OLLAMA, model_name="ollama/llama3", cost_tier="low", latency_tier="fast"),
    ModelSpec(id="balanced-reasoner", provider=ModelProvider.ANTHROPIC, model_name="claude-3-5-sonnet", cost_tier="medium", latency_tier="moderate"),
    ModelSpec(id="deep-reasoner", provider=ModelProvider.OPENAI, model_name="gpt-4o", cost_tier="high", latency_tier="moderate"),
]


class ModelRouter:
    """
    Intelligent Model Router that dynamically routes requests to the optimal LLM provider
    based on task complexity, cost policies, and provides automatic failover.
    """

    def __init__(self, specs: list[ModelSpec] | None = None):
        self.specs: dict[str, ModelSpec] = {s.id: s for s in (specs or DEFAULT_MODEL_SPECS)}
        self._provider_handlers: dict[str, Callable[..., Any]] = {}

    def register_provider_handler(self, provider: str, handler: Callable[..., Any]) -> None:
        """Registers an execution handler for a provider (e.g. mock, openai client, ollama)."""
        self._provider_handlers[provider.lower()] = handler

    def select_model(
        self,
        complexity: TaskComplexity = TaskComplexity.MEDIUM,
        prefer_low_cost: bool = False
    ) -> ModelSpec:
        """Selects the best suited available model based on complexity and cost profile."""
        available = [s for s in self.specs.values() if s.is_available]
        if not available:
            # Fallback to any defined spec
            return list(self.specs.values())[0]

        if complexity == TaskComplexity.HIGH:
            # Prefer deep reasoning
            high_cap = [s for s in available if s.cost_tier in ("medium", "high")]
            if high_cap:
                return high_cap[-1]

        if complexity == TaskComplexity.LOW or prefer_low_cost:
            # Prefer low cost, fast latency
            low_cost = [s for s in available if s.cost_tier == "low"]
            if low_cost:
                return low_cost[0]

        # Default moderate
        return available[0]

    def get_fallback_chain(self, primary_model: ModelSpec) -> list[ModelSpec]:
        """Calculates prioritized fallback models in case primary provider fails."""
        chain = [primary_model]
        # Alternate provider with similar capabilities
        for s in self.specs.values():
            if s.id != primary_model.id and s.is_available and s.provider != primary_model.provider:
                chain.append(s)
        return chain

    async def generate(
        self,
        request: ModelGenerateRequest,
        primary_model_id: str | None = None
    ) -> ModelGenerateResponse:
        """
        Executes generation through the router with automatic multi-model fallback.
        """
        if primary_model_id and primary_model_id in self.specs:
            primary = self.specs[primary_model_id]
        else:
            primary = self.select_model(complexity=request.complexity)

        fallback_chain = self.get_fallback_chain(primary)
        attempted: list[str] = []
        last_error = None

        for idx, model in enumerate(fallback_chain):
            attempted.append(model.model_name)
            handler = self._provider_handlers.get(model.provider.value)

            start_t = time.perf_counter()
            try:
                if handler:
                    result = await handler(model.model_name, request)
                else:
                    # Built-in deterministic simulated response for offline/testing
                    result = {
                        "content": f"Deterministic model response for task '{request.task}' using {model.model_name}.",
                        "prompt_tokens": len(request.prompt.split()) * 2,
                        "completion_tokens": 50
                    }

                latency = round((time.perf_counter() - start_t) * 1000.0, 2)
                return ModelGenerateResponse(
                    content=result["content"],
                    model_used=model.model_name,
                    provider=model.provider.value,
                    prompt_tokens=result.get("prompt_tokens", 50),
                    completion_tokens=result.get("completion_tokens", 30),
                    latency_ms=latency,
                    fallback_used=(idx > 0),
                    attempted_models=attempted
                )
            except Exception as e:
                last_error = e
                # Provider failed, continue down fallback chain
                continue

        # If all providers failed, raise safe failure
        raise RuntimeError(
            f"All model providers in fallback chain failed: {attempted}. Last error: {last_error}"
        )
