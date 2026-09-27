"""
AgentControl Permission Engine
Fine-grained, least-privilege permission enforcement with deterministic deny-precedence.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PermissionEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class PermissionRule(BaseModel):
    """A granular permission rule defining what an agent can perform on a resource."""
    id: str | None = None
    agent_id: str = Field(..., description="Agent ID or wildcard '*'")
    environment: str = Field(..., description="Target environment (e.g. 'production', 'staging', 'development', '*')")
    service: str = Field(..., description="Service namespace (e.g. 'github', 'kubernetes', 'aws')")
    resource: str = Field(..., description="Resource name or pattern (e.g. 'pods', 'ec2', 'repository', '*')")
    action: str = Field(..., description="Action name (e.g. 'read', 'write', 'delete', 'restart', '*')")
    effect: PermissionEffect = Field(default=PermissionEffect.ALLOW, description="allow or deny")
    conditions: dict[str, Any] = Field(default_factory=dict, description="Context conditions (e.g. namespace=prod)")
    description: str | None = None


class PermissionCheckRequest(BaseModel):
    """Request payload to verify permission for an agent operation."""
    agent_id: str
    environment: str
    service: str
    resource: str
    action: str
    context: dict[str, Any] = Field(default_factory=dict)


class PermissionCheckResult(BaseModel):
    """Result of permission verification."""
    allowed: bool
    reason: str
    matched_rule: PermissionRule | None = None
    effect: PermissionEffect = PermissionEffect.DENY
    evaluated_rules_count: int = 0


class PermissionEngine:
    """
    Evaluates fine-grained permissions with explicit deny-first semantics.
    Rule precedence:
    1. Any matching DENY rule immediately blocks the operation (Least Privilege principle).
    2. At least one matching ALLOW rule is required to permit the operation.
    3. If no matching rule is found, default DENY is returned.
    """

    def __init__(self, rules: list[PermissionRule] | None = None):
        self._rules: list[PermissionRule] = rules or []

    def add_rule(self, rule: PermissionRule) -> None:
        self._rules.append(rule)

    def load_rules(self, rules: list[PermissionRule]) -> None:
        self._rules = list(rules)

    def get_rules_for_agent(self, agent_id: str) -> list[PermissionRule]:
        return [r for r in self._rules if r.agent_id in (agent_id, "*")]

    @staticmethod
    def _match_string(pattern: str, value: str) -> bool:
        if pattern == "*" or value == "*" or pattern == value:
            return True
        if pattern.endswith("*") and value.startswith(pattern[:-1]):
            return True
        if value.endswith("*") and pattern.startswith(value[:-1]):
            return True
        return False

    @staticmethod
    def _match_conditions(rule_conditions: dict[str, Any], context: dict[str, Any]) -> bool:
        if not rule_conditions:
            return True
        for key, expected_val in rule_conditions.items():
            actual_val = context.get(key)
            if actual_val is None:
                return False
            if isinstance(expected_val, list):
                if actual_val not in expected_val:
                    return False
            elif actual_val != expected_val:
                return False
        return True

    def check(self, request: PermissionCheckRequest) -> PermissionCheckResult:
        """
        Evaluate permission for the given request.
        Strict security rules:
        - Exact/Wildcard Agent Match
        - Strict Environment Match (production cannot inherit development rules)
        - Service / Resource / Action match
        - Condition matching against contextual arguments
        """
        matched_allow: PermissionRule | None = None
        evaluated_count = 0

        for rule in self._rules:
            # Check agent
            if not self._match_string(rule.agent_id, request.agent_id):
                continue

            # Check environment
            if not self._match_string(rule.environment, request.environment):
                continue

            # Check service
            if not self._match_string(rule.service, request.service):
                continue

            # Check resource
            if not self._match_string(rule.resource, request.resource):
                continue

            # Check action
            if not self._match_string(rule.action, request.action):
                continue

            # Check context conditions
            if not self._match_conditions(rule.conditions, request.context):
                continue

            evaluated_count += 1

            # Explicit DENY takes absolute priority
            if rule.effect == PermissionEffect.DENY:
                return PermissionCheckResult(
                    allowed=False,
                    reason=f"Action explicitly denied by rule {rule.id or 'unnamed'} (service={rule.service}, resource={rule.resource}, action={rule.action})",
                    matched_rule=rule,
                    effect=PermissionEffect.DENY,
                    evaluated_rules_count=evaluated_count
                )

            # Record first matching allow
            if rule.effect == PermissionEffect.ALLOW and matched_allow is None:
                matched_allow = rule

        if matched_allow is not None:
            return PermissionCheckResult(
                allowed=True,
                reason=f"Action allowed by rule {matched_allow.id or 'unnamed'} for agent '{request.agent_id}'",
                matched_rule=matched_allow,
                effect=PermissionEffect.ALLOW,
                evaluated_rules_count=evaluated_count
            )

        # Default Deny
        return PermissionCheckResult(
            allowed=False,
            reason=f"Default deny: No matching allow rule found for agent '{request.agent_id}' on {request.service}:{request.resource}:{request.action} in {request.environment}",
            matched_rule=None,
            effect=PermissionEffect.DENY,
            evaluated_rules_count=evaluated_count
        )
