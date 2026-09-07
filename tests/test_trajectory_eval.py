"""Tests for Agent Trajectory Evaluation and Component-Level Metrics."""

import json
import os
import pytest
from core.agent_metrics import (
    ToolSelectionMetric,
    ArgumentCorrectnessMetric,
    ToolCallOrderMetric,
    StepEfficiencyMetric,
    ReasoningFaithfulnessMetric,
    CompositeTrajectoryScore,
)
from core.trajectory_evaluator import AgentTrajectoryEvaluator


def load_trajectory_scenarios():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "agent_trajectories.json")
    with open(path, "r") as f:
        return json.load(f)


class TestToolSelectionMetric:
    def test_perfect_selection(self):
        expected = ["search", "format"]
        invoked = ["search", "format"]
        res = ToolSelectionMetric.evaluate(expected, invoked)
        assert res["score"] == 1.0
        assert res["precision"] == 1.0
        assert res["recall"] == 1.0
        assert len(res["missing"]) == 0
        assert len(res["unexpected"]) == 0

    def test_missing_and_unexpected_tools(self):
        expected = ["auth", "fetch_data", "send_email"]
        invoked = ["auth", "unauthorized_tool"]
        res = ToolSelectionMetric.evaluate(expected, invoked)
        assert res["score"] < 1.0
        assert "fetch_data" in res["missing"]
        assert "unauthorized_tool" in res["unexpected"]


class TestArgumentCorrectnessMetric:
    def test_matching_arguments(self):
        expected = {
            "transfer": {"account": "ACCT-123", "amount": 500}
        }
        trajectory = [
            {"action": {"type": "tool_call", "name": "transfer", "args": {"account": "ACCT-123", "amount": 500}}}
        ]
        res = ArgumentCorrectnessMetric.evaluate(expected, trajectory)
        assert res["score"] == 1.0
        assert len(res["mismatches"]) == 0

    def test_mismatched_arguments(self):
        expected = {
            "transfer": {"account": "ACCT-123", "amount": 500}
        }
        trajectory = [
            {"action": {"type": "tool_call", "name": "transfer", "args": {"account": "WRONG-ACCT", "amount": 100}}}
        ]
        res = ArgumentCorrectnessMetric.evaluate(expected, trajectory)
        assert res["score"] == 0.0
        assert len(res["mismatches"]) == 2


class TestToolCallOrderMetric:
    def test_strictly_ordered_calls(self):
        expected_order = ["auth", "query", "export"]
        invoked = ["auth", "query", "export"]
        res = ToolCallOrderMetric.evaluate(expected_order, invoked)
        assert res["score"] == 1.0
        assert len(res["violations"]) == 0

    def test_inverted_order_violation(self):
        expected_order = ["auth", "query", "export"]
        invoked = ["query", "auth", "export"]  # query ran before auth!
        res = ToolCallOrderMetric.evaluate(expected_order, invoked)
        assert res["score"] < 1.0
        assert len(res["violations"]) > 0


class TestStepEfficiencyMetric:
    def test_optimal_trajectory(self):
        trajectory = [
            {"action": {"type": "tool_call", "name": "tool_a", "args": {"x": 1}}},
            {"action": {"type": "tool_call", "name": "tool_b", "args": {"y": 2}}},
        ]
        res = StepEfficiencyMetric.evaluate(trajectory, optimal_steps=2)
        assert res["score"] == 1.0
        assert not res["loop_detected"]

    def test_redundant_loop_penalty(self):
        trajectory = [
            {"action": {"type": "tool_call", "name": "tool_a", "args": {"x": 1}}},
            {"action": {"type": "tool_call", "name": "tool_a", "args": {"x": 1}}},  # redundant duplicate
            {"action": {"type": "tool_call", "name": "tool_a", "args": {"x": 1}}},  # redundant duplicate
        ]
        res = StepEfficiencyMetric.evaluate(trajectory, optimal_steps=1)
        assert res["loop_detected"]
        assert res["redundant_calls"] == 2
        assert res["score"] < 0.70


class TestAgentTrajectoryEvaluator:
    @pytest.mark.parametrize("scenario", load_trajectory_scenarios(), ids=lambda s: s["scenario_id"])
    def test_baseline_trajectory_passes(self, scenario):
        evaluator = AgentTrajectoryEvaluator()
        report = evaluator.evaluate_scenario(scenario, scenario["baseline_trajectory"])
        assert report["status"] == "PASSED", f"Baseline scenario failed: {report['failures']}"
        assert report["composite_score"] >= 0.85

    @pytest.mark.parametrize("scenario", load_trajectory_scenarios(), ids=lambda s: s["scenario_id"])
    def test_regression_trajectory_fails(self, scenario):
        evaluator = AgentTrajectoryEvaluator()
        report = evaluator.evaluate_scenario(scenario, scenario["regression_trajectory"])
        assert report["status"] == "FAILED", "Regression scenario was expected to fail quality gates"
        assert len(report["failures"]) > 0
