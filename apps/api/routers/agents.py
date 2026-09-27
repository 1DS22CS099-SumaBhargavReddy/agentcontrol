"""
Agent Registry Router
CRUD endpoints for registering and inspecting AI agents.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import Agent
from apps.api.db.session import get_db

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentCreate(BaseModel):
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = None
    owner: str = Field(default="platform-team")
    environment: str = Field(default="production")
    version: str = Field(default="1.0.0")
    capabilities: List[str] = Field(default_factory=list)
    metadata_info: Dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    owner: str
    environment: str
    version: str
    status: str
    capabilities: List[str]
    metadata_info: Dict[str, Any]
    created_at: str
    updated_at: str


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("agent_executor"))
):
    stmt = select(Agent).where(Agent.name == payload.name)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{payload.name}' already exists"
        )

    agent = Agent(
        name=payload.name,
        description=payload.description,
        owner=payload.owner,
        environment=payload.environment.lower(),
        version=payload.version,
        capabilities=payload.capabilities,
        metadata_info=payload.metadata_info,
        status="active"
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        owner=agent.owner,
        environment=agent.environment,
        version=agent.version,
        status=agent.status,
        capabilities=agent.capabilities or [],
        metadata_info=agent.metadata_info or {},
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat()
    )


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    environment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Agent)
    if environment:
        stmt = stmt.where(Agent.environment == environment.lower())
    res = await db.execute(stmt)
    agents = res.scalars().all()

    return [
        AgentResponse(
            id=a.id,
            name=a.name,
            description=a.description,
            owner=a.owner,
            environment=a.environment,
            version=a.version,
            status=a.status,
            capabilities=a.capabilities or [],
            metadata_info=a.metadata_info or {},
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat()
        )
        for a in agents
    ]


@router.get("/{id_or_name}", response_model=AgentResponse)
async def get_agent(
    id_or_name: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Agent).where((Agent.id == id_or_name) | (Agent.name == id_or_name))
    res = await db.execute(stmt)
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        owner=agent.owner,
        environment=agent.environment,
        version=agent.version,
        status=agent.status,
        capabilities=agent.capabilities or [],
        metadata_info=agent.metadata_info or {},
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat()
    )
