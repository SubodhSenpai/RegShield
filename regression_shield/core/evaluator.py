"""Evaluates one agent trace against a scenario: core metrics, pattern checks, optional LLM judge."""

from __future__ import annotations

import logging
import time
from typing import Any

from regression_shield.core.judge import LLMJudge
from regression_shield.core.metrics import (
    ArgumentCorrectnessMetric,
    ReasoningFaithfulnessMetric,
    StepEfficiencyMetric,
    ToolCallOrderMetric,
    ToolSelectionMetric,
    composite_score,
)
from regression_shield.core.patterns import (
    action_of,
    batch_indices,
    is_pattern_event,
    is_tool_call,
    run_pattern_checks,
    step_number,
)
from regression_shield.log import enable_logging
from regression_shield.models import EvaluationReport, ScenarioSpec, StepTrace

logger = logging.getLogger(__name__)

# What to do with a trace when the LLM judge is enabled but can't produce a verdict
JUDGE_ON_ERROR_CHOICES = ("fail", "pass")


def normalize_trace(trace: Any) -> tuple[list[dict[str, Any]], str]:
    """(steps, final_response) from a list of steps, a ``{"steps", "final_response"}`` dict,
    or any object with ``get_trace()`` (a TraceRecorder or the LangChain handler)."""
    if trace is None:
        return [], ""
    if not isinstance(trace, (list, dict)) and hasattr(trace, "get_trace"):
        trace = {"steps": trace.get_trace(), "final_response": getattr(trace, "final_response", "") or ""}
    if isinstance(trace, dict):
        steps, final_response = trace.get("steps") or [], trace.get("final_response") or ""
    elif isinstance(trace, list):
        steps, final_response = trace, ""
    else:
        raise TypeError(f"trace must be a list of steps, a dict with 'steps', or a recorder; got {type(trace).__name__}")
    normalized = [s.to_dict() if isinstance(s, StepTrace) else s for s in steps]
    for step in normalized:
        if not isinstance(step, dict):
            raise TypeError(f"each trace step must be a dict or StepTrace; got {type(step).__name__}")
    return normalized, str(final_response)


def _join(items: list[str]) -> str:
    return "; ".join(items)


class AgentTraceEvaluator:
    """Evaluates agent traces against scenarios with fixed thresholds and judge settings.

    Example:
        evaluator = AgentTraceEvaluator(min_step_efficiency=0.5)
        report = evaluator.evaluate(scenario, trace)
    """

    def __init__(
        self,
        *,
        min_tool_selection: float = 0.85,
        min_argument_correctness: float = 0.85,
        min_call_ordering: float = 1.00,
        min_step_efficiency: float = 0.70,
        min_reasoning_faithfulness: float = 0.85,
        use_llm_judge: bool = False,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        judge_on_error: str = "fail",
    ):
        if judge_on_error not in JUDGE_ON_ERROR_CHOICES:
            raise ValueError(f"judge_on_error must be one of {JUDGE_ON_ERROR_CHOICES}, got {judge_on_error!r}")
        self.thresholds = {
            "tool_selection": min_tool_selection,
            "argument_correctness": min_argument_correctness,
            "call_ordering": min_call_ordering,
            "step_efficiency": min_step_efficiency,
            "reasoning_faithfulness": min_reasoning_faithfulness,
        }
        self.judge = LLMJudge(api_key=api_key, model=model, base_url=base_url) if use_llm_judge else None
        if self.judge and not self.judge.api_key:  # the judge also reads OPENROUTER_API_KEY / OPENAI_API_KEY
            raise ValueError("use_llm_judge=True needs an API key: pass api_key= or set OPENROUTER_API_KEY / OPENAI_API_KEY.")
        self.judge_on_error = judge_on_error

    def evaluate(self, scenario: ScenarioSpec | dict[str, Any], trace: Any) -> EvaluationReport:
        """Evaluate one trace. ``trace`` is a list of steps, a dict with ``steps`` and
        ``final_response``, or a TraceRecorder / LangChain handler."""
        started = time.perf_counter()
        spec = (scenario if isinstance(scenario, ScenarioSpec) else ScenarioSpec.from_dict(scenario)).to_dict()
        steps, final_response = normalize_trace(trace)
        scenario_id = spec.get("scenario_id", "scenario")  # ScenarioSpec defaults it

        # Tool calls, with their step numbers and parallel batches
        batches = batch_indices(steps)
        tools: list[str] = []
        call_batches: list[int] = []
        call_steps: list[int] = []
        for position, (step, batch) in enumerate(zip(steps, batches, strict=True), 1):
            if is_tool_call(step):
                tools.append(action_of(step)["name"])
                call_batches.append(batch)
                call_steps.append(step_number(step, position))
        logger.debug("Evaluating '%s': %d steps, %d tool calls", scenario_id, len(steps), len(tools))

        expected_tools = spec.get("expected_tools") or []
        # Like every other rule, tool selection is only scored when the scenario sets it
        if expected_tools:
            tool_selection = ToolSelectionMetric.evaluate(expected_tools, tools)
        else:
            tool_selection = {"score": 1.0, "precision": 1.0, "recall": 1.0, "missing": [], "unexpected": [],
                              "checked": False}
        arguments = ArgumentCorrectnessMetric.evaluate(spec.get("expected_arguments") or {}, steps)
        ordering = ToolCallOrderMetric.evaluate(spec.get("expected_order") or [], tools,
                                                batches=call_batches, step_numbers=call_steps)
        # Pattern events (plans, handoffs, approvals...) aren't agent actions, so they don't count as steps
        optimal_steps = spec.get("optimal_step_count") or len(expected_tools) or 3
        efficiency = StepEfficiencyMetric.evaluate([s for s in steps if not is_pattern_event(s)], optimal_steps)
        faithfulness = ReasoningFaithfulnessMetric.evaluate(steps, final_response)

        metrics = {
            "tool_selection": tool_selection["score"],
            "argument_correctness": arguments["score"],
            "call_ordering": ordering["score"],
            "step_efficiency": efficiency["score"],
            "reasoning_faithfulness": faithfulness["score"],
        }
        explanations = {
            "tool_selection": ", ".join(
                part for part in (f"missing {tool_selection['missing']}" if tool_selection["missing"] else "",
                                  f"unexpected {tool_selection['unexpected']}" if tool_selection["unexpected"] else "")
                if part),
            "argument_correctness": _join([f"{m['tool']}.{m['param']} was {m['actual']!r}, expected {m['expected']!r}"
                                           for m in arguments["mismatches"]]),
            "call_ordering": _join(ordering["violations"]),
            "step_efficiency": f"{efficiency['total_steps']} steps for an optimal {efficiency['optimal_steps']}, "
                               f"{efficiency['redundant_calls']} repeated call(s)",
            "reasoning_faithfulness": _join(faithfulness["anomalies"]),
        }
        failures = [
            f"{name.replace('_', ' ').capitalize()} {metrics[name]:.2f} < {minimum:.2f}: {explanations[name]}"
            for name, minimum in self.thresholds.items() if metrics[name] < minimum
        ]
        for name in metrics:
            logger.debug("  %-22s %.2f  %s", name, metrics[name], explanations[name])

        patterns = run_pattern_checks(spec, steps)
        failures += [f"{p['label']}: {_join(p['violations'])}" for p in patterns.values() if not p["passed"]]

        judge_audit = None
        if self.judge:
            goal = spec.get("goal") or spec.get("title") or scenario_id
            judge_audit = self.judge.verify_reasoning_and_outcome(goal, steps, final_response)
            if judge_audit.get("error"):
                if self.judge_on_error == "fail":
                    failures.append(f"LLM judge ({judge_audit['model']}) could not run: {judge_audit['error']}. "
                                    "Set judge_on_error='pass' (--judge-on-error pass) to ignore judge errors.")
            elif not judge_audit["passed"]:
                failures.append(f"LLM judge ({judge_audit['model']}): {judge_audit['reasoning']}")

        score = composite_score(metrics)
        status = "FAILED" if failures else "PASSED"
        logger.info("'%s' %s (composite %.2f) in %.1f ms", scenario_id, status, score,
                    (time.perf_counter() - started) * 1000)
        return EvaluationReport(
            scenario_id=scenario_id,
            title=spec.get("title") or "",
            domain=spec.get("domain") or "",
            status=status,
            composite_score=score,
            metrics=metrics,
            failures=failures,
            patterns=patterns,
            judge_audit=judge_audit,
            details={
                "tool_calls": tools,
                "expected_tools": expected_tools,
                "tool_selection": tool_selection,
                "argument_correctness": arguments,
                "call_ordering": ordering,
                "step_efficiency": efficiency,
                "reasoning_faithfulness": faithfulness,
                "steps": steps,
                "final_response": final_response,
            },
        )


