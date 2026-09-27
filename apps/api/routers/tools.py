"""
Tool Registry Router
Central registry for tools, risk levels, and schemas.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, get_current_user, require_role
from apps.api.db.models import Tool
from apps.api.db.session import get_db

router = APIRouter(prefix="/tools", tags=["Tools"])


class ToolCreate(BaseModel):
    name: str = Field(..., description="Unique tool identifier, e.g. 'github.create_pr'")
    description: str
    version: str = "1.0.0"
    risk_level: str = Field(default="medium", description="low, medium, high, critical")
    owner: str = "platform-team"
    is_mcp_discovered: bool = False
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: float = 30.0


class ToolResponse(BaseModel):
    id: str
    name: str
    description: str
    version: str
    risk_level: str
    owner: str
    is_mcp_discovered: bool
    parameters_schema: dict[str, Any]
    tags: list[str]
    timeout_seconds: float
    created_at: str
    updated_at: str


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def register_tool(
    payload: ToolCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("agent_executor"))
):
    stmt = select(Tool).where(Tool.name == payload.name)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tool with name '{payload.name}' already registered"
        )

    tool = Tool(
        name=payload.name,
        description=payload.description,
        version=payload.version,
        risk_level=payload.risk_level.lower(),
        owner=payload.owner,
        is_mcp_discovered=payload.is_mcp_discovered,
        parameters_schema=payload.parameters_schema,
        tags=payload.tags,
        timeout_seconds=payload.timeout_seconds
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)

    return ToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        version=tool.version,
        risk_level=tool.risk_level,
        owner=tool.owner,
        is_mcp_discovered=tool.is_mcp_discovered,
        parameters_schema=tool.parameters_schema or {},
        tags=tool.tags or [],
        timeout_seconds=tool.timeout_seconds,
        created_at=tool.created_at.isoformat(),
        updated_at=tool.updated_at.isoformat()
    )


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    risk_level: str | None = None,
    is_mcp: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Tool)
    if risk_level:
        stmt = stmt.where(Tool.risk_level == risk_level.lower())
    if is_mcp is not None:
        stmt = stmt.where(Tool.is_mcp_discovered == is_mcp)

    res = await db.execute(stmt)
    tools = res.scalars().all()

    return [
        ToolResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            version=t.version,
            risk_level=t.risk_level,
            owner=t.owner,
            is_mcp_discovered=t.is_mcp_discovered,
            parameters_schema=t.parameters_schema or {},
            tags=t.tags or [],
            timeout_seconds=t.timeout_seconds,
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat()
        )
        for t in tools
    ]


@router.get("/{id_or_name}", response_model=ToolResponse)
async def get_tool(
    id_or_name: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user)
):
    stmt = select(Tool).where((Tool.id == id_or_name) | (Tool.name == id_or_name))
    res = await db.execute(stmt)
    tool = res.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    return ToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        version=tool.version,
        risk_level=tool.risk_level,
        owner=tool.owner,
        is_mcp_discovered=tool.is_mcp_discovered,
        parameters_schema=tool.parameters_schema or {},
        tags=tool.tags or [],
        timeout_seconds=tool.timeout_seconds,
        created_at=tool.created_at.isoformat(),
        updated_at=tool.updated_at.isoformat()
    )
