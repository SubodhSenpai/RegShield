"""Evaluates one agent trace against a scenario: core metrics, pattern checks, cost, optional LLM judge."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

from regression_shield.config import THRESHOLD_KEYS, load_config, setting
from regression_shield.core.cost import merge_pricing, summarize_cost
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
    check_budget,
    is_pattern_event,
    is_tool_call,
    run_pattern_checks,
    step_number,
)
from regression_shield.log import enable_logging
from regression_shield.models import EvaluationReport, RunsReport, ScenarioSpec, StepTrace

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


def trace_llm_calls(trace: Any) -> list[Any]:
    """The LLM usage records of a trace: ``llm_calls`` of a dict trace or of a recorder."""
    if isinstance(trace, dict):
        calls = trace.get("llm_calls")
    elif isinstance(trace, list) or trace is None:
        calls = None
    else:
        calls = getattr(trace, "llm_calls", None)
    if calls is not None and not isinstance(calls, list):
        raise TypeError(f"llm_calls must be a list of usage records; got {type(calls).__name__}")
    return list(calls or [])


def _scenario_tools(spec: dict[str, Any]) -> set[str]:
    """Every tool a scenario names, so claims about tools that never ran can be recognized."""
    tools: set[str] = set(spec.get("expected_tools") or [])
    tools |= set(spec.get("forbidden_tools") or []) | set(spec.get("requires_approval") or [])
    for key in ("expected_arguments", "max_tool_calls", "prerequisites"):
        tools |= set(spec.get(key) or {})
    for item in spec.get("expected_order") or []:
        tools |= set(item) if isinstance(item, (list, tuple)) else {item}
    for group in spec.get("expected_parallel") or []:
        tools |= set(group)
    for needed in (spec.get("prerequisites") or {}).values():
        tools |= set(needed)
    for allowed in (spec.get("agent_tools") or {}).values():
        tools |= set(allowed)
    tools |= {tool for tool in spec.get("forbidden_arguments") or {} if tool != "*"}
    return {str(tool) for tool in tools if isinstance(tool, str)}


def _join(items: list[str]) -> str:
    return "; ".join(items)


class AgentTraceEvaluator:
    """Evaluates agent traces against scenarios with fixed thresholds, judge settings and pricing.

    Any option left as None comes from the project config file (``[tool.regshield]``
    in pyproject.toml or ``regshield.toml``), then from the built-in default.

    Example:
        evaluator = AgentTraceEvaluator(min_step_efficiency=0.5)
        report = evaluator.evaluate(scenario, trace)
    """

    def __init__(
        self,
        *,
        min_tool_selection: float | None = None,
        min_argument_correctness: float | None = None,
        min_call_ordering: float | None = None,
        min_step_efficiency: float | None = None,
        min_reasoning_faithfulness: float | None = None,
        use_llm_judge: bool | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        judge_on_error: str | None = None,
        judge_timeout: float | None = None,
        pricing: dict[str, Any] | None = None,
    ):
        config = load_config()
        explicit = {"min_tool_selection": min_tool_selection, "min_argument_correctness": min_argument_correctness,
                    "min_call_ordering": min_call_ordering, "min_step_efficiency": min_step_efficiency,
                    "min_reasoning_faithfulness": min_reasoning_faithfulness}
        self.thresholds = {key.removeprefix("min_"): float(setting(key, explicit[key], config))
                           for key in THRESHOLD_KEYS}
        self.judge_on_error = setting("judge_on_error", judge_on_error, config)
        if self.judge_on_error not in JUDGE_ON_ERROR_CHOICES:
            raise ValueError(f"judge_on_error must be one of {JUDGE_ON_ERROR_CHOICES}, got {self.judge_on_error!r}")
        self.pricing = merge_pricing(config.get("pricing"), pricing)
        self.judge = None
        if setting("llm_judge", use_llm_judge, config):
            self.judge = LLMJudge(api_key=api_key, model=model, base_url=base_url, timeout=judge_timeout,
                                  pricing=self.pricing)
            if not self.judge.api_key:  # the judge also reads OPENROUTER_API_KEY / OPENAI_API_KEY
                raise ValueError("use_llm_judge=True needs an API key: pass api_key= or set "
                                 "OPENROUTER_API_KEY / OPENAI_API_KEY.")

    def evaluate(self, scenario: ScenarioSpec | dict[str, Any], trace: Any) -> EvaluationReport:
        """Evaluate one trace. ``trace`` is a list of steps, a dict with ``steps`` and
        ``final_response`` (and optionally ``llm_calls``), or a TraceRecorder / LangChain handler."""
        started = time.perf_counter()
        spec = (scenario if isinstance(scenario, ScenarioSpec) else ScenarioSpec.from_dict(scenario)).to_dict()
        steps, final_response = normalize_trace(trace)
        llm_calls = trace_llm_calls(trace)
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
        logger.debug("Evaluating '%s': %d steps, %d tool calls, %d LLM calls", scenario_id, len(steps), len(tools),
                     len(llm_calls))

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
        faithfulness = ReasoningFaithfulnessMetric.evaluate(steps, final_response, known_tools=_scenario_tools(spec),
                                                            batches=batches)

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
        problems: list[tuple[str, str]] = [  # (check, message)
            (name, f"{name.replace('_', ' ').capitalize()} {metrics[name]:.2f} < {minimum:.2f}: {explanations[name]}")
            for name, minimum in self.thresholds.items() if metrics[name] < minimum
        ]
        for name in metrics:
            logger.debug("  %-22s %.2f  %s", name, metrics[name], explanations[name])

        cost = summarize_cost(steps, llm_calls, self.pricing)
        patterns = run_pattern_checks(spec, steps)
        budget = check_budget(spec, cost)
        if budget is not None:
            patterns["budget"] = budget
            logger.debug("  pattern %-15s %s (%.2f)", "budget", "PASSED" if budget["passed"] else "FAILED",
                         budget["score"])
        problems += [(key, f"{p['label']}: {_join(p['violations'])}") for key, p in patterns.items() if not p["passed"]]

        judge_audit = None
        if self.judge:
            goal = spec.get("goal") or spec.get("title") or scenario_id
            judge_audit = self.judge.verify_reasoning_and_outcome(goal, steps, final_response)
            if judge_audit.get("error"):
                if self.judge_on_error == "fail":
                    problems.append(("llm_judge", f"LLM judge ({judge_audit['model']}) could not run: "
                                                  f"{judge_audit['error']}. Set judge_on_error='pass' "
                                                  "(--judge-on-error pass) to ignore judge errors."))
            elif not judge_audit["passed"]:
                problems.append(("llm_judge", f"LLM judge ({judge_audit['model']}): {judge_audit['reasoning']}"))

        warn_only = set(spec.get("warn_only") or [])
        failures = [message for check, message in problems if check not in warn_only]
        warnings = [message for check, message in problems if check in warn_only]
        score = composite_score(metrics)
        status = "FAILED" if failures else "PASSED"
        logger.info("'%s' %s (composite %.2f) in %.1f ms", scenario_id, status, score,
                    (time.perf_counter() - started) * 1000)

        details: dict[str, Any] = {
            "tool_calls": tools,
            "expected_tools": expected_tools,
            "tool_selection": tool_selection,
            "argument_correctness": arguments,
            "call_ordering": ordering,
            "step_efficiency": efficiency,
            "reasoning_faithfulness": faithfulness,
            "steps": steps,
            "final_response": final_response,
        }
        if cost is not None:
            details["cost"] = cost
        if llm_calls:
            details["llm_calls"] = llm_calls
        return EvaluationReport(
            scenario_id=scenario_id,
            title=spec.get("title") or "",
            domain=spec.get("domain") or "",
            status=status,
            composite_score=score,
            metrics=metrics,
            failures=failures,
            warnings=warnings,
            patterns=patterns,
            judge_audit=judge_audit,
            details=details,
        )

    def evaluate_runs(self, scenario: ScenarioSpec | dict[str, Any], traces: Iterable[Any],
                      min_pass_rate: float | None = None) -> RunsReport:
        """Evaluate several runs of the same scenario; see ``evaluate_runs``."""
        rate = float(setting("min_pass_rate", min_pass_rate))
        if not 0 <= rate <= 1:
            raise ValueError(f"min_pass_rate must be from 0 to 1, got {rate}")
        reports = [self.evaluate(scenario, trace) for trace in traces]
        if not reports:
            raise ValueError("evaluate_runs needs at least one trace")
        return RunsReport(scenario_id=reports[0].scenario_id, title=reports[0].title, reports=reports,
                          min_pass_rate=rate)


def evaluate_trace(
    scenario: ScenarioSpec | dict[str, Any],
    trace: Any,
    *,
    min_tool_selection: float | None = None,
    min_argument_correctness: float | None = None,
    min_call_ordering: float | None = None,
    min_step_efficiency: float | None = None,
    min_reasoning_faithfulness: float | None = None,
    use_llm_judge: bool | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    judge_on_error: str | None = None,
    judge_timeout: float | None = None,
    pricing: dict[str, Any] | None = None,
    save_report: bool | str = False,
    dashboard_url: str | None = None,
    verbose: bool = False,
) -> EvaluationReport:
    """Evaluate one agent trace against a scenario.

    Args:
        scenario: A dict or ``ScenarioSpec`` of rules. Unset rules aren't checked;
            unknown fields raise ``ValueError`` so a misspelled rule can't pass silently.
        trace: A list of steps, a dict with ``steps``, ``final_response`` and
            ``llm_calls`` (token usage), or anything with ``get_trace()`` (a
            ``TraceRecorder`` or the LangChain handler).
        min_*: Thresholds for the five core metrics (default 0.85, 0.85, 1.0, 0.70, 0.85).
        use_llm_judge: Also ask an LLM to judge the trace (needs an API key via
            ``api_key`` or OPENROUTER_API_KEY / OPENAI_API_KEY). ``model`` and
            ``base_url`` pick any OpenAI-compatible endpoint; ``judge_timeout`` is
            in seconds (default 30).
        judge_on_error: When the judge can't give a verdict: "fail" (default) or "pass".
        pricing: Your prices, ``{"models": {name: {"input", "output"}}, "tools": {name: usd}}``
            (USD per 1M tokens; per call for tools), over the bundled list prices.
        save_report: Add the report to the dashboard's report file: True for
            ``reports/latest_report.json``, or a path.
        dashboard_url: Also send the report to a running ``regshield serve``.
        verbose: Print RegShield's debug logs to stderr (same as REGSHIELD_LOG=debug).

    Options left as None come from the project config file (``[tool.regshield]``
    in pyproject.toml, or regshield.toml), then from the defaults.
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
        judge_timeout=judge_timeout,
        pricing=pricing,
    )
    report = evaluator.evaluate(scenario, trace)
    if save_report:
        report.save(save_report if isinstance(save_report, str) else None)
    if dashboard_url:
        report.sync_to_dashboard(dashboard_url)
    return report


def evaluate_runs(
    scenario: ScenarioSpec | dict[str, Any],
    traces: Iterable[Any],
    *,
    min_pass_rate: float | None = None,
    **options: Any,
) -> RunsReport:
    """Evaluate several runs of the same scenario and report how reliably they pass.

    Agents aren't deterministic: one passing run says little about the next. Record
    the same task several times and pass every trace. The scenario passes when the
    share of passing runs reaches ``min_pass_rate`` (default 1.0, every run must pass:
    pass^k). ``options`` are the ``evaluate_trace`` options (thresholds, judge, pricing).

    Example:
        traces = [run_agent("Refund order A-1") for _ in range(5)]
        evaluate_runs(SCENARIO, traces, min_pass_rate=0.8).raise_for_failures()
    """
    return AgentTraceEvaluator(**options).evaluate_runs(scenario, traces, min_pass_rate=min_pass_rate)
