"""RegressionShield — Dedicated Agentic AI Reasoning & Execution Trace Evaluation SDK.

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
    CompositeTraceScore,
    CompositeTrajectoryScore,
)
from regression_shield.core.llm_judge import LLMJudge
from regression_shield.core.trajectory_evaluator import (
    AgentTraceEvaluator,
    AgentTrajectoryEvaluator,
)
from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
from regression_shield.adapters.smolagents import (
    evaluate_smolagent,
    extract_smolagents_trace,
    extract_smolagents_trajectory,
)
from regression_shield.adapters.decorator import evaluate_agent_trace, shield

__version__ = "0.3.0"


def evaluate_trace(
    scenario: Union[ScenarioSpec, Dict[str, Any]],
    trace: Optional[Union[List[Union[StepTrace, Dict[str, Any]]], Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
    min_tool_selection: float = 0.85,
    min_argument_correctness: float = 0.85,
    min_order_accuracy: float = 1.00,
    min_trace_efficiency: float = 0.70,
    save_report: bool = True,
    sync_dashboard: bool = False,
    dashboard_url: str = "http://localhost:8000",
    **kwargs: Any,
) -> EvaluationReport:
    """Convenience top-level evaluation function for agent execution traces.

    Args:
        scenario: Dict or ScenarioSpec with expected tools, arguments, and ordering.
        trace: List of steps or dict with 'steps' and 'final_response'.
        api_key: Optional API key for LLM-as-a-judge semantic evaluation.
        model: Optional model identifier (e.g., minimax/minimax-m2.7:free, gpt-4o-mini).
        base_url: Optional OpenAI-compatible API base URL (e.g. OpenRouter, Ollama, vLLM).
        use_llm_judge: Whether to run semantic LLM judge verification.
        min_tool_selection: Minimum Tool Selection F1 threshold (default 0.85).
        min_argument_correctness: Minimum Argument Schema Accuracy threshold (default 0.85).
        min_order_accuracy: Minimum Ordering Accuracy threshold (default 1.00).
        min_trace_efficiency: Minimum Step Efficiency threshold (default 0.70).
        save_report: Automatically persist report to reports/latest_report.json for local dashboard (default True).
        sync_dashboard: Post report directly to running dashboard server API (default False).
        dashboard_url: Dashboard server base URL for syncing (default http://localhost:8000).

    Returns:
        EvaluationReport with status, composite score, metrics, judge_audit, and failure diagnostics.
    """
    raw_trace = trace if trace is not None else kwargs.get("trajectory")
    if raw_trace is None:
        raw_trace = []

    eff_thresh = kwargs.get("min_trajectory_efficiency", min_trace_efficiency)

    evaluator = AgentTraceEvaluator(
        api_key=api_key,
        model=model,
        base_url=base_url,
        use_llm_judge=use_llm_judge,
        min_tool_selection=min_tool_selection,
        min_argument_correctness=min_argument_correctness,
        min_order_accuracy=min_order_accuracy,
        min_trace_efficiency=eff_thresh,
    )
    raw = evaluator.evaluate_scenario(scenario, raw_trace)
    report = EvaluationReport(
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

    if save_report:
        try:
            report.save()
        except Exception:
            pass

    if sync_dashboard:
        try:
            report.sync_to_dashboard(dashboard_url)
        except Exception:
            pass

    return report


# Backward compatibility alias
evaluate_trajectory = evaluate_trace


__all__ = [
    "evaluate_trace",
    "evaluate_trajectory",
    "AgentTraceEvaluator",
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
    "CompositeTraceScore",
    "CompositeTrajectoryScore",
    "RegressionShieldCallbackHandler",
    "evaluate_smolagent",
    "extract_smolagents_trace",
    "extract_smolagents_trajectory",
    "evaluate_agent_trace",
]

