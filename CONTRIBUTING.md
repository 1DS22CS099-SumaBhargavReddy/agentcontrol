# Contributing to AgentControl

Thank you for your interest in contributing to AgentControl! As an open-source control plane for production AI agents, community contributions are essential to building robust, secure, and developer-friendly infrastructure.

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- Python 3.10+ (tested through 3.14)
- Node.js 18+ and npm 9+
- Docker & Docker Compose (optional for local PostgreSQL and Redis)
- Git

### Initial Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/your-username/agentcontrol.git
   cd agentcontrol
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. Install dependencies in editable mode:
   ```bash
   pip install -e ".[dev,postgres,telemetry]"
   ```

4. Install dashboard dependencies:
   ```bash
   cd apps/dashboard
   npm install
   cd ../..
   ```

## Development Workflow

### Running Tests

We maintain high test coverage across all packages:

```bash
# Run all unit and integration tests
pytest

# Run tests with coverage
pytest --cov=packages --cov=apps

# Run a specific test suite
pytest tests/unit/test_policy_engine.py
```

### Code Formatting & Linting

We enforce code quality using Ruff:

```bash
# Check code style and lint
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Check formatting
ruff format --check .
```

## Architecture Principles for Contributions

When adding features or fixing bugs, adhere to these non-negotiable principles:
1. **Never Assume LLM Trust**: Every tool action must pass through the control plane pipeline (Permission -> Policy -> Risk -> Approval -> Sandbox Execution -> Audit).
2. **Deterministic Precedence**: Deterministic rules always override probabilistic or LLM-based decisions.
3. **No Secret Leaks**: Never log raw credentials, authorization tokens, or sensitive API keys into audit logs or OpenTelemetry spans.
4. **Backward Compatibility**: SDK interfaces and REST endpoints follow semantic versioning. Do not introduce breaking schema changes without deprecation cycles.

## Submitting Pull Requests

1. Create a feature branch: `git checkout -b feat/your-feature-name`.
2. Commit your changes with descriptive commit messages following Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).
3. Ensure all tests and lint checks pass locally.
4. Open a Pull Request referencing the related issue.
