"""Scenario, trace step and report models, and the report file the dashboard reads."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Where reports are saved for the dashboard, relative to the working directory
DEFAULT_REPORT_PATH = os.path.join("reports", "latest_report.json")


@dataclass
class StepTrace:
    """One tool call in a trace. Pattern events (plans, handoffs...) are plain dicts."""

    step_index: int
    thought: str = ""
    action_name: str = ""
    action_args: dict[str, Any] = field(default_factory=dict)
    observation: Any = ""
    agent: str | None = None           # which agent acted (multi-agent traces)
    node: str | None = None            # graph node the step ran in
    parallel_group: str | None = None  # steps sharing a group ran concurrently

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "step_index": self.step_index,
            "thought": self.thought,
            "action": {"type": "tool_call", "name": self.action_name, "args": self.action_args},
            "observation": self.observation,
        }
        for key in ("agent", "node", "parallel_group"):
            if getattr(self, key) is not None:
                data[key] = getattr(self, key)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepTrace:
        action = data.get("action") or {}
        return cls(
            step_index=data.get("step_index", 1),
            thought=data.get("thought", ""),
            action_name=action.get("name", ""),
            action_args=action.get("args") or action.get("arguments") or {},
            observation=data.get("observation", ""),
            agent=data.get("agent"),
            node=data.get("node"),
            parallel_group=data.get("parallel_group"),
        )


@dataclass
class ScenarioSpec:
    """What the agent should do. Every rule is optional; unset rules aren't checked."""

    scenario_id: str = "scenario"
    title: str = ""
    domain: str = ""
    goal: str = ""                     # also given to the LLM judge
    expected_tools: list[str] = field(default_factory=list)
    expected_arguments: dict[str, dict[str, Any]] = field(default_factory=dict)
    expected_order: list[Any] = field(default_factory=list)
    optimal_step_count: int | None = None
    # Agentic pattern rules (see regression_shield/core/patterns.py)
    forbidden_tools: list[str] = field(default_factory=list)
    max_tool_calls: dict[str, int] = field(default_factory=dict)
    requires_approval: list[str] = field(default_factory=list)
    require_plan: bool = False
    expected_plan: list[str] = field(default_factory=list)
    agent_tools: dict[str, list[str]] = field(default_factory=dict)
    expected_agents: list[str] = field(default_factory=list)
    max_handoffs: int | None = None
    expected_route: str | list[str] | None = None
    expected_parallel: list[list[str]] = field(default_factory=list)
    allowed_transitions: dict[str, list[str]] = field(default_factory=dict)
    max_node_visits: int | dict[str, int] | None = None
    max_revision_rounds: int | None = None
    # Policy on argument values, and tools that must succeed before others may run
    forbidden_arguments: dict[str, dict[str, Any]] = field(default_factory=dict)
    prerequisites: dict[str, list[str]] = field(default_factory=dict)
    # Budget for one run (needs recorded LLM usage or paid tool calls)
    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_llm_calls: int | None = None
    warn_only: list[str] = field(default_factory=list)  # checks that warn instead of failing
    metadata: dict[str, Any] = field(default_factory=dict)  # free-form, not checked

    def __post_init__(self) -> None:
        # Rules are checked when the scenario is built, so a bad one can't pass silently
        if not isinstance(self.forbidden_arguments, dict):
            raise ValueError("forbidden_arguments must be {tool: {argument: pattern}}")
        for tool, params in self.forbidden_arguments.items():
            if not isinstance(params, dict):
                raise ValueError(f"forbidden_arguments['{tool}'] must be {{argument: pattern or [patterns]}}")
            for param, rule in params.items():
                for pattern in [rule] if isinstance(rule, str) else rule if isinstance(rule, list) else [None]:
                    if not isinstance(pattern, str):
                        raise ValueError(f"forbidden_arguments['{tool}']['{param}'] must be a regular expression "
                                         "or a list of them")
                    try:
                        re.compile(pattern)
                    except re.error as err:
                        raise ValueError(f"forbidden_arguments['{tool}']['{param}']: invalid regular expression "
                                         f"{pattern!r}: {err}") from err
        if not isinstance(self.prerequisites, dict):
            raise ValueError("prerequisites must be {tool: [tools that must succeed first]}")
        self.prerequisites = {tool: [needs] if isinstance(needs, str) else list(needs)
                              for tool, needs in self.prerequisites.items()}
        for limit in ("max_cost_usd", "max_tokens", "max_llm_calls"):
            value = getattr(self, limit)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise ValueError(f"{limit} must be a number >= 0, got {value!r}")
        unknown = sorted(set(self.warn_only) - CHECK_KEYS)
        if unknown:
            raise ValueError(f"warn_only has unknown check(s) {unknown}. Valid: {', '.join(sorted(CHECK_KEYS))}")

    def to_dict(self) -> dict[str, Any]:
        """The fields that are set (empty and unset rules are left out; a limit of 0 is kept)."""
        return {f.name: getattr(self, f.name) for f in fields(self) if not _unset(getattr(self, f.name))}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioSpec:
        # A misspelled rule would silently not be enforced, so reject unknown fields
        names = [f.name for f in fields(cls)]
        unknown = set(data) - set(names)
        if unknown:
            raise ValueError(f"Unknown scenario field(s) {sorted(unknown)}. "
                             f"Put extra information under 'metadata'. Valid fields: {', '.join(names)}")
        return cls(**data)


