"""
Unit tests for Tool Runtime Engine
Tests execution, timeouts, idempotency keys, and automatic rollback hooks.
"""

import asyncio

import pytest

from packages.tool_runtime.runtime import (
    ExecutionStatus,
    ToolDefinition,
    ToolExecutionRequest,
    ToolRuntimeEngine,
)


@pytest.mark.asyncio
async def test_tool_successful_execution():
    engine = ToolRuntimeEngine()
    engine.register_tool(
        ToolDefinition(name="math.add", description="Add numbers", risk_level="low"),
        handler=lambda a, b: a + b
    )

    req = ToolExecutionRequest(
        execution_id="exec-1",
        agent_id="test-agent",
        environment="production",
        tool_name="math.add",
        arguments={"a": 10, "b": 25}
    )
    res = await engine.execute(req)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output == 35


@pytest.mark.asyncio
async def test_tool_idempotency_cache():
    engine = ToolRuntimeEngine()
    call_count = 0

    def non_idempotent_fn(val):
        nonlocal call_count
        call_count += 1
        return {"val": val, "call_count": call_count}

    engine.register_tool(
        ToolDefinition(name="billing.charge", description="Charge account"),
        handler=non_idempotent_fn
    )

    req1 = ToolExecutionRequest(
        execution_id="exec-1",
        idempotency_key="idemp-key-999",
        agent_id="test-agent",
        environment="production",
        tool_name="billing.charge",
        arguments={"val": 50}
    )
    res1 = await engine.execute(req1)
    assert res1.output["call_count"] == 1

    # Second execution with same idempotency key must NOT invoke handler again
    req2 = ToolExecutionRequest(
        execution_id="exec-2",
        idempotency_key="idemp-key-999",
        agent_id="test-agent",
        environment="production",
        tool_name="billing.charge",
        arguments={"val": 50}
    )
    res2 = await engine.execute(req2)
    assert res2.output["call_count"] == 1
    assert call_count == 1  # Underlying function called only once!


@pytest.mark.asyncio
async def test_tool_timeout():
    engine = ToolRuntimeEngine()

    async def slow_fn():
        await asyncio.sleep(1.0)
        return "done"

    engine.register_tool(
        ToolDefinition(name="slow.process", description="Slow job", timeout_seconds=0.1, max_retries=0),
        handler=slow_fn
    )

    req = ToolExecutionRequest(
        execution_id="exec-timeout",
        agent_id="test-agent",
        environment="production",
        tool_name="slow.process",
        timeout_seconds=0.1
    )
    res = await engine.execute(req)
    assert res.status == ExecutionStatus.TIMED_OUT
    assert "timed out" in res.error.lower()


@pytest.mark.asyncio
async def test_tool_rollback_on_failure():
    engine = ToolRuntimeEngine()
    rollback_called = False

    def failing_action(target):
        raise RuntimeError("Disk write failed midway")

    def rollback_action(target):
        nonlocal rollback_called
        rollback_called = True

    engine.register_tool(
        ToolDefinition(name="fs.create_file", description="Create file", max_retries=0),
        handler=failing_action,
        rollback_handler=rollback_action
    )

    req = ToolExecutionRequest(
        execution_id="exec-fail",
        agent_id="test-agent",
        environment="production",
        tool_name="fs.create_file",
        arguments={"target": "config.json"},
        rollback_on_failure=True
    )
    res = await engine.execute(req)
    assert res.status == ExecutionStatus.ROLLED_BACK
    assert res.rollback_performed
    assert rollback_called
