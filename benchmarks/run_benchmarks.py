"""
AgentControl Benchmark Evaluation Runner
Executes structured security, policy, risk, and approval benchmarks against the control plane.
"""

import asyncio
import json
import os
import sys
import time
from httpx import ASGITransport, AsyncClient

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.main import app, seed_initial_demo_data
from apps.api.db.session import init_db


async def run_benchmark_suite():
    print("=" * 70)
    print(">> Running AgentControl Core Control Plane Benchmark Suite")
    print("=" * 70)

    await init_db()
    await seed_initial_demo_data()

    scenarios_path = os.path.join(os.path.dirname(__file__), "scenarios.json")
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    transport = ASGITransport(app=app)
    results = []

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for s in scenarios:
            scenario_id = s["id"]
            name = s["name"]
            category = s["category"]

            start_t = time.perf_counter()
            resp = await client.post("/tool-calls/execute", json={
                "agent_id": s["agent_id"],
                "environment": s["environment"],
                "tool_name": s["tool_name"],
                "arguments": s["arguments"]
            })
            duration_ms = round((time.perf_counter() - start_t) * 1000.0, 2)

            data = resp.json()
            actual_status = data.get("status")
            actual_risk = data.get("risk_level")

            status_match = (actual_status == s["expected_status"])
            passed = status_match

            results.append({
                "id": scenario_id,
                "name": name,
                "category": category,
                "expected_status": s["expected_status"],
                "actual_status": actual_status,
                "risk_level": actual_risk,
                "duration_ms": duration_ms,
                "passed": passed
            })

            status_icon = "PASS" if passed else "FAIL"
            print(f"[{status_icon}] {scenario_id} - {name} ({duration_ms}ms)")
            print(f"       Expected: {s['expected_status']} | Got: {actual_status} | Risk: {actual_risk}")

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    pass_rate = (passed_count / total) * 100.0

    print("=" * 70)
    print(f"Benchmark Results Summary: {passed_count}/{total} Passed ({pass_rate:.1f}%)")
    print("=" * 70)

    return results, pass_rate


if __name__ == "__main__":
    results, pass_rate = asyncio.run(run_benchmark_suite())
    if pass_rate < 100.0:
        sys.exit(1)
