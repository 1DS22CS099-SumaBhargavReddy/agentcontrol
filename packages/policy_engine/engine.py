"""
AgentControl Policy Engine
Declarative, versioned, environment-aware policy evaluation for production AI agents.
"""

import re
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PolicyRuleConstraint(BaseModel):
    """Specific constraints for tool execution."""
    disallowed_arguments: list[str] = Field(default_factory=list, description="Keys that cannot be present in arguments")
    argument_patterns: dict[str, str] = Field(default_factory=dict, description="Regex patterns that argument values must match")
    forbidden_values: dict[str, list[Any]] = Field(default_factory=dict, description="Values strictly forbidden for specific keys")
    max_cost_usd: float | None = Field(default=None, description="Max cost permitted for this operation")


class PolicyRule(BaseModel):
    id: str
    name: str
    description: str | None = None
    target_tool: str = Field(..., description="Tool name or pattern (e.g., 'database.drop_table', 'kubernetes.*', '*')")
    target_tag: str | None = Field(default=None, description="Tag target (e.g. 'destructive', 'network')")
    allowed: bool = Field(default=True, description="Whether this operation is permitted at all")
    require_human_approval: bool = Field(default=False, description="Whether human approval is required")
    constraints: PolicyRuleConstraint | None = None
    reason: str | None = None


class EnvironmentPolicy(BaseModel):
    version: str = "1.0.0"
    environment: str = Field(..., description="Environment (e.g., 'production', 'staging', 'development')")
    rules: list[PolicyRule] = Field(default_factory=list)
    default_require_approval_for_destructive: bool = True


class PolicyViolation(BaseModel):
    rule_id: str
    rule_name: str
    message: str
    severity: str = "high"  # low, medium, high, critical


class PolicyEvaluationRequest(BaseModel):
    agent_id: str
    environment: str
    tool_name: str
    tool_tags: list[str] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    context: dict[str, Any] = Field(default_factory=dict)


class PolicyEvaluationResult(BaseModel):
    allowed: bool
    requires_human_approval: bool
    violations: list[PolicyViolation] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    approval_reasons: list[str] = Field(default_factory=list)


