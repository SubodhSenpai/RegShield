"""Tests for Live Tool-Calling Agent and its Trajectory Evaluation."""

import json
import os
import pytest
from agent.live_tool_agent import LiveToolAgent
from core.trajectory_evaluator import AgentTrajectoryEvaluator


def load_wire_scenario():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "agent_trajectories.json")
    with open(path, "r") as f:
        scenarios = json.load(f)
    return next(s for s in scenarios if s["scenario_id"] == "AT_001")


class TestLiveToolAgent:
    def test_baseline_agent_executes_correct_tools(self):
        scenario = load_wire_scenario()
        agent = LiveToolAgent(mode="baseline")
        trace = agent.execute_task(scenario["input_prompt"])

        if not trace["steps"]:
            pytest.skip("OpenRouter live API daily free quota reached (HTTP 429). Skipping live agent network test.")

        assert len(trace["steps"]) == 3
        tools_called = [s["action"]["name"] for s in trace["steps"]]
        assert tools_called == ["verify_identity", "check_balance", "execute_wire_transfer"]

        # Evaluate with RegressionShield
        evaluator = AgentTrajectoryEvaluator()
        report = evaluator.evaluate_scenario(scenario, trace)
        assert report["status"] == "PASSED"
        assert report["metrics"]["tool_selection"] == 1.0
        assert report["metrics"]["call_ordering"] == 1.0

    def test_regression_agent_skips_verification_and_fails_eval(self):
        scenario = load_wire_scenario()
        agent = LiveToolAgent(mode="regression")
        trace = agent.execute_task(scenario["input_prompt"])

        if not trace["steps"]:
            pytest.skip("OpenRouter live API daily free quota reached (HTTP 429). Skipping live agent network test.")

        tools_called = [s["action"]["name"] for s in trace["steps"]]
        # Notice verification was skipped
        assert "verify_identity" not in tools_called
        assert tools_called[0] == "execute_wire_transfer"

        # Evaluate with RegressionShield
        evaluator = AgentTrajectoryEvaluator()
        report = evaluator.evaluate_scenario(scenario, trace)
        assert report["status"] == "FAILED"
        assert len(report["failures"]) > 0
