# AgentControl: Production Control Plane for AI Agents
## System Architecture, Ecosystem Analysis & Implementation Roadmap

---

## 1. Executive Summary & Ecosystem Analysis

In modern enterprise architectures, AI agents are evolving from conversational chatbots into autonomous actors with tool-calling capabilities (interacting with GitHub, AWS, Kubernetes, corporate databases, payment APIs, and SaaS systems). However, existing tooling presents a dangerous architectural gap:

```
┌─────────────────┐       DIRECT TOOL CALL       ┌──────────────────────┐
│  AI Agent / LLM │  ─────────────────────────►  │ Real-World Systems   │
│  (Non-deterministic)                           │ (k8s, AWS, DBs, Git) │
└─────────────────┘                              └──────────────────────┘
      ▲                                                     ▲
      │                 DANGEROUS MISSING LAYER:             │
      │  ❌ No Fine-grained Permissions                     │
      │  ❌ No Declarative Policies (Env-aware)             │
      │  ❌ No Dynamic Risk Assessment                      │
      │  ❌ No Human-in-the-loop Gating                     │
      │  ❌ No Browser / Prompt Injection Sanitization      │
      │  ❌ No Unified OpenTelemetry / Audit Trail          │
```

### 1.1 Comparison with Existing Ecosystem

| Category | Projects | Limitations for Production Agent Tool Gating | AgentControl Differentiation |
|---|---|---|---|
| **LLM Observability** | Langfuse, Phoenix (Arize), Traceloop | Passive telemetry and evals. They observe what happened after the fact, but cannot intercept, evaluate policies, or block high-risk actions. | **Active Zero-Trust Proxy**: Intercepts actions *before* execution; can pause, demand human sign-off, or reject. Fully exports OpenTelemetry traces to any OTel collector. |
| **Guardrails & Text Filters** | NeMo Guardrails, Guardrails AI, Llama Guard | Focus on text moderation, hallucination detection, and prompt-level constraints. Lack action-level authorization, environment awareness, and tool execution engines. | **System-Level Control Plane**: Deals with structured tool payloads, credentials, cloud environments, idempotent rollback, and multi-tenant RBAC. |
| **General Policy Engines** | Open Policy Agent (OPA), AWS Cedar | Powerful declarative languages (Rego), but lack agentic context: no concept of agent trajectories, token budgets, prompt injection scanning, or asynchronous human approvals. | **Agent-Native Policy Engine**: Rules operate directly on agent ID, risk scores, tool arguments, cost budgets, and execution environments with deterministic and hybrid AI fallbacks. |
| **Tool Protocols** | Anthropic Model Context Protocol (MCP) | MCP standardizes tool discovery and execution over JSON-RPC, but explicitly delegates security, permissioning, and risk evaluation to the host client. Discovered tools default to client trust. | **Managed MCP Gateway**: Discovers MCP tools dynamically, registers them with strict zero-trust default permissions, enforces policy gating before forwarding execution. |
| **Agent Frameworks** | LangGraph, CrewAI, AutoGen, OpenAI Agents SDK | Framework-specific runtime logic. Embedding security rules inside agent code couples policies to the application and prevents central security governance. | **Framework Agnostic**: Sits as an independent control plane accessible via standard Python SDK, REST API, or MCP proxy. |

---

## 2. Core Architectural Design

AgentControl is structured into an event-driven, decoupled zero-trust architecture:

