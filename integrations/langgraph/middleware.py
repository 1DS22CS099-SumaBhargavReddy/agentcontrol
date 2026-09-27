"""
AgentControl LangGraph Integration
Middleware and node wrappers for gating LangGraph tool execution through the AgentControl control plane.
"""

from typing import Any, Callable, Dict, List, Optional
from packages.sdk.client import AgentControl, ToolExecutionResponse


class AgentControlToolNode:
    """
    Drop-in replacement / wrapper for LangGraph ToolNode that intercepts every tool invocation
    and runs it through the AgentControl zero-trust pipeline (Permission -> Policy -> Risk -> Approval -> Execution).
    """

    def __init__(
        self,
        control: AgentControl,
        agent_id: str,
        environment: str = "production",
        wait_for_approval: bool = True
    ):
        self.control = control
        self.agent_id = agent_id
        self.environment = environment
        self.wait_for_approval = wait_for_approval
        self.agent = control.agent(name=agent_id, environment=environment)

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes pending tool calls found in the LangGraph state messages.
        """
        messages = state.get("messages", [])
        if not messages:
            return state

        last_message = messages[-1]
        tool_calls = getattr(last_message, "tool_calls", None) or last_message.get("tool_calls", [])

        results = []
        for call in tool_calls:
            tool_name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            tool_args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")

            # Intercept and gate through AgentControl
            exec_res: ToolExecutionResponse = await self.agent.execute_tool(
                tool_name=tool_name,
                arguments=tool_args,
                wait_for_approval=self.wait_for_approval
            )

            results.append({
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "status": exec_res.status,
                "risk_score": exec_res.risk_score,
                "risk_level": exec_res.risk_level,
                "content": exec_res.execution_result if exec_res.status == "approved_and_executed" else exec_res.error,
                "trace_id": exec_res.trace_id
            })

        # Append tool execution outputs to state
        new_state = dict(state)
        new_state["agentcontrol_results"] = results
        return new_state
