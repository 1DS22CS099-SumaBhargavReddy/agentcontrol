"""
Unit tests for AgentControl Permission Engine
Validates fine-grained permissions, wildcard matching, environment isolation, and explicit deny precedence.
"""

import pytest
from packages.permission_engine.engine import (
    PermissionCheckRequest,
    PermissionEffect,
    PermissionEngine,
    PermissionRule,
)


def test_permission_default_deny():
    engine = PermissionEngine([])
    req = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="delete"
    )
    result = engine.check(req)
    assert not result.allowed
    assert result.effect == PermissionEffect.DENY
    assert "Default deny" in result.reason


def test_permission_exact_allow():
    rule = PermissionRule(
        id="rule-1",
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="read",
        effect=PermissionEffect.ALLOW
    )
    engine = PermissionEngine([rule])
    req = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="read"
    )
    result = engine.check(req)
    assert result.allowed
    assert result.effect == PermissionEffect.ALLOW


def test_permission_explicit_deny_precedence():
    """Explicit deny rule must override any matching allow rule (Least Privilege)."""
    allow_rule = PermissionRule(
        id="allow-all-k8s",
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="*",
        action="*",
        effect=PermissionEffect.ALLOW
    )
    deny_rule = PermissionRule(
        id="deny-delete-k8s",
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="delete",
        effect=PermissionEffect.DENY
    )
    engine = PermissionEngine([allow_rule, deny_rule])

    # Delete should be explicitly blocked
    del_req = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="delete"
    )
    res_del = engine.check(del_req)
    assert not res_del.allowed
    assert "explicitly denied" in res_del.reason

    # Read should still be allowed by the wildcard rule
    read_req = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="read"
    )
    res_read = engine.check(read_req)
    assert res_read.allowed


def test_permission_environment_isolation():
    """Staging permissions must never grant production access."""
    staging_rule = PermissionRule(
        id="staging-perm",
        agent_id="test-agent",
        environment="staging",
        service="aws",
        resource="ec2",
        action="modify",
        effect=PermissionEffect.ALLOW
    )
    engine = PermissionEngine([staging_rule])

    prod_req = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="aws",
        resource="ec2",
        action="modify"
    )
    result = engine.check(prod_req)
    assert not result.allowed


def test_permission_condition_matching():
    conditional_rule = PermissionRule(
        id="cond-rule",
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="restart",
        effect=PermissionEffect.ALLOW,
        conditions={"namespace": "staging-apps"}
    )
    engine = PermissionEngine([conditional_rule])

    # Fails when namespace does not match
    req_fail = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="restart",
        context={"namespace": "kube-system"}
    )
    assert not engine.check(req_fail).allowed

    # Succeeds when namespace matches
    req_success = PermissionCheckRequest(
        agent_id="test-agent",
        environment="production",
        service="kubernetes",
        resource="pods",
        action="restart",
        context={"namespace": "staging-apps"}
    )
    assert engine.check(req_success).allowed
