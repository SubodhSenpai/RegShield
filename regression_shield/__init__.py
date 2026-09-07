"""RegressionShield — Dedicated Agentic AI Reasoning & Trajectory Evaluation SDK.

Evaluates autonomous agent execution chains:
- Tool Selection F1 (Precision & Recall)
- Parameter & Argument Schema Accuracy
- Prerequisite Call Ordering & Sequences
- Step Efficiency & Loop / Thrashing Penalties
- Intermediate Thought-Observation Faithfulness
"""

from typing import Dict, Any, List, Union

from regression_shield.models import (
    StepTrace,
    ScenarioSpec,
    EvaluationReport,
)
from regression_shield.core.agent_metrics import (
    ToolSelectionMetric,
    ArgumentCorrectnessMetric,
    ToolCallOrderMetric,
    StepEfficiencyMetric,
    ReasoningFaithfulnessMetric,
    CompositeTrajectoryScore,
)
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator
from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
from regression_shield.adapters.smolagents import evaluate_smolagent, extract_smolagents_trajectory
from regression_shield.adapters.decorator import evaluate_agent_trace

__version__ = "0.2.0"


def evaluate_trajectory(
    scenario: Union[ScenarioSpec, Dict[str, Any]],
    trajectory: Union[List[Union[StepTrace, Dict[str, Any]]], Dict[str, Any]],
    min_tool_selection: float = 0.85,
    min_argument_correctness: float = 0.85,
    min_order_accuracy: float = 1.00,
    min_trajectory_efficiency: float = 0.70,
) -> EvaluationReport:
    """Convenience top-level evaluation function.

    Args:
        scenario: Dict or ScenarioSpec with expected tools, arguments, and ordering.
        trajectory: List of steps or dict with 'steps' and 'final_response'.

    Returns:
        EvaluationReport with status, composite score, metrics, and failure diagnostics.
    """
    evaluator = AgentTrajectoryEvaluator(
        min_tool_selection=min_tool_selection,
        min_argument_correctness=min_argument_correctness,
        min_order_accuracy=min_order_accuracy,
        min_trajectory_efficiency=min_trajectory_efficiency,
    )
    raw = evaluator.evaluate_scenario(scenario, trajectory)
    return EvaluationReport(
        scenario_id=raw["scenario_id"],
        title=raw["title"],
        domain=raw["domain"],
        status=raw["status"],
        composite_score=raw["composite_score"],
        metrics=raw["metrics"],
        failures=raw["failures"],
        details=raw["details"],
    )


__all__ = [
    "evaluate_trajectory",
    "AgentTrajectoryEvaluator",
    "ScenarioSpec",
    "StepTrace",
    "EvaluationReport",
    "ToolSelectionMetric",
    "ArgumentCorrectnessMetric",
    "ToolCallOrderMetric",
    "StepEfficiencyMetric",
    "ReasoningFaithfulnessMetric",
    "CompositeTrajectoryScore",
    "RegressionShieldCallbackHandler",
    "evaluate_smolagent",
    "extract_smolagents_trajectory",
    "evaluate_agent_trace",
]
