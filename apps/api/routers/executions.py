"""
Unified Action Execution & Control Plane Interceptor Router
Coordinates Permission -> Policy -> Risk -> Approval -> Execution -> Audit pipeline.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.audit.service import AuditLogger
from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import (
    AgentRun,
    ApprovalRequest,
    ExecutionRecord,
    Permission,
    Policy,
    ToolCall,
)
from apps.api.db.session import get_db
from packages.decision_engine.engine import (
    DecisionOutcome,
    DecisionRequest,
    HybridDecisionProvider,
    RuleBasedDecisionProvider,
)
from packages.permission_engine.engine import (
    PermissionCheckRequest,
    PermissionEffect,
    PermissionEngine,
    PermissionRule,
)
from packages.policy_engine.engine import (
    PolicyEngine,
    PolicyEvaluationRequest,
)
from packages.risk_engine.engine import (
    RiskAssessmentRequest,
    RiskEngine,
)
from packages.security_guard.scanner import (
    BrowserScanner,
    PromptInjectionScanner,
)
from packages.telemetry.tracer import TelemetryManager
from packages.tool_runtime.runtime import (
    ExecutionStatus,
    ToolDefinition,
    ToolExecutionRequest,
    ToolRuntimeEngine,
)

router = APIRouter(tags=["Executions & Runs"])

# Global shared runtime instances
telemetry_mgr = TelemetryManager()
runtime_engine = ToolRuntimeEngine()
risk_engine = RiskEngine()
decision_provider = HybridDecisionProvider(rule_provider=RuleBasedDecisionProvider())

# Register builtin demonstration tools
runtime_engine.register_tool(
    ToolDefinition(
        name="kubernetes.restart_pod",
        description="Restart a Kubernetes pod in the cluster",
        risk_level="critical",
        tags=["destructive", "kubernetes", "infrastructure"]
    ),
    handler=lambda namespace, pod: {"status": "restarted", "pod": pod, "namespace": namespace, "restarted_at": datetime.now(timezone.utc).isoformat()},
    rollback_handler=lambda namespace, pod: {"status": "rollback_completed", "pod": pod, "namespace": namespace}
)

runtime_engine.register_tool(
    ToolDefinition(
        name="github.create_pr",
        description="Create a pull request on GitHub",
        risk_level="medium",
        tags=["github", "write"]
    ),
    handler=lambda repo, title, head, base: {"pr_number": 42, "url": f"https://github.com/{repo}/pull/42", "title": title}
)

runtime_engine.register_tool(
    ToolDefinition(
        name="database.read_query",
        description="Execute read-only SQL query on database",
        risk_level="low",
        tags=["database", "read"]
    ),
    handler=lambda query: {"rows": [{"id": 1, "status": "active"}], "row_count": 1}
)

runtime_engine.register_tool(
    ToolDefinition(
        name="browser.fetch_url",
        description="Fetch content from external URL",
        risk_level="medium",
        tags=["web", "browser", "network"]
    ),
    handler=lambda url: {"url": url, "status_code": 200, "content": "Sample verified document content."}
)


class RunCreate(BaseModel):
    agent_id: str
    environment: str = "production"
    trace_id: str | None = None
    metadata_info: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    id: str
    agent_id: str
    environment: str
    trace_id: str
    status: str
    total_duration_ms: float
    total_tokens: int
    total_cost_usd: float
    started_at: str
    completed_at: str | None


class ToolExecuteRequest(BaseModel):
    agent_id: str
    environment: str = "production"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    bypass_approval_check: bool = False  # internal flag used strictly after approval sign-off


class ToolExecuteResponse(BaseModel):
    call_id: str
    status: str  # approved_and_executed, approval_required, permission_denied, policy_blocked, execution_failed, security_blocked
    risk_score: float
    risk_level: str
    reason_codes: list[str]
    approval_id: str | None = None
    execution_result: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0
    trace_id: str


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    trace_id = payload.trace_id or uuid.uuid4().hex
    run = AgentRun(
        agent_id=payload.agent_id,
        environment=payload.environment.lower(),
        trace_id=trace_id,
        status="running",
        metadata_info=payload.metadata_info
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return RunResponse(
        id=run.id,
        agent_id=run.agent_id,
        environment=run.environment,
        trace_id=run.trace_id,
        status=run.status,
        total_duration_ms=run.total_duration_ms,
        total_tokens=run.total_tokens,
        total_cost_usd=run.total_cost_usd,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None
    )


@router.get("/runs/{id}", response_model=RunResponse)
async def get_run(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(AgentRun).where(AgentRun.id == id)
    run = (await db.execute(stmt)).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    return RunResponse(
        id=run.id,
        agent_id=run.agent_id,
        environment=run.environment,
        trace_id=run.trace_id,
        status=run.status,
        total_duration_ms=run.total_duration_ms,
        total_tokens=run.total_tokens,
        total_cost_usd=run.total_cost_usd,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None
    )


@router.post("/tool-calls/execute", response_model=ToolExecuteResponse)
async def execute_tool_call(
    payload: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Main Zero-Trust Control Plane Pipeline:
    Security Scan -> Permission -> Policy -> Risk -> Decision -> Approval -> Execution -> Audit -> Telemetry
    """
    trace_id = payload.trace_id or uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    call_id = str(uuid.uuid4())

    with telemetry_mgr.start_span(
        name=f"tool_gate:{payload.tool_name}",
        operation_name="tool.call",
        trace_id=trace_id,
        span_id=span_id,
        attributes={
            "gen_ai.agent.id": payload.agent_id,
            "gen_ai.tool.name": payload.tool_name,
            "environment": payload.environment
        }
    ):
        # 1. SECURITY SCAN: Browser SSRF & Prompt Injection
        # Check URLs in arguments
        for v in payload.arguments.values():
            if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://") or "://" in v):
                scan_res = BrowserScanner.scan_url(v)
                if not scan_res.is_safe:
                    await AuditLogger.log_event(
                        db=db,
                        agent_id=payload.agent_id,
                        user_id=user.user_id,
                        action="security.blocked_ssrf",
                        tool_name=payload.tool_name,
                        risk_level="critical",
                        execution_status="blocked",
                        trace_id=trace_id,
                        payload={"url": v, "reason": scan_res.reason}
                    )
                    return ToolExecuteResponse(
                        call_id=call_id,
                        status="security_blocked",
                        risk_score=1.0,
                        risk_level="critical",
                        reason_codes=["ssrf_attempt_detected", scan_res.blocked_category or "malicious_url"],
                        error=f"Security violation: {scan_res.reason}",
                        trace_id=trace_id
                    )

            # Check for prompt injection in argument strings
            if isinstance(v, str):
                inj_res = PromptInjectionScanner.scan_text(v)
                if not inj_res.is_safe:
                    await AuditLogger.log_event(
                        db=db,
                        agent_id=payload.agent_id,
                        user_id=user.user_id,
                        action="security.blocked_injection",
                        tool_name=payload.tool_name,
                        risk_level="high",
                        execution_status="blocked",
                        trace_id=trace_id,
                        payload={"patterns": inj_res.detected_patterns}
                    )
                    return ToolExecuteResponse(
                        call_id=call_id,
                        status="security_blocked",
                        risk_score=inj_res.risk_score,
                        risk_level="high",
                        reason_codes=["prompt_injection_detected"] + inj_res.detected_patterns,
                        error=f"Security violation: {inj_res.reason}",
                        trace_id=trace_id
                    )

        # 2. PERMISSION ENGINE CHECK
        # Fetch relevant rules from DB
        stmt = select(Permission).where(
            (Permission.agent_id == payload.agent_id) | (Permission.agent_id == "*"),
            (Permission.environment == payload.environment.lower()) | (Permission.environment == "*")
        )
        perm_records = (await db.execute(stmt)).scalars().all()
        perm_engine = PermissionEngine([
            PermissionRule(
                id=p.id,
                agent_id=p.agent_id,
                environment=p.environment,
                service=p.service,
                resource=p.resource,
                action=p.action,
                effect=PermissionEffect(p.effect),
                conditions=p.conditions or {}
            )
            for p in perm_records
        ])

        service_name, action_name = (payload.tool_name.split(".", 1) if "." in payload.tool_name else ("general", payload.tool_name))
        perm_result = perm_engine.check(
            PermissionCheckRequest(
                agent_id=payload.agent_id,
                environment=payload.environment,
                service=service_name,
                resource="*",
                action=action_name,
                context=payload.arguments
            )
        )

        if not perm_result.allowed:
            await AuditLogger.log_event(
                db=db,
                agent_id=payload.agent_id,
                user_id=user.user_id,
                action="permission.denied",
                tool_name=payload.tool_name,
                risk_level="high",
                policy_decision="denied",
                execution_status="blocked",
                trace_id=trace_id,
                payload={"reason": perm_result.reason}
            )
            return ToolExecuteResponse(
                call_id=call_id,
                status="permission_denied",
                risk_score=0.8,
                risk_level="high",
                reason_codes=["unauthorized_tool_access"],
                error=perm_result.reason,
                trace_id=trace_id
            )

        # 3. POLICY ENGINE EVALUATION
        pol_stmt = select(Policy).where(
            Policy.environment == payload.environment.lower(),
            Policy.is_active == True
        )
        pol_record = (await db.execute(pol_stmt)).scalar_one_or_none()
        pol_engine = PolicyEngine()
        if pol_record:
            pol_engine.load_from_yaml(pol_record.raw_yaml)

        # Get tool definition if available
        tool_def = runtime_engine.get_tool(payload.tool_name)
        tool_tags = tool_def.tags if tool_def else []
        tool_inherent_risk = tool_def.risk_level if tool_def else "medium"

        pol_result = pol_engine.evaluate(
            PolicyEvaluationRequest(
                agent_id=payload.agent_id,
                environment=payload.environment,
                tool_name=payload.tool_name,
                tool_tags=tool_tags,
                arguments=payload.arguments
            )
        )

        if not pol_result.allowed:
            await AuditLogger.log_event(
                db=db,
                agent_id=payload.agent_id,
                user_id=user.user_id,
                action="policy.violation_blocked",
                tool_name=payload.tool_name,
                risk_level="critical",
                policy_decision="blocked",
                execution_status="blocked",
                trace_id=trace_id,
                payload={"violations": [v.dict() for v in pol_result.violations]}
            )
            return ToolExecuteResponse(
                call_id=call_id,
                status="policy_blocked",
                risk_score=0.9,
                risk_level="critical",
                reason_codes=["policy_violation"],
                error="; ".join(v.message for v in pol_result.violations),
                trace_id=trace_id
            )

        # 4. RISK ASSESSMENT ENGINE
        risk_result = risk_engine.evaluate(
            RiskAssessmentRequest(
                agent_id=payload.agent_id,
                environment=payload.environment,
                tool_name=payload.tool_name,
                tool_inherent_risk=tool_inherent_risk,
                tool_tags=tool_tags,
                arguments=payload.arguments
            )
        )

        # 5. DECISION LAYER
        decision = await decision_provider.decide(
            DecisionRequest(
                question=f"Should {payload.agent_id} execute {payload.tool_name}?",
                context={
                    "policy_allowed": pol_result.allowed,
                    "policy_requires_approval": pol_result.requires_human_approval,
                    "risk_score": risk_result.risk_score,
                    "risk_reasons": risk_result.reason_codes
                }
            )
        )

        # Record proposed tool call in DB
        tc = ToolCall(
            id=call_id,
            run_id=payload.run_id,
            agent_id=payload.agent_id,
            environment=payload.environment,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            status="proposed",
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level.value,
            requires_approval=(decision.decision == DecisionOutcome.HUMAN_REVIEW or risk_result.requires_human_approval or pol_result.requires_human_approval)
        )
        db.add(tc)
        await db.commit()

        # 6. HUMAN-IN-THE-LOOP APPROVAL CHECK
        needs_approval = tc.requires_approval and not payload.bypass_approval_check
        if needs_approval:
            from datetime import timedelta
            approval_req = ApprovalRequest(
                tool_call_id=call_id,
                agent_id=payload.agent_id,
                environment=payload.environment,
                tool_name=payload.tool_name,
                parameters=payload.arguments,
                risk_score=risk_result.risk_score,
                risk_level=risk_result.risk_level.value,
                reason_codes=risk_result.reason_codes + pol_result.approval_reasons,
                status="pending",
                requested_by=payload.agent_id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
            )
            db.add(approval_req)
            tc.approval_id = approval_req.id
            tc.status = "pending_approval"
            await db.commit()

            await AuditLogger.log_event(
                db=db,
                agent_id=payload.agent_id,
                user_id=user.user_id,
                action="tool.paused_for_approval",
                tool_name=payload.tool_name,
                risk_level=risk_result.risk_level.value,
                approval_status="pending",
                trace_id=trace_id,
                payload={"approval_id": approval_req.id, "risk_score": risk_result.risk_score}
            )

            return ToolExecuteResponse(
                call_id=call_id,
                status="approval_required",
                risk_score=risk_result.risk_score,
                risk_level=risk_result.risk_level.value,
                reason_codes=risk_result.reason_codes + pol_result.approval_reasons,
                approval_id=approval_req.id,
                trace_id=trace_id
            )

        # 7. EXECUTION ENGINE
        tc.status = "executing"
        await db.commit()

        exec_id = str(uuid.uuid4())
        exec_res = await runtime_engine.execute(
            ToolExecutionRequest(
                execution_id=exec_id,
                idempotency_key=payload.idempotency_key,
                agent_id=payload.agent_id,
                environment=payload.environment,
                tool_name=payload.tool_name,
                arguments=payload.arguments,
                rollback_on_failure=True
            )
        )

        # Save ExecutionRecord
        exec_record = ExecutionRecord(
            id=exec_id,
            tool_call_id=call_id,
            idempotency_key=payload.idempotency_key,
            status=exec_res.status.value,
            output=exec_res.output,
            error=exec_res.error,
            duration_ms=exec_res.duration_ms,
            retry_attempts=exec_res.retry_attempts,
            rollback_performed=exec_res.rollback_performed
        )
        db.add(exec_record)

        tc.execution_id = exec_id
        tc.status = "completed" if exec_res.status == ExecutionStatus.SUCCESS else "failed"
        await db.commit()

        # 8. AUDIT LOG & TELEMETRY
        await AuditLogger.log_event(
            db=db,
            agent_id=payload.agent_id,
            user_id=user.user_id,
            action="tool.executed",
            tool_name=payload.tool_name,
            risk_level=risk_result.risk_level.value,
            policy_decision="allowed",
            approval_status="approved" if payload.bypass_approval_check else "not_required",
            execution_status=exec_res.status.value,
            trace_id=trace_id,
            payload={"duration_ms": exec_res.duration_ms, "output": exec_res.output}
        )

        return ToolExecuteResponse(
            call_id=call_id,
            status="approved_and_executed" if exec_res.status == ExecutionStatus.SUCCESS else "execution_failed",
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level.value,
            reason_codes=risk_result.reason_codes,
            approval_id=tc.approval_id,
            execution_result=exec_res.output,
            error=exec_res.error,
            duration_ms=exec_res.duration_ms,
            trace_id=trace_id
        )


@router.post("/tool-calls/{approval_id}/resume", response_model=ToolExecuteResponse)
async def resume_approved_tool_call(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("approver"))
):
    """
    Executes a previously paused tool call once approved by a human.
    """
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    approval = (await db.execute(stmt)).scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    if approval.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval request is not in 'approved' status (current status: {approval.status})"
        )

    # Execute directly via tool execution pipeline with bypass_approval_check=True
    return await execute_tool_call(
        payload=ToolExecuteRequest(
            agent_id=approval.agent_id,
            environment=approval.environment,
            tool_name=approval.tool_name,
            arguments=approval.parameters or {},
            bypass_approval_check=True
        ),
        db=db,
        user=user
    )
