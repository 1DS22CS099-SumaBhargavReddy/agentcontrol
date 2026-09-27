"""
AgentControl Python SDK
Developer-friendly client for integrating the zero-trust control plane into any AI agent.
"""

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel


class ToolExecutionResponse(BaseModel):
    call_id: str
    status: str
    risk_score: float
    risk_level: str
    reason_codes: list[str]
    approval_id: str | None = None
    execution_result: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0
    trace_id: str


class AgentClient:
    """Represents a scoped agent context connected to the AgentControl control plane."""

    def __init__(self, control: "AgentControl", name: str, environment: str = "production"):
        self.control = control
        self.name = name
        self.environment = environment

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str | None = None,
        wait_for_approval: bool = True,
        approval_poll_interval: float = 2.0,
        approval_timeout: float = 300.0
    ) -> ToolExecutionResponse:
        """
        Executes a tool call through the zero-trust control plane pipeline.
        If human approval is required, optionally awaits human decision and auto-resumes.
        """
        url = f"{self.control.endpoint}/tool-calls/execute"
        payload = {
            "agent_id": self.name,
            "environment": self.environment,
            "tool_name": tool_name,
            "arguments": arguments,
            "idempotency_key": idempotency_key
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=self.control._get_headers())
            resp.raise_for_status()
            data = resp.json()
            initial_res = ToolExecutionResponse(**data)

            # If approval is required and caller requested waiting for human review
            if initial_res.status == "approval_required" and wait_for_approval and initial_res.approval_id:
                appr_id = initial_res.approval_id
                elapsed = 0.0
                while elapsed < approval_timeout:
                    await asyncio.sleep(approval_poll_interval)
                    elapsed += approval_poll_interval

                    appr_url = f"{self.control.endpoint}/approvals/{appr_id}"
                    appr_resp = await client.get(appr_url, headers=self.control._get_headers())
                    if appr_resp.status_code == 200:
                        appr_data = appr_resp.json()
                        status = appr_data.get("status")
                        if status == "approved":
                            # Resume execution
                            resume_url = f"{self.control.endpoint}/tool-calls/{appr_id}/resume"
                            resume_resp = await client.post(resume_url, headers=self.control._get_headers())
                            resume_resp.raise_for_status()
                            return ToolExecutionResponse(**resume_resp.json())
                        elif status in ("rejected", "expired"):
                            initial_res.status = f"approval_{status}"
                            initial_res.error = f"Human reviewer {status} the operation: {appr_data.get('decision_reason', 'No reason given')}"
                            return initial_res

                initial_res.error = f"Timed out after {approval_timeout}s awaiting human approval."
                return initial_res

            return initial_res


class AgentControl:
    """
    Main SDK entrypoint for AgentControl control plane.
    """

    def __init__(self, endpoint: str = "http://localhost:8000", api_key: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        return headers

    def agent(self, name: str, environment: str = "production") -> AgentClient:
        return AgentClient(control=self, name=name, environment=environment)

    async def register_agent(
        self,
        name: str,
        environment: str = "production",
        owner: str = "platform-team",
        description: str | None = None,
        capabilities: list[str] | None = None
    ) -> dict[str, Any]:
        url = f"{self.endpoint}/agents"
        payload = {
            "name": name,
            "environment": environment,
            "owner": owner,
            "description": description or f"Agent {name}",
            "capabilities": capabilities or []
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def register_tool(
        self,
        name: str,
        description: str,
        risk_level: str = "medium",
        tags: list[str] | None = None,
        parameters_schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.endpoint}/tools"
        payload = {
            "name": name,
            "description": description,
            "risk_level": risk_level,
            "tags": tags or [],
            "parameters_schema": parameters_schema or {}
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def approve(self, approval_id: str, reason: str = "Approved by operator") -> dict[str, Any]:
        url = f"{self.endpoint}/approvals/{approval_id}/approve"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"reason": reason}, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def reject(self, approval_id: str, reason: str = "Rejected by operator") -> dict[str, Any]:
        url = f"{self.endpoint}/approvals/{approval_id}/reject"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"reason": reason}, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    def tool(self, name: str, description: str, risk_level: str = "medium", tags: list[str] | None = None):
        """Decorator to register a Python function as a managed tool."""
        def decorator(func: Callable[..., Any]):
            # Infer parameter schema
            sig = inspect.signature(func)
            props = {}
            for param_name in sig.parameters:
                props[param_name] = {"type": "string"}

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)

            wrapper.tool_name = name
            wrapper.tool_description = description
            wrapper.risk_level = risk_level
            wrapper.tags = tags or []
            wrapper.parameters_schema = {"type": "object", "properties": props}
            return wrapper
        return decorator
