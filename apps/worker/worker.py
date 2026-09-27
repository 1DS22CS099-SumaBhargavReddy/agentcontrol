"""
AgentControl Background Worker
Handles asynchronous tasks: approval expiration sweeper, webhook dispatching, and audit telemetry archiving.
"""

import asyncio
from datetime import datetime, timezone
import logging
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from sqlalchemy import select, update
from apps.api.db.session import AsyncSessionLocal, init_db
from apps.api.db.models import ApprovalRequest, ToolCall
from apps.api.audit.service import AuditLogger

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agentcontrol.worker")


async def sweep_expired_approvals():
    """Finds pending approvals past their expiration time and marks them expired."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at < now
        )
        res = await db.execute(stmt)
        expired_reqs = res.scalars().all()

        for req in expired_reqs:
            logger.info(f"Expiring approval request {req.id} for agent {req.agent_id} (tool: {req.tool_name})")
            req.status = "expired"
            req.updated_at = now

            # Update associated tool call
            tc_stmt = select(ToolCall).where(ToolCall.id == req.tool_call_id)
            tc = (await db.execute(tc_stmt)).scalar_one_or_none()
            if tc:
                tc.status = "expired"

            # Record audit event
            await AuditLogger.log_event(
                db=db,
                agent_id=req.agent_id,
                action="approval.expired",
                tool_name=req.tool_name,
                risk_level=req.risk_level,
                approval_status="expired",
                payload={"approval_id": req.id, "expired_at": now.isoformat()}
            )

        if expired_reqs:
            await db.commit()
            logger.info(f"Successfully expired {len(expired_reqs)} approval requests.")


async def run_worker_loop(interval_seconds: float = 10.0, run_once: bool = False):
    logger.info("Starting AgentControl Background Worker...")
    await init_db()

    while True:
        try:
            await sweep_expired_approvals()
        except Exception as e:
            logger.error(f"Error in worker sweep loop: {e}", exc_info=True)

        if run_once:
            break
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
