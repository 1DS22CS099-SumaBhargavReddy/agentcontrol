"""
AgentControl: Production Control Plane for AI Agents
FastAPI Core Backend Application
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from apps.api.db.models import Agent, Permission, Policy, Tool
from apps.api.db.session import AsyncSessionLocal, init_db
from apps.api.routers import (
    agents,
    approvals,
    audit,
    evaluations,
    executions,
    mcp,
    permissions,
    policies,
    risk_decisions,
    security,
    tools,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentcontrol")


async def seed_initial_demo_data():
    """Seeds baseline agents, tools, policies, and permissions for instant usability."""
    async with AsyncSessionLocal() as db:
        # 1. Seed demo agent
        stmt = select(Agent).where(Agent.name == "production-incident-agent")
        existing_agent = (await db.execute(stmt)).scalar_one_or_none()
        if not existing_agent:
            agent = Agent(
                name="production-incident-agent",
                description="Autonomous SRE incident investigation and remediation agent",
                owner="platform-sre",
                environment="production",
                version="1.0.0",
                capabilities=["kubernetes:read", "kubernetes:restart", "github:create_pr", "database:read"],
                status="active"
            )
            db.add(agent)

        # 2. Seed tools
        demo_tools = [
            Tool(
                name="kubernetes.restart_pod",
                description="Restart an unstable pod in the Kubernetes cluster",
                risk_level="critical",
                tags=["destructive", "kubernetes", "infrastructure"],
                parameters_schema={"type": "object", "properties": {"namespace": {"type": "string"}, "pod": {"type": "string"}}, "required": ["namespace", "pod"]}
            ),
            Tool(
                name="github.create_pr",
                description="Create an emergency hotfix PR on GitHub",
                risk_level="medium",
                tags=["github", "write"],
                parameters_schema={"type": "object", "properties": {"repo": {"type": "string"}, "title": {"type": "string"}, "head": {"type": "string"}, "base": {"type": "string"}}}
            ),
            Tool(
                name="database.read_query",
                description="Execute read-only query for telemetry analysis",
                risk_level="low",
                tags=["database", "read"],
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
            ),
            Tool(
                name="browser.fetch_url",
                description="Safely fetch external documentation or runbooks",
                risk_level="medium",
                tags=["web", "browser", "network"],
                parameters_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
            )
        ]
        for t in demo_tools:
            stmt = select(Tool).where(Tool.name == t.name)
            if not (await db.execute(stmt)).scalar_one_or_none():
                db.add(t)

        # 3. Seed baseline permissions for production-incident-agent
        perms = [
            Permission(
                agent_id="production-incident-agent",
                environment="production",
                service="kubernetes",
                resource="*",
                action="restart*",
                effect="allow",
                description="Allow restart of non-system pods"
            ),
            Permission(
                agent_id="production-incident-agent",
                environment="production",
                service="github",
                resource="*",
                action="create_pr",
                effect="allow"
            ),
            Permission(
                agent_id="production-incident-agent",
                environment="production",
                service="database",
                resource="*",
                action="read_query",
                effect="allow"
            ),
            Permission(
                agent_id="production-incident-agent",
                environment="production",
                service="browser",
                resource="*",
                action="fetch_url",
                effect="allow"
            ),
        ]
        for p in perms:
            p_stmt = select(Permission).where(
                Permission.agent_id == p.agent_id,
                Permission.service == p.service,
                Permission.action == p.action
            )
            if not (await db.execute(p_stmt)).scalar_one_or_none():
                db.add(p)

        # 4. Seed baseline declarative policy
        pol_yaml = """
version: "1.0.0"
policies:
  production:
    destructive_operations:
      require_human_approval: true
    kubernetes:
      restart_pod:
        allowed: true
        require_human_approval: true
        reason: "Restarting production pods requires SRE human approval"
    database:
      drop_table:
        allowed: false
        reason: "Direct drop table is strictly forbidden in production"
      read_query:
        allowed: true
        require_human_approval: false
        constraints:
          argument_patterns:
            query: '^(?i:\\s*(SELECT|EXPLAIN|SHOW|DESCRIBE|WITH)\\b).*$'
  development:
    destructive_operations:
      require_human_approval: false
"""
        pol_stmt = select(Policy).where(Policy.environment == "production", Policy.is_active == True)
        existing_pol = (await db.execute(pol_stmt)).scalar_one_or_none()
        if existing_pol:
            existing_pol.raw_yaml = pol_yaml
        else:
            db.add(Policy(environment="production", version="1.0.0", raw_yaml=pol_yaml, is_active=True))

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing AgentControl Database & Tables...")
    await init_db()
    logger.info("Seeding baseline demo assets...")
    await seed_initial_demo_data()
    logger.info("AgentControl Control Plane Ready.")
    yield
    # Shutdown
    logger.info("Shutting down AgentControl Control Plane.")


app = FastAPI(
    title="AgentControl API",
    description="The Open-Source Control Plane for Production AI Agents",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS configuration for React Dashboard & external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(agents.router)
app.include_router(tools.router)
app.include_router(permissions.router)
app.include_router(policies.router)
app.include_router(risk_decisions.router)
app.include_router(approvals.router)
app.include_router(executions.router)
app.include_router(evaluations.router)
app.include_router(audit.router)
app.include_router(security.router)
app.include_router(mcp.router)


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to AgentControl: Open-Source Zero-Trust Control Plane for AI Agents",
        "version": "1.0.0",
        "docs_url": "/docs",
        "dashboard_url": "http://localhost:3000",
        "health_check": "/health"
    }


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "agentcontrol-control-plane",
        "version": "0.1.0",
        "features": {
            "mcp": True,
            "opentelemetry": True,
            "browser_scan": True,
            "prompt_injection_defense": True,
            "human_in_the_loop": True,
            "clerk_oauth_auth": True,
            "supabase_postgres": True
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
