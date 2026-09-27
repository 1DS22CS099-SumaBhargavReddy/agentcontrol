"""
Unit tests for AgentControl Evaluation Framework
Tests trajectory evaluation, safety metrics, policy compliance calculations, and regression detection.
"""

from packages.evaluation import (
    AgentEvaluator,
    EvaluationInput,
    TrajectoryStep,
)


def test_perfect_trajectory_evaluation():
    inp = EvaluationInput(
        run_id="run-1",
        agent_id="test-agent",
        task_goal="Query database safely",
        expected_tools=["database.read_query"],
        trajectory=[
            TrajectoryStep(
                tool_name="database.read_query",
                arguments={"query": "SELECT 1"},
                status="success",
                is_necessary=True,
                policy_violation=False,
                prompt_injection_flag=False,
                duration_ms=120.0,
                cost_usd=0.001
            )
        ],
        task_completed=True,
        total_tokens=150,
        total_cost_usd=0.001
    )

    report = AgentEvaluator.evaluate(inp)
    assert report.task_success == 1.0
    assert report.tool_selection == 1.0
    assert report.policy_compliance == 1.0
    assert report.safety == 1.0
    assert report.regression_passed is True


def test_trajectory_with_violations_and_injections():
    inp = EvaluationInput(
        run_id="run-2",
        agent_id="compromised-agent",
        task_goal="Access internal resource",
        expected_tools=["safe_tool"],
        trajectory=[
            TrajectoryStep(
                tool_name="unnecessary_tool",
                status="failed",
                is_necessary=False,
                policy_violation=True,
                prompt_injection_flag=True,
                duration_ms=250.0
            ),
            TrajectoryStep(
                tool_name="safe_tool",
                status="success",
                is_necessary=True,
                policy_violation=False,
                prompt_injection_flag=False,
                duration_ms=100.0
            )
        ],
        task_completed=False
    )

    report = AgentEvaluator.evaluate(inp)
    assert report.task_success == 0.0
    assert report.policy_compliance < 1.0
    assert report.safety < 1.0
    assert report.policy_violations_count == 1
    assert report.injection_attempts_count == 1
    assert report.regression_passed is False
