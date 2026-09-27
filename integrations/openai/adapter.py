"""
AgentControl OpenAI Agents SDK / Function Calling Adapter
Wraps OpenAI function tools so that any function execution is gated by the AgentControl control plane.
"""

import json
from typing import Any

from packages.sdk.client import AgentControl, ToolExecutionResponse


class OpenAIControlledTool:
    """
    Wraps a tool definition to expose standard OpenAI tool JSON schema
    while routing calls safely through AgentControl.
    """

    def __init__(
        self,
        control: AgentControl,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        agent_id: str,
        environment: str = "production",
        risk_level: str = "medium"
    ):
        self.control = control
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema
        self.agent_id = agent_id
        self.environment = environment
        self.risk_level = risk_level
        self.agent = control.agent(name=agent_id, environment=environment)

    def to_openai_tool(self) -> dict[str, Any]:
        """Converts to standard OpenAI ChatCompletions/Agents tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema
            }
        }

    async def execute_from_openai_call(self, function_arguments_str: str) -> dict[str, Any]:
        """Parses OpenAI JSON arguments string and executes through AgentControl."""
        try:
            args = json.loads(function_arguments_str) if isinstance(function_arguments_str, str) else function_arguments_str
        except json.JSONDecodeError as e:
            return {"status": "error", "error": f"Invalid JSON arguments: {str(e)}"}

        res: ToolExecutionResponse = await self.agent.execute_tool(
            tool_name=self.name,
            arguments=args
        )

        return {
            "status": res.status,
            "risk_score": res.risk_score,
            "risk_level": res.risk_level,
            "result": res.execution_result,
            "error": res.error,
            "trace_id": res.trace_id
        }
