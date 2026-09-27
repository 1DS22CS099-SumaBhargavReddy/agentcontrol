"""
AgentControl Cost Control Engine
Tracks token usage, computes estimated costs, and enforces budget policies per request, agent, and environment.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    provider: str
    model_name: str
    prompt_cost_per_1k: float
    completion_cost_per_1k: float


class UsageRecord(BaseModel):
    agent_id: str
    environment: str
    model_name: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CostLimitPolicy(BaseModel):
    per_request_limit_usd: float | None = None
    agent_daily_limit_usd: float | None = None
    environment_monthly_limit_usd: float | None = None


class CostBudgetExceededError(Exception):
    def __init__(self, message: str, limit_type: str, current_spend: float, limit: float):
        super().__init__(message)
        self.limit_type = limit_type
        self.current_spend = current_spend
        self.limit = limit


# Standard enterprise pricing lookup ($ per 1k tokens)
DEFAULT_PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(provider="openai", model_name="gpt-4o", prompt_cost_per_1k=0.005, completion_cost_per_1k=0.015),
    "gpt-4o-mini": ModelPricing(provider="openai", model_name="gpt-4o-mini", prompt_cost_per_1k=0.00015, completion_cost_per_1k=0.0006),
    "claude-3-5-sonnet": ModelPricing(provider="anthropic", model_name="claude-3-5-sonnet", prompt_cost_per_1k=0.003, completion_cost_per_1k=0.015),
    "claude-3-haiku": ModelPricing(provider="anthropic", model_name="claude-3-haiku", prompt_cost_per_1k=0.00025, completion_cost_per_1k=0.00125),
    "gemini-1.5-pro": ModelPricing(provider="gemini", model_name="gemini-1.5-pro", prompt_cost_per_1k=0.00125, completion_cost_per_1k=0.005),
    "gemini-1.5-flash": ModelPricing(provider="gemini", model_name="gemini-1.5-flash", prompt_cost_per_1k=0.000075, completion_cost_per_1k=0.0003),
    "ollama/llama3": ModelPricing(provider="ollama", model_name="llama3", prompt_cost_per_1k=0.0, completion_cost_per_1k=0.0),
    "mock-model": ModelPricing(provider="mock", model_name="mock-model", prompt_cost_per_1k=0.001, completion_cost_per_1k=0.002),
}


class CostController:
    """
    Manages real-time cost tracking, token budgeting, and limit enforcement.
    """

    def __init__(self, pricing_table: dict[str, ModelPricing] | None = None):
        self.pricing_table = pricing_table or DEFAULT_PRICING.copy()
        self._usage_history: list[UsageRecord] = []
        self._policies: dict[str, CostLimitPolicy] = {}  # scope -> policy

    def set_policy(self, scope: str, policy: CostLimitPolicy) -> None:
        """Sets a cost policy for an agent_id or environment (e.g., 'production', 'agent-123')."""
        self._policies[scope.lower()] = policy

    def get_policy(self, scope: str) -> CostLimitPolicy | None:
        return self._policies.get(scope.lower())

    def calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculates estimated dollar cost for a token consumption record."""
        pricing = self.pricing_table.get(model_name.lower())
        if not pricing:
            # Fallback to default average rate
            pricing = ModelPricing(provider="custom", model_name=model_name, prompt_cost_per_1k=0.002, completion_cost_per_1k=0.005)

        cost = (prompt_tokens / 1000.0 * pricing.prompt_cost_per_1k) + (completion_tokens / 1000.0 * pricing.completion_cost_per_1k)
        return round(cost, 6)

    def check_and_record(
        self,
        agent_id: str,
        environment: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int
    ) -> UsageRecord:
        """
        Validates the proposed usage against active budget policies, then records it.
        Raises CostBudgetExceededError if any limit is breached.
        """
        total_tokens = prompt_tokens + completion_tokens
        cost = self.calculate_cost(model_name, prompt_tokens, completion_tokens)

        # 1. Check per-request limits (agent policy, environment policy)
        agent_policy = self.get_policy(agent_id)
        env_policy = self.get_policy(environment)

        for p in (agent_policy, env_policy):
            if p and p.per_request_limit_usd is not None:
                if cost > p.per_request_limit_usd:
                    raise CostBudgetExceededError(
                        f"Request cost ${cost:.4f} exceeds per-request limit of ${p.per_request_limit_usd:.4f}",
                        limit_type="per_request",
                        current_spend=cost,
                        limit=p.per_request_limit_usd
                    )

        # 2. Check agent daily spend
        if agent_policy and agent_policy.agent_daily_limit_usd is not None:
            today_spend = self.get_agent_daily_spend(agent_id)
            if (today_spend + cost) > agent_policy.agent_daily_limit_usd:
                raise CostBudgetExceededError(
                    f"Agent {agent_id} daily spend (${today_spend + cost:.4f}) exceeds limit of ${agent_policy.agent_daily_limit_usd:.4f}",
                    limit_type="agent_daily",
                    current_spend=today_spend + cost,
                    limit=agent_policy.agent_daily_limit_usd
                )

        # 3. Check environment monthly spend
        if env_policy and env_policy.environment_monthly_limit_usd is not None:
            env_spend = self.get_environment_spend(environment)
            if (env_spend + cost) > env_policy.environment_monthly_limit_usd:
                raise CostBudgetExceededError(
                    f"Environment {environment} monthly spend (${env_spend + cost:.4f}) exceeds limit of ${env_policy.environment_monthly_limit_usd:.4f}",
                    limit_type="environment_monthly",
                    current_spend=env_spend + cost,
                    limit=env_policy.environment_monthly_limit_usd
                )

        pricing = self.pricing_table.get(model_name.lower())
        provider = pricing.provider if pricing else "unknown"

        record = UsageRecord(
            agent_id=agent_id,
            environment=environment.lower(),
            model_name=model_name,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost
        )
        self._usage_history.append(record)
        return record

    def get_agent_daily_spend(self, agent_id: str) -> float:
        now = datetime.now(timezone.utc)
        return sum(
            r.estimated_cost_usd
            for r in self._usage_history
            if r.agent_id == agent_id and r.timestamp.date() == now.date()
        )

    def get_environment_spend(self, environment: str) -> float:
        env_lower = environment.lower()
        return sum(
            r.estimated_cost_usd
            for r in self._usage_history
            if r.environment == env_lower
        )

    def get_total_spend(self) -> float:
        return sum(r.estimated_cost_usd for r in self._usage_history)

    def get_metrics_summary(self) -> dict[str, Any]:
        return {
            "total_requests": len(self._usage_history),
            "total_tokens": sum(r.total_tokens for r in self._usage_history),
            "total_spend_usd": round(self.get_total_spend(), 4),
            "records_count": len(self._usage_history)
        }
