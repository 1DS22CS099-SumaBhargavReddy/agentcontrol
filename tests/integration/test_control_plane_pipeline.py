"""
End-to-End Integration Tests for AgentControl Pipeline
Tests the complete flow: Permission -> Policy -> Risk -> Approval -> Sandbox Execution -> Audit Trail
"""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.db.session import init_db
from apps.api.main import app, seed_initial_demo_data


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()
    await seed_initial_demo_data()


@pytest.mark.asyncio
async def test_low_risk_tool_auto_executes():
    """Read queries should pass through without requiring human approval."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/tool-calls/execute", json={
            "agent_id": "production-incident-agent",
            "environment": "production",
            "tool_name": "database.read_query",
            "arguments": {"query": "SELECT * FROM metrics LIMIT 5"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved_and_executed"
        assert data["risk_level"] == "low"
        assert data["execution_result"] is not None


@pytest.mark.asyncio
async def test_high_risk_tool_requires_approval_and_resumes():
    """Destructive operations in production must pause for human approval, then resume upon sign-off."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Propose destructive action
        resp = await ac.post("/tool-calls/execute", json={
            "agent_id": "production-incident-agent",
            "environment": "production",
            "tool_name": "kubernetes.restart_pod",
            "arguments": {"namespace": "production", "pod": "auth-service-789"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approval_required"
        assert data["risk_score"] >= 0.50
        approval_id = data["approval_id"]
        assert approval_id is not None

        # 2. Check pending approvals queue
        appr_list_resp = await ac.get("/approvals?status_filter=pending")
        assert appr_list_resp.status_code == 200
        pending = appr_list_resp.json()
        assert any(item["id"] == approval_id for item in pending)

        # 3. Human approver approves
        approve_resp = await ac.post(f"/approvals/{approval_id}/approve", json={
            "reason": "Authorized by Senior SRE on-call"
        })
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # 4. Resume execution
        resume_resp = await ac.post(f"/tool-calls/{approval_id}/resume")
        assert resume_resp.status_code == 200
        res_data = resume_resp.json()
        assert res_data["status"] == "approved_and_executed"
        assert res_data["execution_result"]["status"] == "restarted"

        # 5. Check Audit Log & Chain Integrity
        audit_resp = await ac.get("/audit?limit=10")
        assert audit_resp.status_code == 200
        events = audit_resp.json()
        assert len(events) >= 3

        verify_resp = await ac.get("/audit/verify")
        assert verify_resp.status_code == 200
        assert verify_resp.json()["verified"] is True