class PolicyEngine:
    """
    Evaluates declarative policies per environment.
    Strictly deterministic and auditable.
    """

    def __init__(self):
        self._policies_by_env: dict[str, EnvironmentPolicy] = {}

    def register_policy(self, policy: EnvironmentPolicy) -> None:
        self._policies_by_env[policy.environment.lower()] = policy

    def load_from_yaml(self, yaml_content: str) -> None:
        data = yaml.safe_load(yaml_content)
        if not data or "policies" not in data:
            raise ValueError("Invalid policy YAML: root must contain 'policies' mapping")

        for env_name, env_spec in data["policies"].items():
            rules: list[PolicyRule] = []
            env_destructive_approval = env_spec.get("destructive_operations", {}).get("require_human_approval", True)

            # Parse hierarchical service.action policies from YAML
            for section_key, section_val in env_spec.items():
                if section_key == "destructive_operations":
                    continue
                if isinstance(section_val, dict):
                    for action_key, action_spec in section_val.items():
                        if isinstance(action_spec, dict):
                            rule_id = f"{env_name}.{section_key}.{action_key}"
                            rule_tool = f"{section_key}.{action_key}"
                            constraints = None
                            if "constraints" in action_spec:
                                constraints = PolicyRuleConstraint(**action_spec["constraints"])

                            rules.append(
                                PolicyRule(
                                    id=rule_id,
                                    name=f"{section_key} {action_key} rule",
                                    target_tool=rule_tool,
                                    allowed=action_spec.get("allowed", True),
                                    require_human_approval=action_spec.get("require_human_approval", False),
                                    constraints=constraints,
                                    reason=action_spec.get("reason", f"Policy restriction on {rule_tool}")
                                )
                            )

            policy = EnvironmentPolicy(
                version=data.get("version", "1.0.0"),
                environment=env_name,
                rules=rules,
                default_require_approval_for_destructive=env_destructive_approval
            )
            self.register_policy(policy)

    @staticmethod
    def _tool_matches(pattern: str, tool_name: str) -> bool:
        if pattern == "*" or pattern == tool_name:
            return True
        if pattern.endswith("*") and tool_name.startswith(pattern[:-1]):
            return True
        return False

    def evaluate(self, request: PolicyEvaluationRequest) -> PolicyEvaluationResult:
        env = request.environment.lower()
        policy = self._policies_by_env.get(env)

        # Default policy if none explicitly defined for environment:
        # In production, default requires approval for destructive actions; in dev, more relaxed.
        default_destructive_approval = True if env == "production" else False
        if policy is not None:
            default_destructive_approval = policy.default_require_approval_for_destructive

        allowed = True
        requires_approval = False
        violations: list[PolicyViolation] = []
        matched_rules: list[str] = []
        approval_reasons: list[str] = []

        # Tag-based baseline check: if action is tagged destructive, apply environment baseline
        if "destructive" in [t.lower() for t in request.tool_tags] and default_destructive_approval:
            requires_approval = True
            approval_reasons.append(f"Destructive operation in '{env}' environment requires human sign-off")

        if policy is None:
            return PolicyEvaluationResult(
                allowed=allowed,
                requires_human_approval=requires_approval,
                violations=violations,
                matched_rules=matched_rules,
                approval_reasons=approval_reasons
            )

        for rule in policy.rules:
            # Check target tool pattern
            matches_tool = self._tool_matches(rule.target_tool, request.tool_name)
            matches_tag = rule.target_tag is not None and rule.target_tag.lower() in [t.lower() for t in request.tool_tags]

            if not (matches_tool or matches_tag):
                continue

            matched_rules.append(rule.id)

            # Check if outright disallowed
            if not rule.allowed:
                allowed = False
                violations.append(
                    PolicyViolation(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        message=rule.reason or f"Tool '{request.tool_name}' is forbidden in {env}",
                        severity="critical"
                    )
                )

            # Check if human approval required
            if rule.require_human_approval:
                requires_approval = True
                approval_reasons.append(rule.reason or f"Rule '{rule.name}' requires human approval")

            # Check constraints
            if rule.constraints:
                c = rule.constraints

                # Disallowed arguments
                for forbidden_key in c.disallowed_arguments:
                    if forbidden_key in request.arguments:
                        allowed = False
                        violations.append(
                            PolicyViolation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                message=f"Argument '{forbidden_key}' is strictly forbidden by policy",
                                severity="high"
                            )
                        )

                # Forbidden values
                for key, forbidden_list in c.forbidden_values.items():
                    val = request.arguments.get(key)
                    if val in forbidden_list:
                        allowed = False
                        violations.append(
                            PolicyViolation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                message=f"Argument '{key}={val}' matches forbidden values {forbidden_list}",
                                severity="critical"
                            )
                        )

                # Argument regex patterns
                for key, pattern in c.argument_patterns.items():
                    val = str(request.arguments.get(key, ""))
                    if not re.match(pattern, val):
                        allowed = False
                        violations.append(
                            PolicyViolation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                message=f"Argument '{key}' value does not comply with required pattern '{pattern}'",
                                severity="high"
                            )
                        )

                # Cost constraints
                if c.max_cost_usd is not None and request.estimated_cost_usd > c.max_cost_usd:
                    allowed = False
                    violations.append(
                        PolicyViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            message=f"Estimated cost ${request.estimated_cost_usd:.4f} exceeds policy maximum ${c.max_cost_usd:.4f}",
                            severity="medium"
                        )
                    )

        return PolicyEvaluationResult(
            allowed=allowed,
            requires_human_approval=requires_approval,
            violations=violations,
            matched_rules=matched_rules,
            approval_reasons=approval_reasons
        )
