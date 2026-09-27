"""
Unit tests for AgentControl Integrations
Tests LangGraph middleware, OpenAI adapter, Kubernetes gateway, GitHub gateway, and MCP client.
"""

import pytest
from integrations.langgraph import AgentControlToolNode
from integrations.openai import OpenAIControlledTool
from integrations.kubernetes import KubernetesGateway
from integrations.github import GitHubGateway
from integrations.mcp.gateway import MCPGateway
from packages.sdk.client import AgentControl, ToolExecutionResponse
from packages.tool_runtime.runtime import ToolRuntimeEngine


@pytest.mark.asyncio
async def test_kubernetes_gateway_operations():
    k8s = KubernetesGateway()
    pods = await k8s.list_pods("production")
    assert len(pods) >= 2
    assert any(p["name"] == "auth-service-789" for p in pods)

    restart_res = await k8s.restart_pod("production", "auth-service-789")
    assert restart_res["status"] == "restarted"
    assert restart_res["healthy"] is True

    rollback_res = await k8s.rollback_deployment("production", "auth-service")
    assert rollback_res["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_github_gateway_operations():
    gh = GitHubGateway()
    commits = await gh.get_recent_commits("org/api-service")
    assert len(commits) == 2

    pr = await gh.create_pull_request(
        repository="org/api-service",
        title="fix(auth): resolve pod restart loop",
        head="fix/pod-crash",
        base="main"
    )
    assert pr["pr_number"] > 0
    assert "https://github.com/org/api-service/pull/" in pr["url"]


@pytest.mark.asyncio
async def test_openai_controlled_tool_schema_and_call(monkeypatch):
    control = AgentControl()

    # Mock execute_tool on agent
    async def mock_execute_tool(tool_name: str, arguments: dict, **kwargs):
        return ToolExecutionResponse(
            call_id="call-123",
            status="approved_and_executed",
            risk_score=0.1,
            risk_level="low",
            reason_codes=["low_inherent_tool_risk"],
            execution_result={"rows": 5},
            trace_id="trace-abc"
        )

    agent = control.agent("test-agent")
    monkeypatch.setattr(agent, "execute_tool", mock_execute_tool)

    tool = OpenAIControlledTool(
        control=control,
        name="database.read_query",
        description="Run read query",
        parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        agent_id="test-agent"
    )
    tool.agent = agent

    schema = tool.to_openai_tool()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "database.read_query"

    res = await tool.execute_from_openai_call('{"query": "SELECT 1"}')
    assert res["status"] == "approved_and_executed"
    assert res["result"]["rows"] == 5


@pytest.mark.asyncio
async def test_langgraph_tool_node_intercept(monkeypatch):
    control = AgentControl()

    async def mock_execute_tool(tool_name: str, arguments: dict, **kwargs):
        return ToolExecutionResponse(
            call_id="call-456",
            status="approved_and_executed",
            risk_score=0.15,
            risk_level="low",
            reason_codes=["read_query"],
            execution_result={"status": "ok"},
            trace_id="trace-xyz"
        )

    node = AgentControlToolNode(control=control, agent_id="langgraph-agent")
    monkeypatch.setattr(node.agent, "execute_tool", mock_execute_tool)

    class DummyMessage:
        def __init__(self):
            self.tool_calls = [{"id": "tc-1", "name": "database.read_query", "args": {"query": "SELECT 1"}}]

    state = {"messages": [DummyMessage()]}
    new_state = await node(state)
    assert "agentcontrol_results" in new_state
    assert len(new_state["agentcontrol_results"]) == 1
    assert new_state["agentcontrol_results"][0]["status"] == "approved_and_executed"
