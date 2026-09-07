"""RegressionShield — Dedicated Agentic AI Reasoning & Trajectory Evaluation SDK.

Evaluates autonomous agent execution chains:
- Tool Selection F1 (Precision & Recall)
- Parameter & Argument Schema Accuracy
- Prerequisite Call Ordering & Sequences
- Step Efficiency & Loop / Thrashing Penalties
- Intermediate Thought-Observation Faithfulness
"""

from typing import Dict, Any, List, Union, Optional

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
from regression_shield.core.llm_judge import LLMJudge
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator
from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
from regression_shield.adapters.smolagents import evaluate_smolagent, extract_smolagents_trajectory
from regression_shield.adapters.decorator import evaluate_agent_trace

__version__ = "0.2.0"


def evaluate_trajectory(
    scenario: Union[ScenarioSpec, Dict[str, Any]],
    trajectory: Union[List[Union[StepTrace, Dict[str, Any]]], Dict[str, Any]],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
    min_tool_selection: float = 0.85,
    min_argument_correctness: float = 0.85,
    min_order_accuracy: float = 1.00,
    min_trajectory_efficiency: float = 0.70,
) -> EvaluationReport:
    """Convenience top-level evaluation function.

    Args:
        scenario: Dict or ScenarioSpec with expected tools, arguments, and ordering.
        trajectory: List of steps or dict with 'steps' and 'final_response'.
        api_key: Optional API key for LLM-as-a-judge semantic evaluation.
        model: Optional model identifier (e.g., minimax/minimax-m2.7:free, gpt-4o-mini).
        base_url: Optional OpenAI-compatible API base URL (e.g. OpenRouter, Ollama, vLLM).
        use_llm_judge: Whether to run semantic LLM judge verification.
        min_tool_selection: Minimum Tool Selection F1 threshold (default 0.85).
        min_argument_correctness: Minimum Argument Schema Accuracy threshold (default 0.85).
        min_order_accuracy: Minimum Ordering Accuracy threshold (default 1.00).
        min_trajectory_efficiency: Minimum Step Efficiency threshold (default 0.70).

    Returns:
        EvaluationReport with status, composite score, metrics, judge_audit, and failure diagnostics.
    """
    evaluator = AgentTrajectoryEvaluator(
        api_key=api_key,
        model=model,
        base_url=base_url,
        use_llm_judge=use_llm_judge,
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
        judge_audit=raw.get("judge_audit"),
    )


__all__ = [
    "evaluate_trajectory",
    "AgentTrajectoryEvaluator",
    "LLMJudge",
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
