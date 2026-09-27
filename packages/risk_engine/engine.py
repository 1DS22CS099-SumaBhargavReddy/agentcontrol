"""
AgentControl Risk Engine
Deterministic multi-factor risk assessment for AI agent tool actions.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskAssessmentRequest(BaseModel):
    agent_id: str
    environment: str
    tool_name: str
    tool_inherent_risk: str = "medium"  # low, medium, high, critical
    tool_tags: list[str] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class RiskAssessmentResult(BaseModel):
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Calculated normalized risk score")
    risk_level: RiskLevel
    reason_codes: list[str]
    requires_human_approval: bool
    blast_radius: str  # localized, moderate, broad, catastrophic
    factors_breakdown: dict[str, float]


class RiskEngine:
    """
    Evaluates multi-factor deterministic risk for any agent-initiated action.
    Guarantees consistent, reproducible risk ratings without depending on non-deterministic LLMs.
    """

    CRITICAL_THRESHOLDS = {
        "critical_approval_threshold": 0.50,  # Any action >= 0.50 requires human sign-off
    }

    SENSITIVE_TARGETS = {
        "kube-system", "production", "prod", "master", "main",
        "payments", "billing", "users", "credentials", "secrets",
        "pci", "hipaa", "financial"
    }

    DESTRUCTIVE_KEYWORDS = {
        "delete", "drop", "destroy", "truncate", "terminate",
        "kill", "wipe", "format", "reboot", "restart", "rollback"
    }

    def evaluate(self, request: RiskAssessmentRequest) -> RiskAssessmentResult:
        factors: dict[str, float] = {}
        reason_codes: list[str] = []

        # Determine inherent tool traits
        tool_lower = request.tool_name.lower()
        tags_lower = [t.lower() for t in request.tool_tags]
        inherent = request.tool_inherent_risk.lower()

        is_destructive = any(kw in tool_lower for kw in self.DESTRUCTIVE_KEYWORDS) or any(
            t in ("destructive", "delete", "danger") for t in tags_lower
        )
        is_read_only = (inherent == "low" or any(t in ("read", "query", "get", "describe") for t in tags_lower)) and not is_destructive

        # 1. Environment baseline
        env = request.environment.lower()
        if env in ("production", "prod"):
            factors["environment"] = 0.10 if is_read_only else 0.35
            reason_codes.append("production_environment")
        elif env in ("staging", "stage"):
            factors["environment"] = 0.05 if is_read_only else 0.15
            reason_codes.append("staging_environment")
        else:
            factors["environment"] = 0.05
            reason_codes.append("non_production_environment")

        # 2. Tool inherent risk
        if inherent == "critical":
            factors["tool_inherent"] = 0.35
            reason_codes.append("critical_inherent_tool_risk")
        elif inherent == "high":
            factors["tool_inherent"] = 0.25
            reason_codes.append("high_inherent_tool_risk")
        elif inherent == "medium":
            factors["tool_inherent"] = 0.15
            reason_codes.append("medium_inherent_tool_risk")
        else:
            factors["tool_inherent"] = 0.05
            reason_codes.append("low_inherent_tool_risk")

        # 3. Action / destructive keywords detection in tool name and tags
        if is_destructive:
            factors["destructive_operation"] = 0.25
            reason_codes.append("destructive_operation")

        # 4. Sensitive targets inspection in arguments
        sensitive_match = False
        raw_args_str = str(request.arguments).lower()
        for target in self.SENSITIVE_TARGETS:
            if target in raw_args_str:
                sensitive_match = True
                reason_codes.append(f"sensitive_target_{target}")

        if sensitive_match:
            factors["sensitive_target"] = 0.20

        # 5. Blast radius evaluation
        blast_radius = "localized"
        target_keys = ["target_ids", "targets", "pod", "instances", "cluster", "hosts"]
        has_wildcard_target = any(
            str(request.arguments.get(k, "")).lower() in ("*", "all")
            for k in target_keys
        ) or request.arguments.get("force") is True

        if has_wildcard_target:
            factors["blast_radius"] = 0.20
            reason_codes.append("high_blast_radius_wildcard_or_force")
            blast_radius = "broad"
        elif is_destructive and env in ("production", "prod"):
            blast_radius = "catastrophic"
            factors["blast_radius"] = 0.15
            reason_codes.append("production_destructive_blast_radius")
        elif is_destructive:
            blast_radius = "moderate"

        # Calculate sum and cap between 0.0 and 1.0
        total_score = min(1.0, sum(factors.values()))
        # Round to 2 decimals
        risk_score = round(total_score, 2)

        # Map to RiskLevel
        if risk_score >= 0.75:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= 0.50:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 0.25:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        # Requires approval if risk_score >= threshold
        requires_approval = risk_score >= self.CRITICAL_THRESHOLDS["critical_approval_threshold"]

        return RiskAssessmentResult(
            risk_score=risk_score,
            risk_level=risk_level,
            reason_codes=reason_codes,
            requires_human_approval=requires_approval,
            blast_radius=blast_radius,
            factors_breakdown=factors
        )
