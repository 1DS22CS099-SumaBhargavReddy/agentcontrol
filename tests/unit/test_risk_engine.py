"""
Unit tests for AgentControl Risk Engine
Tests deterministic multi-factor scoring, blast radius evaluation, and approval triggers.
"""

import pytest
from packages.risk_engine.engine import (
    RiskAssessmentRequest,
    RiskEngine,
    RiskLevel,
)


def test_risk_low_read_operation():
    engine = RiskEngine()
    req = RiskAssessmentRequest(
        agent_id="test-agent",
        environment="development",
        tool_name="database.read_query",
        tool_inherent_risk="low",
        tool_tags=["read", "analytics"],
        arguments={"query": "SELECT COUNT(*) FROM items"}
    )
    result = engine.evaluate(req)
    assert result.risk_score < 0.25
    assert result.risk_level == RiskLevel.LOW
    assert not result.requires_human_approval


def test_risk_critical_production_destructive():
    engine = RiskEngine()
    req = RiskAssessmentRequest(
        agent_id="incident-agent",
        environment="production",
        tool_name="kubernetes.restart_pod",
        tool_inherent_risk="critical",
        tool_tags=["destructive", "kubernetes"],
        arguments={"namespace": "production", "pod": "billing-api-1"}
    )
    result = engine.evaluate(req)
    assert result.risk_score >= 0.75
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.requires_human_approval
    assert "production_environment" in result.reason_codes
    assert "destructive_operation" in result.reason_codes
    assert any("sensitive_target" in r for r in result.reason_codes)


def test_risk_blast_radius_wildcard():
    engine = RiskEngine()
    req = RiskAssessmentRequest(
        agent_id="cleanup-agent",
        environment="production",
        tool_name="cloud.terminate_instances",
        tool_inherent_risk="high",
        arguments={"target_ids": "*", "force": True}
    )
    result = engine.evaluate(req)
    assert result.blast_radius in ("broad", "catastrophic")
    assert result.requires_human_approval
    assert "high_blast_radius_wildcard_or_force" in result.reason_codes