```
                           AI Agent / Framework
               (LangGraph, OpenAI SDK, Custom Agent, MCP Client)
                                     │
                        1. Tool Execution Request
                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │                      AGENTCONTROL API                       │
      │                (FastAPI / Pydantic v2 / Async)              │
      ├─────────────────────────────────────────────────────────────┤
      │  [Auth Layer]: Clerk JWT / OAuth2 / API Keys (SHA-256)      │
      │  [Security Guard]: Prompt Injection & Browser URL Scanner   │
      │  [Cost Limiter]: Token & Dollar Budget Enforcement          │
      └──────────────────────────────┬──────────────────────────────┘
                                     │
                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │                   ZERO-TRUST PIPELINE                       │
      ├─────────────────────────────────────────────────────────────┤
      │  Stage 1: Tool & Agent Registry Lookup                      │
      │  Stage 2: Permission Engine (RBAC, Scopes, Environment)     │
      │  Stage 3: Policy Engine (Declarative Rules, AST Matcher)    │
      │  Stage 4: Risk Engine (Deterministic Scoring + Reasons)     │
      │  Stage 5: Decision Layer (Allow / Deny / Human Review)      │
      └──────────────────────────────┬──────────────────────────────┘
                                     │
             ┌───────────────────────┴───────────────────────┐
             │ Requires Approval?                            │
             ▼                                               ▼
     [YES: Risk >= Threshold]                     [NO: Risk < Threshold]
             │                                               │
             ▼                                               │
      ┌─────────────────────────────┐                        │
      │   HUMAN APPROVAL ENGINE     │                        │
      │  - Creates Pending Request  │                        │
      │  - Webhook / SSE / Dashboard│                        │
      │  - Awaits cryptographic sign│                        │
      │  - Auto-expiry & timeouts   │                        │
      └──────────────┬──────────────┘                        │
                     │ Approved                              │
                     ▼                                       │
      ┌──────────────────────────────────────────────────────┴──────┐
      │                    ACTION EXECUTION ENGINE                  │
      │  - Sandboxed Runner (Docker / Subprocess / HTTP / MCP)     │
      │  - Timeouts, Exponential Backoff, Idempotency Keys         │
      │  - Rollback hook registry                                   │
      │  - Output Sanitizer & Injection Scanner                     │
      └──────────────────────────────┬──────────────────────────────┘
                                     │
                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │                    AUDIT & OBSERVABILITY                    │
      ├─────────────────────────────────────────────────────────────┤
      │  - OpenTelemetry Trace & Span Generation (gen_ai.* specs)   │
      │  - Append-Only Tamper-Resistant Audit Log                   │
      │  - PostgreSQL / Supabase Storage with asyncpg & RLS         │
      │  - Real-Time WebSockets to React Control Dashboard          │
      └─────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack & Integration Choices

1. **Database & Storage**:
   - **PostgreSQL / Supabase**: Native async PostgreSQL with SQLAlchemy 2.0 (asyncio) + asyncpg. Structured relational tables with JSONB only for tool argument schemas and raw telemetry. Compatible with Supabase (RLS policies, Supabase Auth tokens).
2. **Backend API**:
   - **FastAPI + Pydantic v2**: High-throughput async REST API with OpenAPI documentation, WebSockets for live approval feeds and agent execution streaming.
3. **Authentication & Identity**:
   - **Multi-tenant Auth**:
     - API Key with secure SHA-256 hashing and prefix indexing (`acp_live_...`).
     - OAuth2 / JWT (Clerk JWKS integration, Supabase Auth JWT verification, RFC 7519 compliant).
4. **Agent & Tool Interoperability**:
   - **Anthropic Model Context Protocol (MCP)**: Native client and server bridge.
   - **OpenTelemetry GenAI Semantic Conventions**: Standardized attributes (`gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.agent.id`, `gen_ai.risk.score`).
5. **Security Scanning**:
   - **Prompt Injection Defense**: Multi-tier heuristics, regex delimiters, and untrusted payload isolation.
   - **Browser & URL Scanner**: SSRF protection, private IP blocklists (RFC 1918/4193), safe scheme validation, and suspicious payload detection for web browsing tools.
6. **Frontend Dashboard**:
   - **React 18 + TypeScript + Vite**: Modern, dark glassmorphic responsive interface with Tailwind CSS, Lucide icons, real-time live runs, approvals queue, policy editor, and audit explorer.

---

## 4. Phased Implementation Roadmap

- **Phase 1: Architecture, Monorepo Setup & Workspace Foundations**
  - Project directory structure (`apps/api`, `apps/dashboard`, `apps/worker`, `packages/*`, `integrations/*`, `deploy/*`).
  - Python virtual environment, dependencies configuration, pre-commit, Ruff, Pytest.
- **Phase 2: Database Schema, Models & Migrations (PostgreSQL / Supabase)**
  - SQLAlchemy 2.0 Async models: `agents`, `tools`, `permissions`, `policies`, `agent_runs`, `tool_calls`, `risk_assessments`, `approval_requests`, `audit_events`, `cost_budgets`.
  - Migration scripts, seed fixtures, connection pooling with health check.
- **Phase 3: Agent & Tool Registry Core**
  - CRUD & registration API for agents and tools. Versioning, schema validation with JSON Schema, capability definitions.
- **Phase 4: Fine-Grained Permission Engine**
  - Role-based and attribute-based access control (RBAC/ABAC). Scoped environment permissions (production, staging, development), resource wildcards, explicit deny precedence.
- **Phase 5: Declarative Policy Engine**
  - YAML-defined environment policies, condition evaluator, constraint rules (destructive operations, restricted arguments, parameter whitelists).
- **Phase 6: Action-Risk Engine**
  - Multi-factor deterministic risk calculation: environment multiplier, tool inherent risk, argument sensitivity, blast radius. Return risk score [0.0 - 1.0], risk levels, reason codes.
- **Phase 7: Decision Layer & Hybrid Fallbacks**
  - Abstraction for rule-based decisions, fallback providers, and hybrid classification.
- **Phase 8: Human-in-the-Loop Approval System**
  - Pending approval state machine, expiration timers, approval tokens, webhook notification handlers, audit evidence capture.
- **Phase 9: Action Execution Engine & Sandbox**
  - Sandboxed execution, timeout handlers, idempotency tracking, retry policies, rollback hooks.
- **Phase 10: Model Context Protocol (MCP) Integration**
  - MCP client connector, dynamic tool ingestion, zero-trust permission binding.
- **Phase 11: OpenTelemetry Instrumentation**
  - Full trace generation following `gen_ai.*` semantic conventions. In-memory / OTLP exporter integration.
- **Phase 12: Evaluation & Benchmarking Framework**
  - Evaluation harness: task success, policy compliance, safety scores, latency & token cost calculations.
- **Phase 13: Browser Scan, Prompt Injection & Security Hardening**
  - SSRF filter, private network blocklist, prompt injection heuristics, safe payload tagging.
- **Phase 14: React + TypeScript Control Dashboard**
  - Real-time management UI: Overview metrics, Agent catalog, Live trace explorer, Pending Approvals Inbox, Policy Editor, Audit Trail.
- **Phase 15: Python SDK**
  - Developer-friendly async client: `@control.tool`, `agent.execute_tool()`, automatic OTel context propagation, LangGraph & OpenAI SDK adapters.
- **Phase 16: End-to-End AI Production Incident Commander Demo**
  - Realistic multi-step incident scenario: Prometheus alert -> log inspection -> root-cause diagnosis -> high-risk pod restart -> approval request -> human sign-off -> rollback & verification.
- **Phase 17: Production Deployment & Open-Source Distribution**
  - Docker Compose, Kubernetes manifests, Helm chart, CI/CD GitHub Actions workflows, comprehensive documentation (`README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`).

---
