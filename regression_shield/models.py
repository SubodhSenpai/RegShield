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
    judge_audit: Optional[Dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation report to a JSON-serializable dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "domain": self.domain,
            "status": self.status,
            "composite_score": self.composite_score,
            "metrics": self.metrics,
            "failures": self.failures,
            "details": self.details,
            "judge_audit": self.judge_audit,
        }

    def save(self, filepath: Optional[str] = None) -> str:
        """Persist evaluation report to disk for local dashboard ingestion.

        Args:
            filepath: Target file path (defaults to reports/latest_report.json).

        Returns:
            Absolute path to the saved report file.
        """
        import os
        import json
        from datetime import datetime, timezone

        target = filepath or os.path.join(os.getcwd(), "reports", "latest_report.json")
        reports_dir = os.path.dirname(os.path.abspath(target))
        os.makedirs(reports_dir, exist_ok=True)

        existing_data: Dict[str, Any] = {}
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception:
                existing_data = {}

        report_dict = self.to_dict()
        b_list = existing_data.get("trace_baseline", [])
        # Replace if same scenario_id exists, otherwise append
        b_list = [sc for sc in b_list if sc.get("scenario_id") != self.scenario_id]
        b_list.append(report_dict)

        existing_data["trace_baseline"] = b_list
        existing_data["trajectory_baseline"] = b_list
        existing_data["timestamp"] = datetime.now(timezone.utc).isoformat()

        with open(target, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2)

        return os.path.abspath(target)

    def sync_to_dashboard(self, server_url: str = "http://localhost:8000") -> bool:
        """Send evaluation report to a running local RegressionShield dashboard server.

        Args:
            server_url: Base URL of the dashboard server.

        Returns:
            True if sync succeeded, False otherwise.
        """
        import json
        import urllib.request

        url = f"{server_url.rstrip('/')}/api/evaluate-trace"
        payload = json.dumps({
            "scenario_id": self.scenario_id,
            "title": self.title,
            "domain": self.domain,
            "trace": self.details.get("steps", []),
            "final_response": self.details.get("final_response", ""),
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status in (200, 201)
        except Exception:
            return False

    def print_diagnostics(self):
        """Prints a human-readable diagnostic report indicating agent failure points."""
        print(f"\n[{self.status}] Scenario {self.scenario_id}: {self.title}")
        print(f"Composite Score: {self.composite_score:.2f}")
        print("-" * 50)
        for metric_name, val in self.metrics.items():
            print(f"  * {metric_name:<24s}: {val:.2f}")

        if self.judge_audit and self.judge_audit.get("reasoning"):
            model_name = self.judge_audit.get("model", "LLM")
            j_score = self.judge_audit.get("score", 1.0)
            j_reason = self.judge_audit.get("reasoning", "")
            print(f"\n[Judge Audit - {model_name}]:")
            print(f"  Score: {j_score:.2f} | Reasoning: {j_reason}")

        if self.failures:
            print("\n[!] Failure Diagnoses (Where your agent went wrong):")
            for f in self.failures:
                print(f"  -> {f}")
        else:
            print("\n[OK] All agentic reasoning checks passed cleanly!")

