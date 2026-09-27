# Changelog

All notable changes to the **AgentControl** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-09-27

### Added
- **Core Architecture**:
  - Zero-Trust Control Plane pipeline intercepting all AI agent actions.
  - Multi-tenant authentication layer supporting SHA-256 API keys and JWT Bearer tokens.
  - Asynchronous high-throughput REST API with FastAPI and Pydantic v2.
  - Relational persistence with SQLAlchemy 2.0 Async (PostgreSQL / Supabase + SQLite development fallback).
- **Security & Guardrails**:
  - Prompt Injection Scanner with regex heuristics, delimiter jailbreak detection, and suspicious pattern tagging.
  - Browser & URL SSRF Protection blocking private IP spaces (RFC 1918, RFC 4193, cloud metadata 169.254.169.254).
- **Engines**:
  - **Permission Engine**: Fine-grained RBAC and ABAC with service/resource wildcard matching and explicit deny precedence.
  - **Policy Engine**: Declarative YAML-based environment policies with argument regex pattern validation and destructive operation controls.
  - **Risk Engine**: Deterministic multi-factor scoring combining environment baseline, inherent tool risk, keyword heuristics, sensitive target inspection, and blast radius calculation.
  - **Decision Layer**: Hybrid rule-based and provider-agnostic decision abstraction with deterministic rule overrides.
  - **Human-in-the-Loop Approvals**: Asynchronous pending approval queues, token signing, reason capture, and auto-expiry.
  - **Tool Runtime Sandbox**: Sandboxed execution engine with timeouts, exponential backoff retries, and rollback hooks.
  - **Cost Control & Model Router**: Multi-provider LLM routing (OpenAI, Anthropic, Gemini, Ollama) with cost/complexity optimization and resilient fallback chains.
  - **Evaluation Framework**: Objective metrics for task success, tool selection efficiency, safety violations, latency, and cost regression.
  - **Cryptographic Audit Trail**: Append-only SHA-256 hash-chained ledger guaranteeing tamper detection and forensic integrity.
- **Integrations**:
  - Anthropic Model Context Protocol (MCP) dynamic tool ingestion gateway.
  - LangGraph `AgentControlToolNode` middleware.
  - OpenAI Agents SDK / Function Calling `OpenAIControlledTool` adapter.
  - Kubernetes cluster management gateway with simulated safety guards.
  - GitHub gateway for PR creation, commit inspection, and diff analysis.
- **Frontend Dashboard**:
  - React 18 + TypeScript + Vite responsive dashboard with dark glassmorphic design system.
  - 8 core views: Overview KPIs, Agent Registry, Runs & Traces, Tool Calls Ledger, Pending Approvals Inbox, Policy Editor, Evaluations, and Audit Trail.
- **DevOps & Distribution**:
  - Docker Compose orchestration (PostgreSQL, Redis, API, Worker, Dashboard).
  - Kubernetes manifests & Helm 3 chart for cloud-native deployment.
  - GitHub Actions CI/CD pipeline covering linting, type checks, pytest unit/integration/security suites, and Docker builds.
  - Production Incident Commander demonstration scenario with complete walkthrough.
