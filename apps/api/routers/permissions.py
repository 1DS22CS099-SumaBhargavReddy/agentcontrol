"""
Permission Engine Router
Manage fine-grained permission rules and perform live permission verifications.
"""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import Permission
from apps.api.db.session import get_db
from packages.permission_engine.engine import (
    PermissionCheckRequest,
    PermissionCheckResult,
    PermissionEffect,
    PermissionEngine,
    PermissionRule,
)

router = APIRouter(prefix="/permissions", tags=["Permissions"])


class PermissionCreate(BaseModel):
    agent_id: str = Field(..., description="Agent ID or wildcard '*'")
    environment: str = Field(default="production")
    service: str = Field(..., description="e.g. 'github', 'kubernetes', 'aws'")
    resource: str = Field(..., description="e.g. 'pods', 'ec2', 'pr', '*'")
    action: str = Field(..., description="e.g. 'read', 'write', 'delete', 'restart', '*'")
    effect: str = Field(default="allow", description="'allow' or 'deny'")
    conditions: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class PermissionResponse(BaseModel):
    id: str
    agent_id: str
    environment: str
    service: str
    resource: str
    action: str
    effect: str
    conditions: dict[str, Any]
    description: str | None
    created_at: str


@router.post("", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission(
    payload: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("admin"))
):
    perm = Permission(
        agent_id=payload.agent_id,
        environment=payload.environment.lower(),
        service=payload.service.lower(),
        resource=payload.resource,
        action=payload.action,
        effect=payload.effect.lower(),
        conditions=payload.conditions,
        description=payload.description
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)

    return PermissionResponse(
        id=perm.id,
        agent_id=perm.agent_id,
        environment=perm.environment,
        service=perm.service,
        resource=perm.resource,
        action=perm.action,
        effect=perm.effect,
        conditions=perm.conditions or {},
        description=perm.description,
        created_at=perm.created_at.isoformat()
    )


@router.get("", response_model=list[PermissionResponse])
async def list_permissions(
    agent_id: str | None = None,
    environment: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Permission)
    if agent_id:
        stmt = stmt.where((Permission.agent_id == agent_id) | (Permission.agent_id == "*"))
    if environment:
        stmt = stmt.where((Permission.environment == environment.lower()) | (Permission.environment == "*"))

    res = await db.execute(stmt)
    perms = res.scalars().all()

    return [
        PermissionResponse(
            id=p.id,
            agent_id=p.agent_id,
            environment=p.environment,
            service=p.service,
            resource=p.resource,
            action=p.action,
            effect=p.effect,
            conditions=p.conditions or {},
            description=p.description,
            created_at=p.created_at.isoformat()
        )
        for p in perms
    ]


@router.post("/check", response_model=PermissionCheckResult)
async def check_permission(
    request: PermissionCheckRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Permission).where(
        (Permission.agent_id == request.agent_id) | (Permission.agent_id == "*"),
        (Permission.environment == request.environment.lower()) | (Permission.environment == "*")
    )
    res = await db.execute(stmt)
    db_perms = res.scalars().all()

    engine = PermissionEngine([
        PermissionRule(
            id=p.id,
            agent_id=p.agent_id,
            environment=p.environment,
            service=p.service,
            resource=p.resource,
            action=p.action,
            effect=PermissionEffect(p.effect),
            conditions=p.conditions or {},
            description=p.description
        )
        for p in db_perms
    ])

    return engine.check(request)
