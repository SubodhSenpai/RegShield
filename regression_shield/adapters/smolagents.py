"""Hugging Face smolagents Adapter for RegressionShield SDK."""

import json
from typing import Dict, Any, List, Optional
from regression_shield.models import StepTrace, EvaluationReport
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator


def extract_smolagents_trajectory(agent: Any) -> List[Dict[str, Any]]:
    """Extract standard ReAct trajectory from a Hugging Face smolagents ToolCallingAgent."""
    extracted = []
    step_idx = 1

    memory_steps = getattr(agent, "memory", None)
    steps_list = getattr(memory_steps, "steps", []) if memory_steps else []

    for step in steps_list:
        if hasattr(step, "tool_calls") and step.tool_calls:
            for tc in step.tool_calls:
                tool_name = getattr(tc, "name", "")
                if tool_name == "final_answer":
                    continue
                tool_args = getattr(tc, "arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        pass

                obs = getattr(step, "observations", "")
                thought = getattr(step, "model_output", "") or ""

                extracted.append({
                    "step_index": step_idx,
                    "thought": str(thought)[:400],
                    "action": {
                        "type": "tool_call",
                        "name": tool_name,
                        "args": tool_args,
                        "arguments": tool_args,
                    },
                    "observation": str(obs)[:400],
                })
                step_idx += 1

    return extracted


def evaluate_smolagent(
    agent: Any, scenario: Any, final_response: str = ""
) -> EvaluationReport:
    """Evaluate a finished smolagent run against a scenario policy specification."""
    steps = extract_smolagents_trajectory(agent)
    evaluator = AgentTrajectoryEvaluator()
    raw_rep = evaluator.evaluate_scenario(
        scenario, {"steps": steps, "final_response": final_response}
    )
    return EvaluationReport(
        scenario_id=raw_rep["scenario_id"],
        title=raw_rep["title"],
        domain=raw_rep["domain"],
        status=raw_rep["status"],
        composite_score=raw_rep["composite_score"],
        metrics=raw_rep["metrics"],
        failures=raw_rep["failures"],
        details=raw_rep["details"],
    )
