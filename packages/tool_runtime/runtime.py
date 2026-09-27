"""
AgentControl Action Execution Engine & Tool Runtime
Sandboxed, resilient execution with timeouts, retries, idempotency, and rollback hooks.
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
import inspect
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.security_guard.scanner import PromptInjectionScanner


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "medium"  # low, medium, high, critical
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    owner: str = "platform-team"
    is_mcp_discovered: bool = False
    timeout_seconds: float = 30.0
    max_retries: int = 2


class ToolExecutionRequest(BaseModel):
    execution_id: str
    idempotency_key: Optional[str] = None
    agent_id: str
    environment: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[float] = None
    enable_retries: bool = True
    rollback_on_failure: bool = False


class ToolExecutionResult(BaseModel):
    execution_id: str
    idempotency_key: Optional[str] = None
    status: ExecutionStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    retry_attempts: int = 0
    rollback_performed: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ToolRuntimeEngine:
    """
    Manages registered tool handlers and executes them with sandboxed safety guarantees.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._rollback_handlers: Dict[str, Callable[..., Any]] = {}
        self._idempotency_store: Dict[str, ToolExecutionResult] = {}

    def register_tool(
        self,
        tool: ToolDefinition,
        handler: Optional[Callable[..., Any]] = None,
        rollback_handler: Optional[Callable[..., Any]] = None
    ) -> None:
        self._tools[tool.name] = tool
        if handler:
            self._handlers[tool.name] = handler
        if rollback_handler:
            self._rollback_handlers[tool.name] = rollback_handler

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        # 1. Idempotency check: prevent duplicate real-world execution
        if request.idempotency_key and request.idempotency_key in self._idempotency_store:
            cached = self._idempotency_store[request.idempotency_key]
            if cached.status == ExecutionStatus.SUCCESS:
                return cached

        tool = self._tools.get(request.tool_name)
        if not tool:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                idempotency_key=request.idempotency_key,
                status=ExecutionStatus.FAILED,
                error=f"Tool '{request.tool_name}' is not registered in runtime",
            )

        handler = self._handlers.get(request.tool_name)
        if not handler:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                idempotency_key=request.idempotency_key,
                status=ExecutionStatus.FAILED,
                error=f"No execution handler registered for tool '{request.tool_name}'",
            )

        timeout = request.timeout_seconds or tool.timeout_seconds
        max_retries = tool.max_retries if request.enable_retries else 0

        start_time = time.perf_counter()
        attempts = 0
        last_error: Optional[str] = None
        status = ExecutionStatus.RUNNING

        while attempts <= max_retries:
            attempts += 1
            try:
                # Call handler with timeout
                if inspect.iscoroutinefunction(handler):
                    res = await asyncio.wait_for(handler(**request.arguments), timeout=timeout)
                else:
                    loop = asyncio.get_event_loop()
                    res = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: handler(**request.arguments)),
                        timeout=timeout
                    )

                # Output security scan: check for prompt injection or malicious payload in output
                if isinstance(res, str):
                    scan = PromptInjectionScanner.scan_text(res)
                    if not scan.is_safe:
                        # Wrap untrusted content with boundary markers to prevent agent prompt hijacking
                        res = PromptInjectionScanner.wrap_untrusted_content(res, source_tag=f"tool_output_{request.tool_name}")

                duration = (time.perf_counter() - start_time) * 1000
                result = ToolExecutionResult(
                    execution_id=request.execution_id,
                    idempotency_key=request.idempotency_key,
                    status=ExecutionStatus.SUCCESS,
                    output=res,
                    duration_ms=round(duration, 2),
                    retry_attempts=attempts - 1,
                    rollback_performed=False
                )

                if request.idempotency_key:
                    self._idempotency_store[request.idempotency_key] = result

                return result

            except asyncio.TimeoutError:
                last_error = f"Execution timed out after {timeout} seconds"
                status = ExecutionStatus.TIMED_OUT
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                status = ExecutionStatus.FAILED
                if attempts <= max_retries:
                    # Exponential backoff
                    await asyncio.sleep(0.1 * (2 ** (attempts - 1)))

        # Failure handling & Rollback hook
        duration = (time.perf_counter() - start_time) * 1000
        rollback_performed = False

        if request.rollback_on_failure and request.tool_name in self._rollback_handlers:
            rb_handler = self._rollback_handlers[request.tool_name]
            try:
                if inspect.iscoroutinefunction(rb_handler):
                    await rb_handler(**request.arguments)
                else:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, lambda: rb_handler(**request.arguments))
                rollback_performed = True
                status = ExecutionStatus.ROLLED_BACK
            except Exception as rb_err:
                last_error = f"{last_error} | Rollback failed: {str(rb_err)}"

        result = ToolExecutionResult(
            execution_id=request.execution_id,
            idempotency_key=request.idempotency_key,
            status=status,
            error=last_error,
            duration_ms=round(duration, 2),
            retry_attempts=attempts - 1,
            rollback_performed=rollback_performed
        )

        return result
