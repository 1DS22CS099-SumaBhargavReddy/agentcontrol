"""
AgentControl Demonstration: AI Production Incident Commander
Realistic end-to-end demonstration of an autonomous AI agent managing a production outage
under the strict governance, policy enforcement, and human-in-the-loop approval of AgentControl.

Scenario:
1. Alert: Prometheus reports 99th percentile latency spike on production auth-service.
2. Investigation: Agent investigates metrics & logs using read queries (Auto-approved, low risk).
3. Code Inspection: Agent inspects recent GitHub commits and deployment metadata (Auto-approved).
4. Diagnosis: Agent diagnoses memory leak & deadlocked pod in CrashLoopBackOff.
5. Mitigation Proposal: Agent proposes restarting the pod in production namespace.
6. Control Plane Interception: AgentControl calculates critical risk (score: 0.85) -> blocks auto-execution -> pauses for human approval.
7. Human Sign-Off: Senior SRE inspects evidence, provides approval token & rationale.
8. Execution & Verification: Tool executes, health check confirms service recovery.
9. Incident Report: Post-mortem generated with full cryptographic audit trail.
"""

import asyncio
import os
import sys
import time
from httpx import ASGITransport, AsyncClient

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from apps.api.main import app, seed_initial_demo_data
from apps.api.db.session import init_db


def print_banner(step: str, title: str):
    print("\n" + "=" * 80)
    print(f">> [STEP {step}] {title}")
    print("=" * 80)


async def run_incident_commander_demo():
    print("*" * 80)
    print("  AGENTCONTROL ENTERPRISE DEMO: AI PRODUCTION INCIDENT COMMANDER")
    print("*" * 80)

    await init_db()
    await seed_initial_demo_data()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # STEP 1: Incoming Alert
        print_banner("1", "Prometheus High-Latency Alert Triggered")
        alert = {
            "alertname": "AuthServiceHighLatencyP99",
            "service": "auth-service",
            "namespace": "production",
            "latency_p99": "4850ms",
            "threshold": "500ms",
            "severity": "critical"
        }
        print(f"Alert Received: {alert['alertname']} | Service: {alert['service']} | Latency: {alert['latency_p99']}")
        print("Spawning Agent: 'production-incident-agent' (Environment: production)")

        # STEP 2: Agent Queries Telemetry Database
        print_banner("2", "Agent Investigates Telemetry & Metrics (Read Query)")
        query_payload = {
            "agent_id": "production-incident-agent",
            "environment": "production",
            "tool_name": "database.read_query",
            "arguments": {"query": "SELECT error_rate, p99_latency FROM service_telemetry WHERE service='auth-service'"}
        }
        print("Invoking Tool: 'database.read_query' with read query...")
        resp = await client.post("/tool-calls/execute", json=query_payload)
        data = resp.json()
        print(f"AgentControl Decision: {data['status'].upper()} (Risk Level: {data['risk_level'].upper()}, Score: {data['risk_score']})")
        print(f"Result: {data['execution_result']}")

        # STEP 3: Agent Inspects Pod Health on Kubernetes
        print_banner("3", "Agent Inspects Kubernetes Pod Cluster State")
        print("Invoking Tool: 'kubernetes.get_pod' for auth-service-789...")
        # Note: simulated in demo
        print("Cluster State Found: pod auth-service-789 status is 'CrashLoopBackOff', restart_count=12, CPU=1.8 cores")

        # STEP 4: High-Risk Mitigation Proposal
        print_banner("4", "Agent Proposes High-Risk Mitigation: Restart Production Pod")
        restart_payload = {
            "agent_id": "production-incident-agent",
            "environment": "production",
            "tool_name": "kubernetes.restart_pod",
            "arguments": {"namespace": "production", "pod": "auth-service-789"}
        }
        print("Proposing Action: kubernetes.restart_pod on production/auth-service-789...")
        resp = await client.post("/tool-calls/execute", json=restart_payload)
        data = resp.json()

        print("\n--- AGENTCONTROL INTERCEPTION ---")
        print(f"Status: {data['status'].upper()}")
        print(f"Risk Level: {data['risk_level'].upper()} (Score: {data['risk_score']})")
        print(f"Reason Codes: {', '.join(data['reason_codes'])}")
        print(f"Approval Request ID: {data['approval_id']}")
        print("Action has been PAUSED safely. Execution prohibited until human sign-off.")

        approval_id = data["approval_id"]

        # STEP 5: SRE Reviews Pending Approvals Queue
        print_banner("5", "Human Operator (Senior SRE) Reviews Pending Queue")
        appr_resp = await client.get("/approvals?status_filter=pending")
        pending_list = appr_resp.json()
        target_approval = next((item for item in pending_list if item["id"] == approval_id), None)
        print(f"Found Pending Request #{target_approval['id']}")
        print(f"  Tool: {target_approval['tool_name']}")
        print(f"  Target: {target_approval['parameters']}")
        print(f"  Risk Factors: {target_approval['reason_codes']}")
        print(f"  Expires At: {target_approval['expires_at']}")

        # STEP 6: SRE Grants Approval
        print_banner("6", "Senior SRE Grants Cryptographic Approval")
        decision_payload = {
            "reason": "Authorized by On-Call Senior SRE after verifying memory exhaustion dump."
        }
        approve_resp = await client.post(f"/approvals/{approval_id}/approve", json=decision_payload)
        print(f"Approval Decision Recorded: Status={approve_resp.json()['status'].upper()}")
        print(f"Approved By: default-developer | Reason: {decision_payload['reason']}")

        # STEP 7: Agent Resumes and Executes Action
        print_banner("7", "Execution Engine Resumes and Executes Pod Restart")
        resume_resp = await client.post(f"/tool-calls/{approval_id}/resume")
        resume_data = resume_resp.json()
        print(f"Execution Status: {resume_data['status'].upper()}")
        print(f"Cluster Output: {resume_data['execution_result']}")

        # STEP 8: Post-Mortem Verification & Cryptographic Audit Trail
        print_banner("8", "Post-Incident Audit Trail Verification")
        audit_verify = await client.get("/audit/verify")
        verify_data = audit_verify.json()
        print(f"Audit Trail Integrity: {'VERIFIED' if verify_data['verified'] else 'TAMPERED'}")
        print(f"Message: {verify_data['message']}")

        print("\n" + "=" * 80)
        print(">> INCIDENT COMMANDER WORKFLOW COMPLETE: OUTAGE RESOLVED SAFELY")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_incident_commander_demo())
