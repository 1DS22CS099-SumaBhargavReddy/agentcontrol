"""
Model Context Protocol (MCP) Router
Endpoints to connect external MCP servers and discover tools.
"""


from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, require_role
from apps.api.db.models import Tool
from apps.api.db.session import get_db
from apps.api.routers.executions import runtime_engine
from integrations.mcp.gateway import MCPDiscoveryResult, MCPGateway

router = APIRouter(prefix="/mcp", tags=["MCP Gateway"])

_mcp_gateway = MCPGateway(runtime_engine=runtime_engine)


class MCPConnectRequest(BaseModel):
    server_endpoint: str = Field(..., description="HTTP/SSE URL of external MCP server")
    auth_token: str | None = None


@router.post("/discover", response_model=MCPDiscoveryResult)
async def discover_mcp_tools(
    payload: MCPConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_role("admin"))
):
    result = await _mcp_gateway.discover_and_register_tools(
        server_endpoint=payload.server_endpoint,
        auth_token=payload.auth_token
    )

    # Sync discovered tools into DB with zero-trust flags
    for tool_def in result.tools:
        stmt = select(Tool).where(Tool.name == tool_def.name)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            db_tool = Tool(
                name=tool_def.name,
                description=tool_def.description,
                version=tool_def.version,
                risk_level=tool_def.risk_level,
                owner="mcp-server",
                is_mcp_discovered=True,
                parameters_schema=tool_def.parameters_schema,
                tags=tool_def.tags,
                timeout_seconds=tool_def.timeout_seconds
            )
            db.add(db_tool)
    await db.commit()

    return result
