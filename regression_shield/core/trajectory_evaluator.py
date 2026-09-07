"""Core Trajectory Evaluation Orchestrator for RegressionShield SDK."""

import logging
from typing import Dict, Any, List, Union

from regression_shield.core.agent_metrics import (
    ToolSelectionMetric,
    ArgumentCorrectnessMetric,
    ToolCallOrderMetric,
    StepEfficiencyMetric,
    ReasoningFaithfulnessMetric,
    CompositeTrajectoryScore,
)
from regression_shield.models import ScenarioSpec, StepTrace, EvaluationReport

logger = logging.getLogger("regression_shield.evaluator")


class AgentTrajectoryEvaluator:
    """Core evaluation orchestrator assessing ReAct agent trajectories."""

    def __init__(
        self,
        min_tool_selection: float = 0.85,
        min_argument_correctness: float = 0.85,
        min_order_accuracy: float = 1.00,
        min_trajectory_efficiency: float = 0.70,
    ):
        self.min_tool_selection = min_tool_selection
        self.min_argument_correctness = min_argument_correctness
        self.min_order_accuracy = min_order_accuracy
        self.min_trajectory_efficiency = min_trajectory_efficiency

    def evaluate_scenario(
        self,
        scenario: Union[ScenarioSpec, Dict[str, Any]],
        trajectory_data: Union[List[Union[StepTrace, Dict[str, Any]]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluate an agent trajectory against a scenario policy specification.

        Args:
            scenario: Scenario dict or ScenarioSpec.
            trajectory_data: List of steps or dict with 'steps' and 'final_response'.

        Returns:
            Dict report with status, composite_score, metrics, and failures.
        """
        # Normalize scenario
        if isinstance(scenario, ScenarioSpec):
            sc_dict = scenario.to_dict()
        else:
            sc_dict = scenario

        scenario_id = sc_dict.get("scenario_id", "AT_CUSTOM")
        title = sc_dict.get("title", f"Scenario {scenario_id}")
        domain = sc_dict.get("domain", "General")
        expected_tools = sc_dict.get("expected_tools", [])
        expected_arguments = sc_dict.get("expected_arguments", {})
        expected_order = sc_dict.get("expected_order", [])

        # Normalize trajectory
        if isinstance(trajectory_data, list):
            raw_steps = trajectory_data
            final_response = ""
        else:
            raw_steps = trajectory_data.get("steps", [])
            final_response = trajectory_data.get("final_response", "")

        # Convert StepTrace objects to dicts if needed
        steps: List[Dict[str, Any]] = []
        for s in raw_steps:
            if isinstance(s, StepTrace):
                steps.append(s.to_dict())
            elif isinstance(s, dict):
                steps.append(s)

        # 1. Extract invoked tools
        invoked_tools: List[str] = []
        for s in steps:
            action = s.get("action", {})
            if action.get("type", "tool_call") == "tool_call" and "name" in action:
                invoked_tools.append(action["name"])

        # 2. Tool Selection
        tool_sel_res = ToolSelectionMetric.evaluate(expected_tools, invoked_tools)

        # 3. Argument Correctness
        arg_corr_res = ArgumentCorrectnessMetric.evaluate(expected_arguments, steps)

        # 4. Tool Call Order
        order_res = ToolCallOrderMetric.evaluate(expected_order, invoked_tools)

        # 5. Efficiency
        optimal_steps = sc_dict.get("optimal_step_count") or len(expected_tools) or 3
        efficiency_res = StepEfficiencyMetric.evaluate(steps, optimal_steps=optimal_steps)

        # 6. Reasoning Faithfulness
        reasoning_res = ReasoningFaithfulnessMetric.evaluate(steps)

        # 7. Composite
        metric_scores = {
            "tool_selection": tool_sel_res["score"],
            "argument_correctness": arg_corr_res["score"],
            "call_ordering": order_res["score"],
            "step_efficiency": efficiency_res["score"],
            "reasoning_faithfulness": reasoning_res["score"],
        }
        composite_score = CompositeTrajectoryScore.calculate(metric_scores)

        # Diagnostics & failure detection
        failures = []

        if tool_sel_res["score"] < self.min_tool_selection:
            failures.append(
                f"Tool Selection F1 ({tool_sel_res['score']:.2f}) < threshold ({self.min_tool_selection:.2f}). "
                f"Missing: {tool_sel_res['missing']}, Unexpected: {tool_sel_res['unexpected']}"
            )

        if arg_corr_res["score"] < self.min_argument_correctness:
            failures.append(
                f"Argument Correctness ({arg_corr_res['score']:.2f}) < threshold ({self.min_argument_correctness:.2f}). "
                f"Mismatches detected: {len(arg_corr_res['mismatches'])}"
            )

        if order_res["score"] < self.min_order_accuracy:
            failures.append(
                f"Tool Order Accuracy ({order_res['score']:.2f}) < threshold ({self.min_order_accuracy:.2f}). "
                f"Violations: {'; '.join(order_res['violations'])}"
            )

        if efficiency_res["score"] < self.min_trajectory_efficiency:
            failures.append(
                f"Trajectory Efficiency ({efficiency_res['score']:.2f}) < threshold ({self.min_trajectory_efficiency:.2f}). "
                f"Total steps: {efficiency_res['total_steps']}, Redundant calls: {efficiency_res['redundant_calls']}"
            )

        is_passed = len(failures) == 0

        report = {
            "scenario_id": scenario_id,
            "title": title,
            "domain": domain,
            "status": "PASSED" if is_passed else "FAILED",
            "composite_score": composite_score,
            "metrics": metric_scores,
            "details": {
                "invoked_tools": invoked_tools,
                "expected_tools": expected_tools,
                "tool_selection": tool_sel_res,
                "argument_correctness": arg_corr_res,
                "order_analysis": order_res,
                "efficiency": efficiency_res,
                "reasoning": reasoning_res,
                "total_steps": len(steps),
                "final_response": final_response,
                "steps": steps,
            },
            "failures": failures,
        }

        return report
