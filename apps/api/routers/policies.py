"""
Policy Engine Router
Create, edit, version, and evaluate declarative YAML security policies.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import Policy
from apps.api.db.session import get_db
from packages.policy_engine.engine import (
    PolicyEngine,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
)

router = APIRouter(prefix="/policies", tags=["Policies"])


class PolicyCreate(BaseModel):
    environment: str = Field(..., description="Target environment (production, staging, development)")
    version: str = Field(default="1.0.0")
    raw_yaml: str = Field(..., description="Valid YAML declaring policies for the environment")


class PolicyResponse(BaseModel):
    id: str
    environment: str
    version: str
    raw_yaml: str
    is_active: bool
    created_at: str
    updated_at: str


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_policy(
    payload: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("admin"))
):
    # Validate YAML syntax first
    try:
        parsed = yaml.safe_load(payload.raw_yaml)
        if not isinstance(parsed, dict):
            raise ValueError("YAML root must be a dictionary")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed YAML policy syntax: {str(e)}"
        )

    # Deactivate existing policies for this environment
    stmt = select(Policy).where(Policy.environment == payload.environment.lower())
    existing_res = await db.execute(stmt)
    for p in existing_res.scalars().all():
        p.is_active = False

    new_policy = Policy(
        environment=payload.environment.lower(),
        version=payload.version,
        raw_yaml=payload.raw_yaml,
        is_active=True
    )
    db.add(new_policy)
    await db.commit()
    await db.refresh(new_policy)

    return PolicyResponse(
        id=new_policy.id,
        environment=new_policy.environment,
        version=new_policy.version,
        raw_yaml=new_policy.raw_yaml,
        is_active=new_policy.is_active,
        created_at=new_policy.created_at.isoformat(),
        updated_at=new_policy.updated_at.isoformat()
    )


@router.get("", response_model=List[PolicyResponse])
async def list_policies(
    environment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Policy).where(Policy.is_active == True)
    if environment:
        stmt = stmt.where(Policy.environment == environment.lower())
    res = await db.execute(stmt)
    policies = res.scalars().all()

    return [
        PolicyResponse(
            id=p.id,
            environment=p.environment,
            version=p.version,
            raw_yaml=p.raw_yaml,
            is_active=p.is_active,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat()
        )
        for p in policies
    ]


@router.post("/evaluate", response_model=PolicyEvaluationResult)
async def evaluate_policy(
    request: PolicyEvaluationRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Policy).where(
        Policy.environment == request.environment.lower(),
        Policy.is_active == True
    )
    res = await db.execute(stmt)
    policy_record = res.scalar_one_or_none()

    engine = PolicyEngine()
    if policy_record:
        engine.load_from_yaml(policy_record.raw_yaml)

    return engine.evaluate(request)
