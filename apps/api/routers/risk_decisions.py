"""
Risk Engine & Decision Layer Router
Endpoints for calculating action risk scores and determining autonomous vs human-review decisions.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.service import AuthenticatedUser, get_current_user
from apps.api.db.session import get_db
from packages.decision_engine.engine import (
    DecisionRequest,
    DecisionResponse,
    HybridDecisionProvider,
    RuleBasedDecisionProvider,
)
from packages.risk_engine.engine import (
    RiskAssessmentRequest,
    RiskAssessmentResult,
    RiskEngine,
)

router = APIRouter(tags=["Risk & Decisions"])

_risk_engine = RiskEngine()
_decision_provider = HybridDecisionProvider(rule_provider=RuleBasedDecisionProvider())


@router.post("/risk/evaluate", response_model=RiskAssessmentResult)
async def evaluate_risk(
    request: RiskAssessmentRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    return _risk_engine.evaluate(request)


@router.post("/decisions", response_model=DecisionResponse)
async def decide_action(
    request: DecisionRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    return await _decision_provider.decide(request)
