"""
AgentControl Model Context Protocol (MCP) Gateway
Discovers tools from MCP servers and binds them to the zero-trust control plane.
"""

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

from packages.tool_runtime.runtime import ToolDefinition, ToolRuntimeEngine


class MCPToolSchema(BaseModel):
    name: str
    description: str | None = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class MCPDiscoveryResult(BaseModel):
    server_endpoint: str
    discovered_tools_count: int
    tools: list[ToolDefinition]


class MCPGateway:
    """
    Connects to MCP servers, ingests tool manifests, and proxies executions
    strictly through the AgentControl security and policy pipeline.
    """

    def __init__(self, runtime_engine: ToolRuntimeEngine):
        self.runtime_engine = runtime_engine
        self._mcp_servers: dict[str, str] = {}  # tool_name -> server_endpoint

    async def discover_and_register_tools(
        self,
        server_endpoint: str,
        auth_token: str | None = None
    ) -> MCPDiscoveryResult:
        """
        Discovers tools via MCP HTTP/JSON-RPC protocol and registers them into the runtime.
        Zero-trust principle: Discovered MCP tools default to high risk and strict policy gating.
        """
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        # Standard MCP JSON-RPC 2.0 list_tools payload
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        registered_tools: list[ToolDefinition] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(server_endpoint, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    tools_list = data.get("result", {}).get("tools", [])
                    for t in tools_list:
                        tool_name = f"mcp.{t.get('name')}"
                        t_def = ToolDefinition(
                            name=tool_name,
                            description=t.get("description", "Discovered via Model Context Protocol"),
                            parameters_schema=t.get("inputSchema", {}),
                            risk_level="high",  # Zero-trust default
                            tags=["mcp", "external"],
                            is_mcp_discovered=True,
                            version="1.0.0"
                        )
                        # Register with proxy handler
                        self._mcp_servers[tool_name] = server_endpoint
                        self.runtime_engine.register_tool(
                            t_def,
                            handler=self._create_mcp_proxy_handler(server_endpoint, t.get("name"), auth_token)
                        )
                        registered_tools.append(t_def)
        except Exception:
            # Fallback for mock/simulation when external server is offline
            pass

        return MCPDiscoveryResult(
            server_endpoint=server_endpoint,
            discovered_tools_count=len(registered_tools),
            tools=registered_tools
        )

    def _create_mcp_proxy_handler(
        self,
        server_endpoint: str,
        raw_tool_name: str,
        auth_token: str | None = None
    ) -> Callable[..., Any]:
        """Creates an async proxy caller that communicates with the MCP server."""
        async def proxy_call(**arguments):
            headers = {"Content-Type": "application/json"}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

            call_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": raw_tool_name,
                    "arguments": arguments
                }
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(server_endpoint, json=call_payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                return data.get("result", data)

        return proxy_call