# What warn_only can name: the five metrics, the pattern checks and the LLM judge
METRIC_KEYS = ("tool_selection", "argument_correctness", "call_ordering", "step_efficiency", "reasoning_faithfulness")
PATTERN_KEYS = ("policy", "human_approval", "plan_execute", "multi_agent", "routing", "parallel", "graph",
                "reflection", "budget")
CHECK_KEYS = frozenset((*METRIC_KEYS, *PATTERN_KEYS, "llm_judge"))


def _unset(value: Any) -> bool:
    """None, False and empty values are unset; 0 is a real limit (e.g. max_handoffs: 0)."""
    return value is None or value is False or (isinstance(value, (str, list, dict)) and not value)


class EvaluationFailed(AssertionError):
    """Raised by ``EvaluationReport.raise_for_failures``. Test runners show it as a failed assertion."""

    def __init__(self, report: EvaluationReport):
        self.report = report
        lines = "\n".join(f"  - {failure}" for failure in report.failures)
        super().__init__(f"{report.scenario_id} failed:\n{lines}")


@dataclass
class EvaluationReport:
    """The result of evaluating one trace."""

    scenario_id: str
    status: str  # "PASSED" or "FAILED"
    composite_score: float
    metrics: dict[str, float]
    failures: list[str]
    patterns: dict[str, Any] = field(default_factory=dict)
    judge_audit: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    domain: str = ""
    warnings: list[str] = field(default_factory=list)  # failures of checks listed in warn_only

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"

    @property
    def cost(self) -> dict[str, Any] | None:
        """Tokens and cost of the run (``details["cost"]``), or None when no usage was recorded."""
        return self.details.get("cost")

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict of the report."""
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "domain": self.domain,
            "status": self.status,
            "composite_score": self.composite_score,
            "metrics": self.metrics,
            "patterns": self.patterns,
            "failures": self.failures,
            "warnings": self.warnings,
            "judge_audit": self.judge_audit,
            "details": self.details,
        }

    def format(self) -> str:
        """Readable summary: status, metrics, pattern checks, cost, judge verdict, failures and warnings."""
        from regression_shield.core.cost import describe_cost

        name = f"{self.scenario_id}  {self.title}" if self.title else self.scenario_id
        lines = [f"{self.status}  {name}  (composite {self.composite_score:.2f})"]
        lines += [f"  {metric:<24s}{value:.2f}" for metric, value in self.metrics.items()]
        if self.patterns:
            lines.append("  pattern checks: " + ", ".join(
                f"{p['label']} {'PASS' if p['passed'] else 'FAIL'}" for p in self.patterns.values()))
        if self.cost:
            lines.append(f"  cost: {describe_cost(self.cost)}")
        if self.judge_audit:
            score = self.judge_audit.get("score")
            score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
            lines.append(f"  LLM judge ({self.judge_audit.get('model')}): {score_text}  {self.judge_audit.get('reasoning', '')}")
        if self.failures:
            lines.append("Failures:")
            lines += [f"  - {failure}" for failure in self.failures]
        if self.warnings:
            lines.append("Warnings (warn_only):")
            lines += [f"  - {warning}" for warning in self.warnings]
        return "\n".join(lines)

    def raise_for_failures(self) -> EvaluationReport:
        """Raise ``EvaluationFailed`` if the evaluation failed; otherwise return the report."""
        if not self.passed:
            raise EvaluationFailed(self)
        return self

    def save(self, path: str | None = None) -> str:
        """Add this report to the report file the dashboard reads (replacing any
        earlier report with the same scenario_id). Returns the file's absolute path."""
        return save_reports([self], path)

    def sync_to_dashboard(self, url: str = "http://localhost:8000") -> bool:
        """Send this report to a running ``regshield serve`` dashboard. Returns True on success."""
        request = urllib.request.Request(
            f"{url.rstrip('/')}/api/reports",
            data=json.dumps(self.to_dict(), default=str).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status == 200
        except OSError as err:
            logger.warning("Could not send report to the dashboard at %s: %s", url, err)
            return False


@dataclass
class RunsReport:
    """Several runs of the same scenario (``evaluate_runs``): how reliably the agent passes.

    An agent that passes once can still fail the next run. ``pass_rate`` is the
    share of runs that passed; the scenario passes when it reaches ``min_pass_rate``
    (default 1.0: every run must pass, also called pass^k).
    """

    scenario_id: str
    reports: list[EvaluationReport]
    min_pass_rate: float = 1.0
    title: str = ""

    @property
    def runs(self) -> int:
        return len(self.reports)

    @property
    def passed_runs(self) -> int:
        return sum(report.passed for report in self.reports)

    @property
    def pass_rate(self) -> float:
        return round(self.passed_runs / self.runs, 4) if self.runs else 0.0

    @property
    def passed(self) -> bool:
        return self.runs > 0 and self.pass_rate + 1e-9 >= self.min_pass_rate

    @property
    def status(self) -> str:
        return "PASSED" if self.passed else "FAILED"

    @property
    def failure_counts(self) -> dict[str, int]:
        """How many runs each kind of failure appeared in, most frequent first."""
        counts: dict[str, int] = {}
        for report in self.reports:
            # "Argument correctness 0.00 < 0.85: ..." and "Policy: ..." group by the check's name
            kinds = {re.sub(r"\s+\d+(\.\d+)?\s*<\s*\d+(\.\d+)?$", "", failure.split(":", 1)[0])
                     for failure in report.failures}
            for kind in kinds:
                counts[kind] = counts.get(kind, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    @property
    def failures(self) -> list[str]:
        """Why the scenario failed: the pass rate, then each kind of failure with how many runs had it."""
        if self.passed:
            return []
        lines = [f"{self.passed_runs}/{self.runs} runs passed (pass rate {self.pass_rate:.2f}, "
                 f"required {self.min_pass_rate:.2f})"]
        lines += [f"{kind} in {count}/{self.runs} runs" for kind, count in self.failure_counts.items()]
        return lines

    @property
    def cost(self) -> dict[str, Any] | None:
        """Total and average cost of the runs that recorded usage."""
        costs = [report.cost for report in self.reports if report.cost]
        if not costs:
            return None
        total = round(sum(cost["total_usd"] for cost in costs), 6)
        return {"total_usd": total, "average_usd": round(total / len(costs), 6), "runs_with_usage": len(costs),
                "total_tokens": sum(cost["total_tokens"] for cost in costs),
                "complete": all(cost["complete"] for cost in costs)}

    def format(self) -> str:
        from regression_shield.core.cost import format_usd

        name = f"{self.scenario_id}  {self.title}" if self.title else self.scenario_id
        lines = [f"{self.status}  {name}  ({self.passed_runs}/{self.runs} runs passed, "
                 f"pass rate {self.pass_rate:.2f}, required {self.min_pass_rate:.2f})"]
        for number, report in enumerate(self.reports, 1):
            first = report.failures[0] if report.failures else ""
            more = f" (+{len(report.failures) - 1} more)" if len(report.failures) > 1 else ""
            lines.append(f"  run {number}: {report.status}" + (f"  {first}{more}" if first else ""))
        if self.cost:
            lines.append(f"  cost: {format_usd(self.cost['total_usd'])} total, "
                         f"{format_usd(self.cost['average_usd'])} per run")
        if self.failures:
            lines.append("Failures:")
            lines += [f"  - {failure}" for failure in self.failures]
        return "\n".join(lines)

    def raise_for_failures(self) -> RunsReport:
        """Raise ``EvaluationFailed`` if too few runs passed; otherwise return the report."""
        if not self.passed:
            raise EvaluationFailed(self)  # type: ignore[arg-type]
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "status": self.status,
            "runs": self.runs,
            "passed_runs": self.passed_runs,
            "pass_rate": self.pass_rate,
            "min_pass_rate": self.min_pass_rate,
            "failure_counts": self.failure_counts,
            "cost": self.cost,
            "reports": [report.to_dict() for report in self.reports],
        }


def load_report_file(path: str | None = None) -> dict[str, Any]:
    """The report file's contents, or an empty report if it doesn't exist or can't be read."""
    target = path or DEFAULT_REPORT_PATH
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"results": [], "regression_results": []}


def save_reports(
    reports: Sequence[EvaluationReport | dict[str, Any]],
    path: str | None = None,
    *,
    regression_reports: Sequence[EvaluationReport | dict[str, Any]] | None = None,
    replace: bool = False,
) -> str:
    """Write reports to the dashboard's report file.

    Reports are merged by scenario_id into what's already there, unless
    ``replace`` is set. ``regression_reports`` are regressed variants of the same
    scenarios, shown side by side in the dashboard. Returns the absolute path.
    """
    target = os.path.abspath(path or DEFAULT_REPORT_PATH)
    data = {"results": [], "regression_results": []} if replace else load_report_file(target)

    def merge(key: str, new: Sequence[EvaluationReport | dict[str, Any]]) -> None:
        new_dicts = [r.to_dict() if isinstance(r, EvaluationReport) else r for r in new]
        ids = {r.get("scenario_id") for r in new_dicts}
        data[key] = [r for r in data.get(key, []) if r.get("scenario_id") not in ids] + new_dicts

    merge("results", reports)
    if regression_reports is not None:
        merge("regression_results", regression_reports)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    logger.debug("Saved %d report(s) to %s", len(reports), target)
    return target