def evaluate_trace(
    scenario: ScenarioSpec | dict[str, Any],
    trace: Any,
    *,
    min_tool_selection: float = 0.85,
    min_argument_correctness: float = 0.85,
    min_call_ordering: float = 1.00,
    min_step_efficiency: float = 0.70,
    min_reasoning_faithfulness: float = 0.85,
    use_llm_judge: bool = False,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    judge_on_error: str = "fail",
    save_report: bool | str = False,
    dashboard_url: str | None = None,
    verbose: bool = False,
) -> EvaluationReport:
    """Evaluate one agent trace against a scenario.

    Args:
        scenario: A dict or ``ScenarioSpec`` of rules. Unset rules aren't checked;
            unknown fields raise ``ValueError`` so a misspelled rule can't pass silently.
        trace: A list of steps, a dict with ``steps`` and ``final_response``, or
            anything with ``get_trace()`` (a ``TraceRecorder`` or the LangChain handler).
        min_*: Thresholds for the five core metrics.
        use_llm_judge: Also ask an LLM to judge the trace (needs an API key via
            ``api_key`` or OPENROUTER_API_KEY / OPENAI_API_KEY). ``model`` and
            ``base_url`` pick any OpenAI-compatible endpoint.
        judge_on_error: When the judge can't give a verdict: "fail" (default) or "pass".
        save_report: Add the report to the dashboard's report file: True for
            ``reports/latest_report.json``, or a path.
        dashboard_url: Also send the report to a running ``regshield serve``.
        verbose: Print RegShield's debug logs to stderr (same as REGSHIELD_LOG=debug).
    """
    if verbose:
        enable_logging("DEBUG")
    evaluator = AgentTraceEvaluator(
        min_tool_selection=min_tool_selection,
        min_argument_correctness=min_argument_correctness,
        min_call_ordering=min_call_ordering,
        min_step_efficiency=min_step_efficiency,
        min_reasoning_faithfulness=min_reasoning_faithfulness,
        use_llm_judge=use_llm_judge,
        api_key=api_key,
        model=model,
        base_url=base_url,
        judge_on_error=judge_on_error,
    )
    report = evaluator.evaluate(scenario, trace)
    if save_report:
        report.save(save_report if isinstance(save_report, str) else None)
    if dashboard_url:
        report.sync_to_dashboard(dashboard_url)
    return report
