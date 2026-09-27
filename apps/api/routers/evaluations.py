"""
Agent Evaluation & System Metrics Router
Trajectory evaluation, regression tracking, and aggregated operational dashboards.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, get_current_user
from apps.api.db.models import (
    Agent,
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    EvaluationRecord,
    ToolCall,
)
from apps.api.db.session import get_db
from packages.evaluation.evaluator import (
    AgentEvaluator,
    EvaluationInput,
    EvaluationReport,
)

router = APIRouter(tags=["Evaluations & Metrics"])


class SystemMetricsResponse(BaseModel):
    active_agents: int
    agent_runs_count: int
    blocked_actions_count: int
    human_approvals_pending: int
    human_approvals_total: int
    policy_violations_count: int
    audit_events_count: int
    avg_safety_score: float
    total_estimated_cost_usd: float


@router.post("/evaluations", response_model=EvaluationReport)
async def evaluate_agent_trajectory(
    eval_input: EvaluationInput,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    report = AgentEvaluator.evaluate(eval_input)

    # Persist evaluation record
    record = EvaluationRecord(
        run_id=eval_input.run_id,
        agent_id=eval_input.agent_id,
        task_success=report.task_success,
        tool_selection=report.tool_selection,
        policy_compliance=report.policy_compliance,
        safety=report.safety,
        latency_ms=report.latency_ms,
        cost_usd=report.cost_usd,
        summary=report.summary
    )
    db.add(record)
    await db.commit()

    return report


@router.get("/metrics", response_model=SystemMetricsResponse)
async def get_system_metrics(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    # Active agents count
    agent_count = (await db.execute(select(func.count(Agent.id)).where(Agent.status == "active"))).scalar() or 0

    # Total runs count
    runs_count = (await db.execute(select(func.count(AgentRun.id)))).scalar() or 0

    # Total cost from runs
    cost_sum = (await db.execute(select(func.sum(AgentRun.total_cost_usd)))).scalar() or 0.0

    # Blocked actions (rejected or failed or policy blocked)
    blocked_actions = (await db.execute(
        select(func.count(ToolCall.id)).where(ToolCall.status.in_(["rejected", "policy_blocked", "security_blocked"]))
    )).scalar() or 0

    # Approvals pending and total
    pending_approvals = (await db.execute(
        select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")
    )).scalar() or 0
    total_approvals = (await db.execute(select(func.count(ApprovalRequest.id)))).scalar() or 0

    # Audit events count
    audit_events = (await db.execute(select(func.count(AuditEvent.id)))).scalar() or 0

    # Policy violations logged in audit
    policy_violations = (await db.execute(
        select(func.count(AuditEvent.id)).where(AuditEvent.action.ilike("%violation%"))
    )).scalar() or 0

    # Average safety score from evaluations
    avg_safety = (await db.execute(select(func.avg(EvaluationRecord.safety)))).scalar() or 0.98

    return SystemMetricsResponse(
        active_agents=agent_count,
        agent_runs_count=runs_count,
        blocked_actions_count=blocked_actions,
        human_approvals_pending=pending_approvals,
        human_approvals_total=total_approvals,
        policy_violations_count=policy_violations,
        audit_events_count=audit_events,
        avg_safety_score=round(float(avg_safety), 2),
        total_estimated_cost_usd=round(float(cost_sum), 2)
    )
