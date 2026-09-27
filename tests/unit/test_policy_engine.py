"""
Unit tests for AgentControl Declarative Policy Engine
Tests YAML parsing, environment overrides, disallowed argument restrictions, and regex patterns.
"""

from packages.policy_engine.engine import (
    PolicyEngine,
    PolicyEvaluationRequest,
    PolicyRule,
    PolicyRuleConstraint,
)

SAMPLE_POLICY_YAML = """
version: "1.0.0"
policies:
  production:
    destructive_operations:
      require_human_approval: true
    database:
      drop_table:
        allowed: false
        reason: "Never allow drop_table in production"
      read_query:
        allowed: true
        require_human_approval: false
    kubernetes:
      restart_pod:
        allowed: true
        require_human_approval: true
        constraints:
          disallowed_arguments: ["force"]
          forbidden_values:
            namespace: ["kube-system", "kube-public"]
          argument_patterns:
            pod: "^[a-z0-9-]+$"
  development:
    destructive_operations:
      require_human_approval: false
"""


def test_policy_yaml_loading_and_evaluation():
    engine = PolicyEngine()
    engine.load_from_yaml(SAMPLE_POLICY_YAML)

    # 1. database.drop_table in production must be disallowed
    req_drop = PolicyEvaluationRequest(
        agent_id="agent-1",
        environment="production",
        tool_name="database.drop_table",
        arguments={"table": "users"}
    )
    res_drop = engine.evaluate(req_drop)
    assert not res_drop.allowed
    assert any("Never allow drop_table" in v.message for v in res_drop.violations)

    # 2. database.read_query in production is allowed without human approval
    req_read = PolicyEvaluationRequest(
        agent_id="agent-1",
        environment="production",
        tool_name="database.read_query",
        arguments={"query": "SELECT 1"}
    )
    res_read = engine.evaluate(req_read)
    assert res_read.allowed
    assert not res_read.requires_human_approval

    # 3. kubernetes.restart_pod in production requires human approval
    req_restart = PolicyEvaluationRequest(
        agent_id="agent-1",
        environment="production",
        tool_name="kubernetes.restart_pod",
        arguments={"namespace": "api", "pod": "api-service-1"}
    )
    res_restart = engine.evaluate(req_restart)
    assert res_restart.allowed
    assert res_restart.requires_human_approval


def test_policy_constraints_forbidden_namespace():
    engine = PolicyEngine()
    engine.load_from_yaml(SAMPLE_POLICY_YAML)

    # Attempting to target kube-system must be blocked
    req = PolicyEvaluationRequest(
        agent_id="agent-1",
        environment="production",
        tool_name="kubernetes.restart_pod",
        arguments={"namespace": "kube-system", "pod": "coredns-123"}
    )
    res = engine.evaluate(req)
    assert not res.allowed
    assert any("forbidden values" in v.message for v in res.violations)


def test_policy_constraints_disallowed_argument():
    engine = PolicyEngine()
    engine.load_from_yaml(SAMPLE_POLICY_YAML)

    # Supplying 'force: true' must be rejected
    req = PolicyEvaluationRequest(
        agent_id="agent-1",
        environment="production",
        tool_name="kubernetes.restart_pod",
        arguments={"namespace": "apps", "pod": "worker-1", "force": True}
    )
    res = engine.evaluate(req)
    assert not res.allowed
    assert any("strictly forbidden" in v.message for v in res.violations)


def test_policy_cost_limit():
    engine = PolicyEngine()
    rule = PolicyRule(
        id="cost-limit-rule",
        name="Cost control limit",
        target_tool="*",
        allowed=True,
        constraints=PolicyRuleConstraint(max_cost_usd=0.05)
    )
    from packages.policy_engine.engine import EnvironmentPolicy
    engine.register_policy(EnvironmentPolicy(environment="production", rules=[rule]))

    # Within cost
    res_ok = engine.evaluate(PolicyEvaluationRequest(
        agent_id="agent-1", environment="production", tool_name="llm.generate", estimated_cost_usd=0.02
    ))
    assert res_ok.allowed

    # Exceeding cost
    res_over = engine.evaluate(PolicyEvaluationRequest(
        agent_id="agent-1", environment="production", tool_name="llm.generate", estimated_cost_usd=0.15
    ))
    assert not res_over.allowed
    assert any("exceeds policy maximum" in v.message for v in res_over.violations)
