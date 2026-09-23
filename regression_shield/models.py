"""Scenario, trace step and report models, and the report file the dashboard reads."""

from __future__ import annotations

import json
import logging
import os
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
    metadata: dict[str, Any] = field(default_factory=dict)  # free-form, not checked

    def to_dict(self) -> dict[str, Any]:
        """The fields that are set (empty and unset rules are left out)."""
        return {f.name: getattr(self, f.name) for f in fields(self)
                if getattr(self, f.name) not in (None, False, "", [], {})}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioSpec:
        # A misspelled rule would silently not be enforced, so reject unknown fields
        names = [f.name for f in fields(cls)]
        unknown = set(data) - set(names)
        if unknown:
            raise ValueError(f"Unknown scenario field(s) {sorted(unknown)}. "
                             f"Put extra information under 'metadata'. Valid fields: {', '.join(names)}")
        return cls(**data)


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

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"

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
            "judge_audit": self.judge_audit,
            "details": self.details,
        }

    def format(self) -> str:
        """Readable summary: status, metrics, pattern checks, judge verdict and failures."""
        name = f"{self.scenario_id}  {self.title}" if self.title else self.scenario_id
        lines = [f"{self.status}  {name}  (composite {self.composite_score:.2f})"]
        lines += [f"  {metric:<24s}{value:.2f}" for metric, value in self.metrics.items()]
        if self.patterns:
            lines.append("  pattern checks: " + ", ".join(
                f"{p['label']} {'PASS' if p['passed'] else 'FAIL'}" for p in self.patterns.values()))
        if self.judge_audit:
            score = self.judge_audit.get("score")
            score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
            lines.append(f"  LLM judge ({self.judge_audit.get('model')}): {score_text}  {self.judge_audit.get('reasoning', '')}")
        if self.failures:
            lines.append("Failures:")
            lines += [f"  - {failure}" for failure in self.failures]
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
