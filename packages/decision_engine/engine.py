"""
AgentControl Decision Layer
Provider-independent decision abstraction with deterministic override guarantees.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DecisionOutcome(str):
    APPROVE = "approve"
    REJECT = "reject"
    HUMAN_REVIEW = "human_review"


class DecisionRequest(BaseModel):
    question: str
    options: List[str] = Field(default_factory=lambda: [DecisionOutcome.APPROVE, DecisionOutcome.REJECT, DecisionOutcome.HUMAN_REVIEW])
    context: Dict[str, Any] = Field(default_factory=dict)
    agent_id: Optional[str] = None
    environment: Optional[str] = None


class DecisionResponse(BaseModel):
    decision: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    provider_used: str
    deterministic_override: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseDecisionProvider(ABC):
    """Abstract base class for decision providers."""

    @abstractmethod
    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        pass


class RuleBasedDecisionProvider(BaseDecisionProvider):
    """Deterministic rule-based decision provider based on policy and risk outputs."""

    def __init__(self, high_risk_threshold: float = 0.50):
        self.high_risk_threshold = high_risk_threshold

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        ctx = request.context
        policy_allowed = ctx.get("policy_allowed", True)
        policy_violations = ctx.get("policy_violations", [])
        risk_score = float(ctx.get("risk_score", 0.0))
        risk_reasons = ctx.get("risk_reasons", [])
        policy_requires_approval = ctx.get("policy_requires_approval", False)

        # 1. Policy violation -> Immediate Reject
        if not policy_allowed or len(policy_violations) > 0:
            return DecisionResponse(
                decision=DecisionOutcome.REJECT,
                confidence=1.0,
                reason_codes=["policy_violation"] + [v.get("rule_name", "violation") if isinstance(v, dict) else str(v) for v in policy_violations],
                provider_used="rule_based",
                deterministic_override=True,
                metadata={"detail": "Operation violated declarative policy rules"}
            )

        # 2. High risk or policy explicitly requested human approval -> Human Review
        if policy_requires_approval or risk_score >= self.high_risk_threshold:
            reasons = ["high_risk_action"] if risk_score >= self.high_risk_threshold else ["policy_mandated_approval"]
            reasons.extend(risk_reasons)
            return DecisionResponse(
                decision=DecisionOutcome.HUMAN_REVIEW,
                confidence=1.0,
                reason_codes=reasons,
                provider_used="rule_based",
                deterministic_override=True,
                metadata={"risk_score": risk_score}
            )

        # 3. Otherwise -> Approve
        return DecisionResponse(
            decision=DecisionOutcome.APPROVE,
            confidence=0.98,
            reason_codes=["low_risk_within_policy"],
            provider_used="rule_based",
            deterministic_override=True,
            metadata={"risk_score": risk_score}
        )


class HybridDecisionProvider(BaseDecisionProvider):
    """
    Hybrid decision provider:
    - Deterministic rules always take priority for definitive decisions (Reject or Mandatory Human Review).
    - In ambiguous or borderline zones, queries an intelligent model provider.
    """

    def __init__(self, rule_provider: Optional[RuleBasedDecisionProvider] = None, model_provider: Optional[BaseDecisionProvider] = None):
        self.rule_provider = rule_provider or RuleBasedDecisionProvider()
        self.model_provider = model_provider

    async def decide(self, request: DecisionRequest) -> DecisionResponse:
        # First, run the deterministic rules
        rule_response = await self.rule_provider.decide(request)

        # If rules determined REJECT or HUMAN_REVIEW with high confidence, never downgrade to APPROVE
        if rule_response.decision in (DecisionOutcome.REJECT, DecisionOutcome.HUMAN_REVIEW):
            return rule_response

        # Check for ambiguous zone: e.g. risk score between 0.35 and 0.49
        risk_score = float(request.context.get("risk_score", 0.0))
        if 0.30 <= risk_score < 0.50 and self.model_provider is not None:
            model_response = await self.model_provider.decide(request)
            # Security guarantee: A model can escalate to HUMAN_REVIEW or REJECT, but cannot bypass a rule reject
            return model_response

        return rule_response
