# AgentControl

<div align="center">

**Open-Source Zero-Trust Control Plane for Production AI Agents**

[![CI/CD](https://github.com/agentcontrol/agentcontrol/actions/workflows/ci.yml/badge.svg)](https://github.com/agentcontrol/agentcontrol/actions)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-GenAI%20Semantic%20Conventions-purple.svg)](https://opentelemetry.io)
[![MCP Compatible](https://img.shields.io/badge/MCP-Protocol%20Ready-orange.svg)](https://modelcontextprotocol.io)

[Architecture](#-core-architecture) •
[Quickstart](#-quickstart-in-60-seconds) •
[Python SDK](#-python-sdk) •
[Integrations](#-integrations) •
[Incident Commander Demo](#-production-incident-commander-demo) •
[Dashboard](#-control-dashboard)

</div>

---

## ⚡ The Problem

Modern organizations are rapidly deploying AI agents that can reason, invoke tools, modify code, query databases, and execute cloud actions. However, deploying autonomous agents directly against production infrastructure exposes companies to critical risks:

* **No fine-grained permissions**: LLMs are often given broad credentials (AWS keys, GitHub tokens, database connections).
* **No declarative policies**: Security rules are either scattered in prompt instructions (which can be jailbroken) or ad-hoc in application code.
* **No dynamic risk evaluation**: Running `SELECT *` and running `DELETE FROM users` or `kubectl delete pod` are treated with identical trust.
* **Lack of asynchronous human-in-the-loop**: Destructive actions cannot safely pause and await human operator sign-off without breaking agent state.
* **Vulnerability to prompt injection & SSRF**: External inputs (web pages, GitHub issues, emails) can hijack agent tool execution.
* **Absence of forensic auditability**: LLM logs lack cryptographic immutability needed for regulatory compliance (SOC2, ISO 27001, HIPAA).

**AgentControl** solves this by sitting as an independent zero-trust proxy between AI agents and the real-world tools they execute.

---

## 🏛 Core Architecture

```text
                           USER / EVENT / LLM
                                   │
                                   ▼
                            AI AGENT RUNTIME
                (LangGraph / OpenAI SDK / Custom Agent)
                                   │
                         Tool Execution Request
                                   ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                      AGENTCONTROL API                       │
        │                  (FastAPI / Pydantic v2)                    │
        ├─────────────────────────────────────────────────────────────┤
        │  [Auth Layer]: API Keys (SHA-256) & OAuth2 / Bearer JWT     │
        │  [Security Guard]: Prompt Injection & Browser SSRF Scanner  │
        │  [Cost Controller]: Token Budgeting & Model Router          │
        └──────────────────────────────┬──────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                     ZERO-TRUST PIPELINE                     │
        ├─────────────────────────────────────────────────────────────┤
        │  Stage 1: Tool & Agent Registry Lookup                      │
        │  Stage 2: Permission Engine (RBAC, Scopes, Environment)     │
        │  Stage 3: Policy Engine (Declarative YAML, Regex AST)       │
        │  Stage 4: Risk Engine (Multi-Factor Deterministic Scoring)  │
        │  Stage 5: Decision Layer (Allow / Reject / Human Review)    │
        └──────────────────────────────┬──────────────────────────────┘
                                       │
               ┌───────────────────────┴───────────────────────┐
               │ Requires Approval?                            │
               ▼                                               ▼
       [YES: Risk >= 0.50]                           [NO: Safe Action]
               │                                               │
               ▼                                               │
        ┌─────────────────────────────┐                        │
        │    HUMAN APPROVAL ENGINE    │                        │
        │  - Pending queue generated  │                        │
        │  - Operator reviews reason  │                        │
        │  - Cryptographic sign-off   │                        │
        └──────────────┬──────────────┘                        │
                       │ Approved                              │
                       ▼                                       │
        ┌──────────────────────────────────────────────────────┴──────┐
        │                   ACTION EXECUTION ENGINE                   │
        │  - Sandboxed Runner (Docker / Subprocess / HTTP / MCP)      │
        │  - Timeouts, Idempotency Keys & Rollback Registry           │
        └──────────────────────────────┬──────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                    AUDIT & OBSERVABILITY                    │
        ├─────────────────────────────────────────────────────────────┤
        │  - OpenTelemetry Trace & Span Generation (gen_ai.* specs)   │
        │  - Append-Only Tamper-Resistant Audit Trail (SHA-256 Chain) │
        │  - Real-time React + TypeScript Control Dashboard           │
        └─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart in 60 Seconds

### Option 1: Docker Compose

Spin up the complete stack (PostgreSQL, Redis, AgentControl API, Background Worker, and Dashboard):

```bash
git clone https://github.com/agentcontrol/agentcontrol.git
cd agentcontrol
docker compose -f deploy/docker/docker-compose.yml up -d
```

* **Control Plane API**: `http://localhost:8000`
* **Swagger API Docs**: `http://localhost:8000/docs`
* **React Control Dashboard**: `http://localhost:3000`

### Option 2: Local Python Setup

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -e .

# 3. Start the AgentControl API
uvicorn apps.api.main:app --reload --port 8000
```

---

## 🐍 Python SDK

Integrate AgentControl into any AI agent in 4 lines of code:

```python
from packages.sdk.client import AgentControl

# Initialize SDK
control = AgentControl(endpoint="http://localhost:8000")

# Create scoped agent client
agent = control.agent(name="incident-commander", environment="production")

# Execute tool through the zero-trust pipeline
result = await agent.execute_tool(
    tool_name="kubernetes.restart_pod",
    arguments={"namespace": "production", "pod": "auth-service-789"}
)

print(f"Status: {result.status}")
print(f"Risk Score: {result.risk_score} ({result.risk_level})")
print(f"Execution Output: {result.execution_result}")
```

---

## 🧩 Integrations

AgentControl is framework and model agnostic:

### 1. LangGraph Middleware
Intercept agent tool calls within LangGraph state machines:

```python
from integrations.langgraph import AgentControlToolNode
from packages.sdk.client import AgentControl

control = AgentControl()
tool_node = AgentControlToolNode(
    control=control,
    agent_id="my-langgraph-agent",
    environment="production"
)
```

### 2. Model Context Protocol (MCP) Gateway
Discovered MCP tools default to zero-trust permissions and strict policy gating:

```python
from integrations.mcp.gateway import MCPGateway
from packages.tool_runtime.runtime import ToolRuntimeEngine

runtime = ToolRuntimeEngine()
gateway = MCPGateway(runtime_engine=runtime)

# Ingest and gate tools from any external MCP server
discovery = await gateway.discover_and_register_tools("http://localhost:8080/mcp")
```

### 3. OpenAI Agents SDK Adapter
Wrap standard function schemas with control plane policies:

```python
from integrations.openai import OpenAIControlledTool

controlled_tool = OpenAIControlledTool(
    control=control,
    name="database.read_query",
    description="Run read-only analytics queries",
    parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    agent_id="reporting-agent"
)

# Pass directly to client.chat.completions.create(tools=[controlled_tool.to_openai_tool()])
```

---

## 🚨 Production Incident Commander Demo

Experience the full enterprise workflow in action:

```bash
python examples/incident_commander/incident_commander.py
```

### Demonstration Walkthrough:
1. **Prometheus Alert**: Spikes latency P99 on `auth-service`.
2. **Investigation**: Agent inspects telemetry via `database.read_query` (Risk: Low -> **Auto-executed**).
3. **Pod State Check**: Cluster reports pod in `CrashLoopBackOff`.
4. **Mitigation Proposal**: Agent proposes `kubernetes.restart_pod` in production.
5. **Control Plane Interception**: Risk Engine scores **1.0 (Critical)** -> **Halts execution and creates Approval Request**.
6. **SRE Sign-Off**: Operator reviews rationale and signs off via API/Dashboard.
7. **Resumed Execution**: Sandbox executes restart, service health recovers.
8. **Forensic Audit**: SHA-256 hash-chain verified across all audit records.

---

## 🖥 Control Dashboard

The React + TypeScript dashboard provides real-time visibility and management:

* **Overview**: Real-time KPI counters (Active Agents, Blocked Actions, Approvals, Spend).
* **Agents Registry**: Catalog of authorized agents, environments, and capability sets.
* **Runs & Traces**: OpenTelemetry distributed waterfall traces.
* **Tool Calls Ledger**: Detailed parameter inspector and risk reason codes.
* **Approvals Inbox**: One-click human sign-off with timeout countdowns.
* **Declarative Policy Editor**: Live YAML policy editing and validation.
* **Evaluations**: Objective metrics for safety, tool precision, and regressions.
* **Audit Trail**: Searchable cryptographic ledger with one-click chain verification.

To run the dashboard locally:
```bash
cd apps/dashboard
npm install
npm run dev
```

---

## 🧪 Testing & Benchmarks

Run the complete test suite:

```bash
# Run 38+ unit, integration, and security tests
pytest -v

# Run core evaluation benchmarks (100% Pass target)
python benchmarks/run_benchmarks.py
```

---

## 🔒 Security & Forensic Auditability

Every sensitive event is appended to a cryptographic hash chain:

$$\text{Hash}_n = \text{SHA-256}(\text{Timestamp} \parallel \text{AgentID} \parallel \text{Action} \parallel \text{Payload} \parallel \text{Hash}_{n-1})$$

Any retroactive alteration of logs or historical tool executions invalidates the entire chain, guaranteeing forensic integrity for enterprise audits.

---

## 📄 License

AgentControl is open-source software licensed under the [Apache-2.0 License](LICENSE).
