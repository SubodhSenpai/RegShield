"""``@shield``: evaluate every run of an agent function."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from regression_shield.core.evaluator import AgentTraceEvaluator
from regression_shield.models import EvaluationReport, ScenarioSpec


def shield(
    scenario: ScenarioSpec | dict[str, Any],
    *,
    get_trace: Callable[[], Any] | None = None,
    raise_on_failure: bool = False,
    **evaluator_options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., tuple[Any, EvaluationReport]]]:
    """Evaluate each call of the decorated function; it then returns ``(output, report)``.

    The function must return a trace (a list of steps, or a dict with ``steps``),
    or you pass ``get_trace``: a callable returning the trace, such as
    ``recorder.get_trace`` or ``handler.get_trace``. With ``raise_on_failure``,
    a failed evaluation raises ``EvaluationFailed``. Other keyword arguments
    (thresholds, judge settings) go to ``AgentTraceEvaluator``.

    Example:
        @shield(scenario, get_trace=recorder.get_trace, raise_on_failure=True)
        def run_agent(task): ...

        output, report = run_agent("Deploy to staging")
    """
    evaluator = AgentTraceEvaluator(**evaluator_options)

    def decorator(fn: Callable[..., Any]) -> Callable[..., tuple[Any, EvaluationReport]]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> tuple[Any, EvaluationReport]:
            output = fn(*args, **kwargs)
            if get_trace is not None:
                trace = get_trace()
            elif isinstance(output, list) or (isinstance(output, dict) and "steps" in output):
                trace = output
            else:
                raise TypeError(
                    f"@shield: '{fn.__name__}' returned {type(output).__name__}, not a trace. Return a list of "
                    "steps or a dict with 'steps', or pass get_trace= (e.g. get_trace=recorder.get_trace)."
                )
            report = evaluator.evaluate(scenario, trace)
            if raise_on_failure:
                report.raise_for_failures()
            return output, report

        return wrapper

    return decorator
