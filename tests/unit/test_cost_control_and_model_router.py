"""
Unit tests for Cost Control & Model Router
Tests pricing calculation, budget limit enforcement, provider selection, and fallback routing.
"""

import pytest

from packages.cost_control import (
    CostBudgetExceededError,
    CostController,
    CostLimitPolicy,
)
from packages.model_router import (
    ModelGenerateRequest,
    ModelRouter,
    TaskComplexity,
)


def test_cost_calculation():
    controller = CostController()
    # gpt-4o: prompt 0.005/1k, completion 0.015/1k
    # 2000 prompt tokens = 0.010, 1000 completion = 0.015 => total = 0.025
    cost = controller.calculate_cost("gpt-4o", prompt_tokens=2000, completion_tokens=1000)
    assert cost == 0.025


def test_per_request_cost_limit_enforced():
    controller = CostController()
    controller.set_policy("production", CostLimitPolicy(per_request_limit_usd=0.05))

    # Request costing ~0.025 should pass
    rec = controller.check_and_record(
        agent_id="agent-1",
        environment="production",
        model_name="gpt-4o",
        prompt_tokens=2000,
        completion_tokens=1000
    )
    assert rec.estimated_cost_usd == 0.025

    # Request costing ~0.100 should be blocked
    with pytest.raises(CostBudgetExceededError) as exc_info:
        controller.check_and_record(
            agent_id="agent-1",
            environment="production",
            model_name="gpt-4o",
            prompt_tokens=10000,
            completion_tokens=5000
        )
    assert exc_info.value.limit_type == "per_request"


def test_agent_daily_budget_limit():
    controller = CostController()
    controller.set_policy("finance-agent", CostLimitPolicy(agent_daily_limit_usd=0.03))

    # 1. First request costing 0.025 succeeds
    controller.check_and_record(
        agent_id="finance-agent",
        environment="production",
        model_name="gpt-4o",
        prompt_tokens=2000,
        completion_tokens=1000
    )

    # 2. Second request pushing cumulative spend over 0.03 fails
    with pytest.raises(CostBudgetExceededError) as exc_info:
        controller.check_and_record(
            agent_id="finance-agent",
            environment="production",
            model_name="gpt-4o",
            prompt_tokens=2000,
            completion_tokens=1000
        )
    assert exc_info.value.limit_type == "agent_daily"


@pytest.mark.asyncio
async def test_model_router_complexity_selection():
    router = ModelRouter()
    low_spec = router.select_model(complexity=TaskComplexity.LOW)
    assert low_spec.cost_tier == "low"

    high_spec = router.select_model(complexity=TaskComplexity.HIGH)
    assert high_spec.cost_tier in ("medium", "high")


@pytest.mark.asyncio
async def test_model_router_automatic_fallback():
    router = ModelRouter()

    # Primary model throws exception
    async def failing_handler(model_name: str, req: ModelGenerateRequest):
        raise ConnectionError("Primary provider connection timeout")

    # Fallback model succeeds
    async def fallback_handler(model_name: str, req: ModelGenerateRequest):
        return {
            "content": f"Resilient response from fallback {model_name}",
            "prompt_tokens": 15,
            "completion_tokens": 25
        }

    router.register_provider_handler("gemini", failing_handler)
    router.register_provider_handler("openai", fallback_handler)

    req = ModelGenerateRequest(task="classification", complexity=TaskComplexity.LOW, prompt="Check this alert")
    resp = await router.generate(req, primary_model_id="fast-classifier")

    assert resp.fallback_used is True
    assert "Resilient response from fallback" in resp.content
    assert len(resp.attempted_models) >= 2
