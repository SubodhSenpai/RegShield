"""Data models and schemas for RegressionShield Agent Trajectory Evaluation."""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class StepTrace:
    """Represents a single step in an agent's ReAct execution chain."""
    step_index: int
    thought: str = ""
    action_name: str = ""
    action_args: Dict[str, Any] = field(default_factory=dict)
    observation: Any = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "thought": self.thought,
            "action": {
                "type": "tool_call",
                "name": self.action_name,
                "args": self.action_args,
                "arguments": self.action_args,
            },
            "observation": self.observation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepTrace":
        act = data.get("action", {})
        name = act.get("name", "") if isinstance(act, dict) else str(act)
        args = act.get("args") or act.get("arguments") or {} if isinstance(act, dict) else {}
        return cls(
            step_index=data.get("step_index", 1),
            thought=data.get("thought", ""),
            action_name=name,
            action_args=args,
            observation=data.get("observation", ""),
        )


@dataclass
class ScenarioSpec:
    """Evaluation specification defining policy expectations for an agent scenario."""
    scenario_id: str
    title: str = ""
    domain: str = "General"
    expected_tools: List[str] = field(default_factory=list)
    expected_arguments: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    expected_order: List[Any] = field(default_factory=list)
    optimal_step_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "domain": self.domain,
            "expected_tools": self.expected_tools,
            "expected_arguments": self.expected_arguments,
            "expected_order": self.expected_order,
            "optimal_step_count": self.optimal_step_count or len(self.expected_tools),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioSpec":
        return cls(
            scenario_id=data.get("scenario_id", "CUSTOM_SCENARIO"),
            title=data.get("title", ""),
            domain=data.get("domain", "General"),
            expected_tools=data.get("expected_tools", []),
            expected_arguments=data.get("expected_arguments", {}),
            expected_order=data.get("expected_order", []),
            optimal_step_count=data.get("optimal_step_count"),
        )


@dataclass
class EvaluationReport:
    """Comprehensive evaluation report detailing where and why an agent failed."""
    scenario_id: str
    title: str
    domain: str
    status: str  # "PASSED" or "FAILED"
    composite_score: float
    metrics: Dict[str, float]
    failures: List[str]
    details: Dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"

    def print_diagnostics(self):
        """Prints a human-readable diagnostic report indicating agent failure points."""
        print(f"\n[{self.status}] Scenario {self.scenario_id}: {self.title}")
        print(f"Composite Score: {self.composite_score:.2f}")
        print("-" * 50)
        for metric_name, val in self.metrics.items():
            print(f"  * {metric_name:<24s}: {val:.2f}")
        if self.failures:
            print("\n[!] Failure Diagnoses (Where your agent went wrong):")
            for f in self.failures:
                print(f"  -> {f}")
        else:
            print("\n[OK] All agentic reasoning checks passed cleanly!")
