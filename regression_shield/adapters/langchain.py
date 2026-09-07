"""LangChain Callback Tracer Adapter for RegressionShield SDK."""

from typing import Dict, Any, List, Optional
from regression_shield.models import StepTrace, ScenarioSpec, EvaluationReport
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator


class RegressionShieldCallbackHandler:
    """LangChain Callback Handler that records agent tool calls, thoughts,
    and observations to evaluate against RegressionShield policy scenarios.

    Usage:
        handler = RegressionShieldCallbackHandler()
        agent_executor.invoke({"input": "..."}, config={"callbacks": [handler]})
        report = handler.evaluate(scenario_spec)
        report.print_diagnostics()
    """

    def __init__(self):
        self.steps: List[StepTrace] = []
        self._current_step_idx = 1
        self._last_thought = ""
        self._current_tool_name = ""
        self._current_tool_args = {}

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Capture LLM intermediate thoughts before tool execution."""
        try:
            generations = getattr(response, "generations", [])
            if generations and generations[0]:
                text = getattr(generations[0][0], "text", "") or ""
                self._last_thought = text.strip()
        except Exception:
            pass

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Capture tool invocation name and arguments."""
        self._current_tool_name = serialized.get("name", "") or kwargs.get("name", "")
        inputs = kwargs.get("inputs")
        if isinstance(inputs, dict):
            self._current_tool_args = inputs
        elif isinstance(input_str, str):
            import json
            try:
                self._current_tool_args = json.loads(input_str)
            except Exception:
                self._current_tool_args = {"input": input_str}
        else:
            self._current_tool_args = {}

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Record completed tool step."""
        step = StepTrace(
            step_index=self._current_step_idx,
            thought=self._last_thought,
            action_name=self._current_tool_name,
            action_args=self._current_tool_args,
            observation=str(output),
        )
        self.steps.append(step)
        self._current_step_idx += 1
        self._last_thought = ""
        self._current_tool_name = ""
        self._current_tool_args = {}

    def get_trajectory(self) -> List[Dict[str, Any]]:
        """Return the collected trajectory as standard dictionary steps."""
        return [s.to_dict() for s in self.steps]

    def evaluate(
        self, scenario: Any, final_response: str = ""
    ) -> EvaluationReport:
        """Evaluate the collected trajectory against a scenario policy."""
        evaluator = AgentTrajectoryEvaluator()
        raw_rep = evaluator.evaluate_scenario(
            scenario,
            {"steps": self.get_trajectory(), "final_response": final_response},
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
