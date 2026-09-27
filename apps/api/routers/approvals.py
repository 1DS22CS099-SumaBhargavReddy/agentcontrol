"""
Human Approval System Router
Manages human-in-the-loop pending approval queues, signatures, and timeouts.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.audit.service import AuditLogger
from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import ApprovalRequest, ToolCall
from apps.api.db.session import get_db

router = APIRouter(prefix="/approvals", tags=["Human Approvals"])


class ApprovalCreate(BaseModel):
    tool_call_id: str
    agent_id: str
    environment: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_score: float
    risk_level: str
    reason_codes: list[str] = Field(default_factory=list)
    requested_by: str = "agent-system"
    expires_in_minutes: int = 60


class ApprovalDecision(BaseModel):
    reason: str | None = Field(default=None, description="Human reviewer rationale")


class ApprovalResponse(BaseModel):
    id: str
    tool_call_id: str
    agent_id: str
    environment: str
    tool_name: str
    parameters: dict[str, Any]
    risk_score: float
    risk_level: str
    reason_codes: list[str]
    status: str  # pending, approved, rejected, expired
    requested_by: str
    approved_by: str | None
    decision_reason: str | None
    expires_at: str
    created_at: str
    updated_at: str


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval_request(
    payload: ApprovalCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=payload.expires_in_minutes)

    req = ApprovalRequest(
        tool_call_id=payload.tool_call_id,
        agent_id=payload.agent_id,
        environment=payload.environment.lower(),
        tool_name=payload.tool_name,
        parameters=payload.parameters,
        risk_score=payload.risk_score,
        risk_level=payload.risk_level,
        reason_codes=payload.reason_codes,
        status="pending",
        requested_by=payload.requested_by,
        expires_at=expires_at
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # Log audit event
    await AuditLogger.log_event(
        db=db,
        agent_id=payload.agent_id,
        user_id=user.user_id,
        action="approval.requested",
        tool_name=payload.tool_name,
        risk_level=payload.risk_level,
        approval_status="pending",
        payload={
            "approval_id": req.id,
            "risk_score": payload.risk_score,
            "reasons": payload.reason_codes
        }
    )

    return ApprovalResponse(
        id=req.id,
        tool_call_id=req.tool_call_id,
        agent_id=req.agent_id,
        environment=req.environment,
        tool_name=req.tool_name,
        parameters=req.parameters or {},
        risk_score=req.risk_score,
        risk_level=req.risk_level,
        reason_codes=req.reason_codes or [],
        status=req.status,
        requested_by=req.requested_by,
        approved_by=req.approved_by,
        decision_reason=req.decision_reason,
        expires_at=req.expires_at.isoformat(),
        created_at=req.created_at.isoformat(),
        updated_at=req.updated_at.isoformat()
    )


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    status_filter: str | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(ApprovalRequest).order_by(desc(ApprovalRequest.created_at)).limit(limit)
    if status_filter:
        stmt = stmt.where(ApprovalRequest.status == status_filter.lower())
    if agent_id:
        stmt = stmt.where(ApprovalRequest.agent_id == agent_id)

    res = await db.execute(stmt)
    approvals = res.scalars().all()

    now = datetime.now(timezone.utc)
    # Check for expired ones dynamically
    results = []
    for a in approvals:
        current_status = a.status
        if current_status == "pending" and a.expires_at and _to_utc(a.expires_at) < now:
            current_status = "expired"

        results.append(
            ApprovalResponse(
                id=a.id,
                tool_call_id=a.tool_call_id,
                agent_id=a.agent_id,
                environment=a.environment,
                tool_name=a.tool_name,
                parameters=a.parameters or {},
                risk_score=a.risk_score,
                risk_level=a.risk_level,
                reason_codes=a.reason_codes or [],
                status=current_status,
                requested_by=a.requested_by,
                approved_by=a.approved_by,
                decision_reason=a.decision_reason,
                expires_at=a.expires_at.isoformat(),
                created_at=a.created_at.isoformat(),
                updated_at=a.updated_at.isoformat()
            )
        )
    return results


@router.get("/{id}", response_model=ApprovalResponse)
async def get_approval(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == id)
    res = await db.execute(stmt)
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    current_status = a.status
    if current_status == "pending" and a.expires_at and _to_utc(a.expires_at) < datetime.now(timezone.utc):
        current_status = "expired"

    return ApprovalResponse(
        id=a.id,
        tool_call_id=a.tool_call_id,
        agent_id=a.agent_id,
        environment=a.environment,
        tool_name=a.tool_name,
        parameters=a.parameters or {},
        risk_score=a.risk_score,
        risk_level=a.risk_level,
        reason_codes=a.reason_codes or [],
        status=current_status,
        requested_by=a.requested_by,
        approved_by=a.approved_by,
        decision_reason=a.decision_reason,
        expires_at=a.expires_at.isoformat(),
        created_at=a.created_at.isoformat(),
        updated_at=a.updated_at.isoformat()
    )


@router.post("/{id}/approve", response_model=ApprovalResponse)
async def approve_request(
    id: str,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("approver"))
):
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == id)
    res = await db.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    now = datetime.now(timezone.utc)
    if req.expires_at and _to_utc(req.expires_at) < now:
        req.status = "expired"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Approval request has expired")

    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Request is already {req.status}")

    req.status = "approved"
    req.approved_by = user.user_id
    req.decision_reason = payload.reason or "Approved by authorized human operator"
    req.updated_at = now

    # Also update associated ToolCall record if exists
    tc_stmt = select(ToolCall).where(ToolCall.id == req.tool_call_id)
    tc_res = await db.execute(tc_stmt)
    tc = tc_res.scalar_one_or_none()
    if tc:
        tc.status = "approved"

    await db.commit()
    await db.refresh(req)

    # Log audit event
    await AuditLogger.log_event(
        db=db,
        agent_id=req.agent_id,
        user_id=user.user_id,
        action="approval.granted",
        tool_name=req.tool_name,
        risk_level=req.risk_level,
        approval_status="approved",
        payload={
            "approval_id": req.id,
            "approved_by": user.user_id,
            "reason": req.decision_reason
        }
    )

    return ApprovalResponse(
        id=req.id,
        tool_call_id=req.tool_call_id,
        agent_id=req.agent_id,
        environment=req.environment,
        tool_name=req.tool_name,
        parameters=req.parameters or {},
        risk_score=req.risk_score,
        risk_level=req.risk_level,
        reason_codes=req.reason_codes or [],
        status=req.status,
        requested_by=req.requested_by,
        approved_by=req.approved_by,
        decision_reason=req.decision_reason,
        expires_at=req.expires_at.isoformat(),
        created_at=req.created_at.isoformat(),
        updated_at=req.updated_at.isoformat()
    )


@router.post("/{id}/reject", response_model=ApprovalResponse)
async def reject_request(
    id: str,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("approver"))
):
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == id)
    res = await db.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    now = datetime.now(timezone.utc)
    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Request is already {req.status}")

    req.status = "rejected"
    req.approved_by = user.user_id
    req.decision_reason = payload.reason or "Rejected by human reviewer"
    req.updated_at = now

    # Also update associated ToolCall record if exists
    tc_stmt = select(ToolCall).where(ToolCall.id == req.tool_call_id)
    tc_res = await db.execute(tc_stmt)
    tc = tc_res.scalar_one_or_none()
    if tc:
        tc.status = "rejected"

    await db.commit()
    await db.refresh(req)

    # Log audit event
    await AuditLogger.log_event(
        db=db,
        agent_id=req.agent_id,
        user_id=user.user_id,
        action="approval.rejected",
        tool_name=req.tool_name,
        risk_level=req.risk_level,
        approval_status="rejected",
        payload={
            "approval_id": req.id,
            "rejected_by": user.user_id,
            "reason": req.decision_reason
        }
    )

    return ApprovalResponse(
        id=req.id,
        tool_call_id=req.tool_call_id,
        agent_id=req.agent_id,
        environment=req.environment,
        tool_name=req.tool_name,
        parameters=req.parameters or {},
        risk_score=req.risk_score,
        risk_level=req.risk_level,
        reason_codes=req.reason_codes or [],
        status=req.status,
        requested_by=req.requested_by,
        approved_by=req.approved_by,
        decision_reason=req.decision_reason,
        expires_at=req.expires_at.isoformat(),
        created_at=req.created_at.isoformat(),
        updated_at=req.updated_at.isoformat()
    )
