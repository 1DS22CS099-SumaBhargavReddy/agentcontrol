# Security Policy

AgentControl is security-critical infrastructure designed to govern and gate AI agent interactions with sensitive real-world systems. We take security vulnerabilities seriously.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**DO NOT report security vulnerabilities through public GitHub issues.**

Instead, report them privately using one of the following channels:

1. **GitHub Security Advisory**: Navigate to the repository's "Security" tab and select **"Report a vulnerability"**.
2. **Email**: Send an encrypted or plain report to `security@agentcontrol.dev`.

### What to Include

Please provide:
* Description of the vulnerability and its potential impact.
* Steps to reproduce, proof of concept (PoC), or code snippet.
* Affected components (e.g., Policy Engine, Permission Engine, Prompt Injection Defense, Browser Scanner, Execution Engine).
* Suggested fix or mitigation if available.

### Response Timeline

* **Initial response**: Within 24-48 hours.
* **Triage & severity rating**: Within 72 hours.
* **Fix & advisory release**: Coordinated disclosure within 30 days or sooner depending on severity (CVSS 3.1).

## Security Architecture Principles

1. **Zero-Trust**: LLMs and agent plans are treated as untrusted callers.
2. **Least Privilege**: Default deny on all tool calls unless explicitly permitted.
3. **Defense in Depth**: Multi-layer evaluation (Permission -> Policy -> Risk -> Human Sign-off -> Execution Sandbox).
4. **Tamper-Resistant Audit**: Cryptographic SHA-256 signatures and append-only audit records.
