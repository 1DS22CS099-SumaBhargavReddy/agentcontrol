"""
Audit Trail & OpenTelemetry Tracing Router
Queryable append-only audit trail and trace span inspector.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.audit.service import AuditLogger
from apps.api.auth.service import AuthenticatedUser, get_current_user
from apps.api.db.models import AuditEvent
from apps.api.db.session import get_db
from apps.api.routers.executions import telemetry_mgr

router = APIRouter(tags=["Audit & Traces"])


class AuditEventResponse(BaseModel):
    id: str
    timestamp: str
    trace_id: Optional[str]
    agent_id: str
    user_id: Optional[str]
    action: str
    tool_name: Optional[str]
    risk_level: Optional[str]
    policy_decision: Optional[str]
    approval_status: Optional[str]
    execution_status: Optional[str]
    signature_sha256: str
    payload: Dict[str, Any]


@router.get("/audit", response_model=List[AuditEventResponse])
async def list_audit_events(
    agent_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    action: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(AuditEvent).order_by(desc(AuditEvent.timestamp)).limit(limit)
    if agent_id:
        stmt = stmt.where(AuditEvent.agent_id == agent_id)
    if tool_name:
        stmt = stmt.where(AuditEvent.tool_name == tool_name)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"%{action}%"))
    if risk_level:
        stmt = stmt.where(AuditEvent.risk_level == risk_level.lower())

    res = await db.execute(stmt)
    events = res.scalars().all()

    return [
        AuditEventResponse(
            id=e.id,
            timestamp=e.timestamp.isoformat(),
            trace_id=e.trace_id,
            agent_id=e.agent_id,
            user_id=e.user_id,
            action=e.action,
            tool_name=e.tool_name,
            risk_level=e.risk_level,
            policy_decision=e.policy_decision,
            approval_status=e.approval_status,
            execution_status=e.execution_status,
            signature_sha256=e.signature_sha256,
            payload=e.payload or {}
        )
        for e in events
    ]


@router.get("/audit/verify")
async def verify_audit_chain(
    limit: int = Query(default=100, le=1000),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    return await AuditLogger.verify_chain_integrity(db=db, limit=limit)


@router.get("/traces")
async def list_traces(
    limit: int = Query(default=50, le=100),
    user: AuthenticatedUser = Depends(get_current_user)
):
    return telemetry_mgr.list_recent_traces(limit=limit)


@router.get("/traces/{trace_id}")
async def get_trace_spans(
    trace_id: str,
    user: AuthenticatedUser = Depends(get_current_user)
):
    spans = telemetry_mgr.get_trace(trace_id)
    return {"trace_id": trace_id, "spans": [s.dict() for s in spans]}
