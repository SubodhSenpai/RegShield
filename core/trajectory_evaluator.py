"""Agent Trajectory Evaluator.

Orchestrates execution chain evaluation for Agentic AI workflows.
Evaluates:
- Tool calling precision and argument schema accuracy
- Call sequence order and prerequisite satisfaction
- Trajectory step efficiency and cycle/loop detection
- Intermediate reasoning faithfulness
- Composite trajectory score against defined policy thresholds
"""

import logging
from typing import Dict, Any, List
from config.settings import EvalConfig
from core.agent_metrics import (
    ToolSelectionMetric,
    ArgumentCorrectnessMetric,
    ToolCallOrderMetric,
    StepEfficiencyMetric,
    ReasoningFaithfulnessMetric,
    CompositeTrajectoryScore,
)

logger = logging.getLogger("regression_shield.trajectory_evaluator")


class AgentTrajectoryEvaluator:
    """Evaluates agent execution trajectories against task specifications."""

    def evaluate_scenario(
        self,
        scenario: Dict[str, Any],
        trajectory_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Evaluate an agent trajectory against a scenario specification.

        Args:
            scenario: Scenario dict from data/agent_trajectories.json containing
                      'scenario_id', 'expected_tools', 'expected_arguments',
                      'expected_order', 'goal'.
            trajectory_data: Agent execution trace containing 'steps' list and
                             'final_response'.

        Returns:
            Evaluation report with metric scores, pass/fail status, and failure details.
        """
        scenario_id = scenario.get("scenario_id", "AT_UNKNOWN")
        title = scenario.get("title", "Untitled Scenario")
        domain = scenario.get("domain", "General")
        expected_tools = scenario.get("expected_tools", [])
        expected_arguments = scenario.get("expected_arguments", {})
        expected_order = scenario.get("expected_order", [])

        if isinstance(trajectory_data, list):
            steps = trajectory_data
            final_response = ""
        else:
            steps = trajectory_data.get("steps", [])
            final_response = trajectory_data.get("final_response", "")

        logger.info("Evaluating agent trajectory for scenario: %s (%s)", scenario_id, title)

        # Extract invoked tools from steps
        invoked_tools: List[str] = []
        for s in steps:
            action = s.get("action", {})
            if action.get("type", "tool_call") == "tool_call" and "name" in action:
                invoked_tools.append(action["name"])

        # 1. Tool Selection Metric
        tool_sel_res = ToolSelectionMetric.evaluate(expected_tools, invoked_tools)

        # 2. Argument Correctness Metric
        arg_corr_res = ArgumentCorrectnessMetric.evaluate(expected_arguments, steps)

        # 3. Tool Call Order Metric
        order_res = ToolCallOrderMetric.evaluate(expected_order, invoked_tools)

        # 4. Step Efficiency Metric
        optimal_steps = len(expected_tools)
        efficiency_res = StepEfficiencyMetric.evaluate(steps, optimal_steps=optimal_steps)

        # 5. Reasoning Faithfulness Metric
        reasoning_res = ReasoningFaithfulnessMetric.evaluate(steps)

        # 6. Composite Score
        metric_scores = {
            "tool_selection": tool_sel_res["score"],
            "argument_correctness": arg_corr_res["score"],
            "call_ordering": order_res["score"],
            "step_efficiency": efficiency_res["score"],
            "reasoning_faithfulness": reasoning_res["score"],
        }
        composite_score = CompositeTrajectoryScore.calculate(metric_scores)

        # Failure checking against thresholds
        failures = []

        min_tool_sel = getattr(EvalConfig, "MIN_TOOL_SELECTION_SCORE", 0.85)
        min_arg_corr = getattr(EvalConfig, "MIN_ARGUMENT_CORRECTNESS_SCORE", 0.85)
        min_order = getattr(EvalConfig, "MIN_ORDER_ACCURACY_SCORE", 1.0)
        min_eff = getattr(EvalConfig, "MIN_TRAJECTORY_EFFICIENCY", 0.70)

        if tool_sel_res["score"] < min_tool_sel:
            failures.append(
                f"Tool Selection F1 ({tool_sel_res['score']:.2f}) < threshold ({min_tool_sel:.2f}). "
                f"Missing: {tool_sel_res['missing']}, Unexpected: {tool_sel_res['unexpected']}"
            )

        if arg_corr_res["score"] < min_arg_corr:
            failures.append(
                f"Argument Correctness ({arg_corr_res['score']:.2f}) < threshold ({min_arg_corr:.2f}). "
                f"Mismatches detected: {len(arg_corr_res['mismatches'])}"
            )

        if order_res["score"] < min_order:
            failures.append(
                f"Tool Order Accuracy ({order_res['score']:.2f}) < threshold ({min_order:.2f}). "
                f"Violations: {'; '.join(order_res['violations'])}"
            )

        if efficiency_res["score"] < min_eff:
            failures.append(
                f"Trajectory Efficiency ({efficiency_res['score']:.2f}) < threshold ({min_eff:.2f}). "
                f"Total steps: {efficiency_res['total_steps']}, Redundant calls: {efficiency_res['redundant_calls']}"
            )

        is_passed = len(failures) == 0

        report = {
            "scenario_id": scenario_id,
            "title": title,
            "domain": domain,
            "status": "PASSED" if is_passed else "FAILED",
            "composite_score": composite_score,
            "metrics": {
                "tool_selection": tool_sel_res["score"],
                "argument_correctness": arg_corr_res["score"],
                "call_ordering": order_res["score"],
                "step_efficiency": efficiency_res["score"],
                "reasoning_faithfulness": reasoning_res["score"],
            },
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

        log_fn = logger.info if is_passed else logger.warning
        log_fn(
            "Scenario %s: %s (Composite: %.2f | Tools: %.2f, Args: %.2f, Order: %.2f, Eff: %.2f)",
            scenario_id, report["status"], composite_score,
            tool_sel_res["score"], arg_corr_res["score"], order_res["score"], efficiency_res["score"],
        )

        return report
