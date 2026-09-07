"""Convenience Decorator for Agent Trajectory Tracing."""

import functools
from typing import Callable, Any, Dict
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator
from regression_shield.models import EvaluationReport


def evaluate_agent_trace(scenario: Any):
    """Decorator to automatically evaluate any function returning a trajectory dict or list of steps.

    Example:
        @evaluate_agent_trace(scenario={
            "expected_tools": ["verify_identity", "check_balance"],
            "expected_order": ["verify_identity", "check_balance"]
        })
        def my_agent(user_input: str):
            # run agent
            return {"steps": [...], "final_response": "..."}

        result, report = my_agent("check balance for CUST-101")
        print("Passed:", report.passed)
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            output = fn(*args, **kwargs)
            evaluator = AgentTrajectoryEvaluator()
            raw_rep = evaluator.evaluate_scenario(scenario, output)
            report = EvaluationReport(
                scenario_id=raw_rep["scenario_id"],
                title=raw_rep["title"],
                domain=raw_rep["domain"],
                status=raw_rep["status"],
                composite_score=raw_rep["composite_score"],
                metrics=raw_rep["metrics"],
                failures=raw_rep["failures"],
                details=raw_rep["details"],
            )
            return output, report
        return wrapper
    return decorator
