"""Convenience Decorator for Agent Trajectory Tracing."""

import functools
from typing import Callable, Any, Dict, Optional
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator
from regression_shield.models import EvaluationReport


def evaluate_agent_trace(
    scenario: Any,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    use_llm_judge: bool = False,
    **evaluator_kwargs: Any,
):
    """Decorator to automatically evaluate any function returning a trajectory dict or list of steps.

    Example:
        @evaluate_agent_trace(
            scenario={"expected_tools": ["verify_identity", "check_balance"]},
            model="minimax/minimax-m2.7:free"
        )
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
            evaluator = AgentTrajectoryEvaluator(
                api_key=api_key,
                model=model,
                base_url=base_url,
                use_llm_judge=use_llm_judge,
                **evaluator_kwargs,
            )
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
                judge_audit=raw_rep.get("judge_audit"),
            )
            return output, report
        return wrapper
    return decorator
