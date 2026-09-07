import pytest
from regression_shield.core.agent_metrics import (
    ToolSelectionMetric,
    ArgumentCorrectnessMetric,
    ToolCallOrderMetric,
    StepEfficiencyMetric,
    ReasoningFaithfulnessMetric,
    CompositeTrajectoryScore,
)
from regression_shield.core.trajectory_evaluator import AgentTrajectoryEvaluator


class TestToolSelectionMetric:
    def test_perfect_selection(self):
        result = ToolSelectionMetric.evaluate(
            expected_tools=["verify_identity", "check_balance"],
            invoked_tools=["verify_identity", "check_balance"],
        )
        assert result["score"] == 1.0
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert len(result["missing"]) == 0
        assert len(result["unexpected"]) == 0

    def test_missing_and_unexpected_tools(self):
        result = ToolSelectionMetric.evaluate(
            expected_tools=["verify_identity", "check_balance", "execute_transfer"],
            invoked_tools=["verify_identity", "check_balance", "unauthorized_tool"],
        )
        assert result["precision"] == round(2 / 3, 2)
        assert result["recall"] == round(2 / 3, 2)
        assert result["score"] == round(2 / 3, 2)
        assert "execute_transfer" in result["missing"]
        assert "unauthorized_tool" in result["unexpected"]

    def test_empty_expected_and_invoked(self):
        result = ToolSelectionMetric.evaluate([], [])
        assert result["score"] == 1.0


class TestArgumentCorrectnessMetric:
    def test_exact_arguments(self):
        expected = {
            "verify_identity": {"customer_id": "CUST-908"},
            "execute_transfer": {"amount": 4500.0, "recipient": "ACCT-9912"},
        }
        invoked_steps = [
            {"action": {"type": "tool_call", "name": "verify_identity", "args": {"customer_id": "CUST-908"}}},
            {"action": {"type": "tool_call", "name": "execute_transfer", "args": {"amount": 4500.0, "recipient": "ACCT-9912"}}},
        ]
        result = ArgumentCorrectnessMetric.evaluate(expected, invoked_steps)
        assert result["score"] == 1.0
        assert result["passed_checks"] == 3
        assert len(result["mismatches"]) == 0

    def test_argument_mismatches(self):
        expected = {
            "execute_transfer": {"amount": 4500.0, "recipient": "ACCT-9912"},
        }
        invoked_steps = [
            {"action": {"type": "tool_call", "name": "execute_transfer", "args": {"amount": 9999.0, "recipient": "ACCT-9912"}}},
        ]
        result = ArgumentCorrectnessMetric.evaluate(expected, invoked_steps)
        assert result["score"] == 0.5
        assert len(result["mismatches"]) == 1
        assert result["mismatches"][0]["param"] == "amount"


class TestToolCallOrderMetric:
    def test_valid_strict_ordering(self):
        expected_order = ["verify_identity", "check_balance", "execute_wire_transfer"]
        invoked = ["verify_identity", "check_balance", "execute_wire_transfer"]
        result = ToolCallOrderMetric.evaluate(expected_order, invoked)
        assert result["score"] == 1.0
        assert len(result["violations"]) == 0

    def test_out_of_order_execution(self):
        expected_order = ["verify_identity", "check_balance", "execute_wire_transfer"]
        # Executed transfer before checking balance or verifying identity
        invoked = ["execute_wire_transfer", "check_balance", "verify_identity"]
        result = ToolCallOrderMetric.evaluate(expected_order, invoked)
        assert result["score"] < 1.0
        assert len(result["violations"]) > 0


class TestStepEfficiencyMetric:
    def test_optimal_efficiency(self):
        steps = [
            {"action": {"type": "tool_call", "name": "verify_identity", "args": {"customer_id": "CUST-908"}}},
            {"action": {"type": "tool_call", "name": "check_balance", "args": {"account_id": "ACCT-4401"}}},
        ]
        result = StepEfficiencyMetric.evaluate(steps, optimal_steps=2)
        assert result["score"] == 1.0
        assert result["loop_detected"] is False
        assert result["redundant_calls"] == 0

    def test_loop_thrashing_detection(self):
        # Repeated identical tool calls
        steps = [
            {"action": {"type": "tool_call", "name": "fetch_metrics", "args": {"service": "payment"}}},
            {"action": {"type": "tool_call", "name": "fetch_metrics", "args": {"service": "payment"}}},
            {"action": {"type": "tool_call", "name": "fetch_metrics", "args": {"service": "payment"}}},
        ]
        result = StepEfficiencyMetric.evaluate(steps, optimal_steps=1)
        assert result["loop_detected"] is True
        assert result["redundant_calls"] == 2
        assert result["score"] < 0.70


class TestReasoningFaithfulnessMetric:
    def test_grounded_reasoning(self):
        steps = [
            {
                "step_index": 1,
                "thought": "Identity is verified, proceeding to balance check.",
                "action": {"type": "tool_call", "name": "check_balance", "args": {"account_id": "ACCT-4401"}},
                "observation": "{\"status\": \"VERIFIED\", \"primary_account\": \"ACCT-4401\"}",
            }
        ]
        result = ReasoningFaithfulnessMetric.evaluate(steps)
        assert result["score"] == 1.0
        assert len(result["anomalies"]) == 0

    def test_ungrounded_contradictory_thought(self):
        # Prior observation had error, but step 2 thought claimed success
        steps = [
            {
                "step_index": 1,
                "thought": "Checking balance.",
                "action": {"type": "tool_call", "name": "check_balance", "args": {"account_id": "ACCT-4401"}},
                "observation": "{\"error\": \"POLICY_VIOLATION: Account frozen\"}",
            },
            {
                "step_index": 2,
                "thought": "Account confirmed and funds available. Executing wire transfer now.",
                "action": {"type": "tool_call", "name": "execute_wire_transfer", "args": {}},
                "observation": "Transfer failed.",
            }
        ]
        result = ReasoningFaithfulnessMetric.evaluate(steps)
        assert result["score"] < 1.0
        assert len(result["anomalies"]) > 0


class TestCompositeTrajectoryScore:
    def test_composite_weights(self):
        metrics = {
            "tool_selection": 1.0,
            "argument_correctness": 1.0,
            "call_ordering": 1.0,
            "step_efficiency": 1.0,
            "reasoning_faithfulness": 1.0,
        }
        score = CompositeTrajectoryScore.calculate(metrics)
        assert score == 1.0

    def test_partial_composite(self):
        metrics = {
            "tool_selection": 0.5,
            "argument_correctness": 1.0,
            "call_ordering": 0.0,
            "step_efficiency": 1.0,
            "reasoning_faithfulness": 1.0,
        }
        score = CompositeTrajectoryScore.calculate(metrics)
        assert 0.0 < score < 1.0


class TestFullTrajectoryEvaluator:
    def test_evaluate_clean_trajectory(self):
        steps = [
            {
                "step_index": 1,
                "thought": "Verifying identity.",
                "action": {"type": "tool_call", "name": "verify_identity", "args": {"customer_id": "CUST-908"}},
                "observation": "VERIFIED",
            },
            {
                "step_index": 2,
                "thought": "Checking balance.",
                "action": {"type": "tool_call", "name": "check_balance", "args": {"account_id": "ACCT-4401"}},
                "observation": "AVAILABLE",
            },
        ]
        scenario = {
            "scenario_id": "AT_TEST",
            "title": "Test Wire Transfer",
            "domain": "Fintech",
            "expected_tools": ["verify_identity", "check_balance"],
            "expected_arguments": {
                "verify_identity": {"customer_id": "CUST-908"},
                "check_balance": {"account_id": "ACCT-4401"},
            },
            "expected_order": ["verify_identity", "check_balance"],
        }
        evaluator = AgentTrajectoryEvaluator()
        report = evaluator.evaluate_scenario(scenario, {"steps": steps, "final_response": "Success"})
        assert report["status"] == "PASSED"
        assert report["composite_score"] == 1.0
        assert report["details"]["steps"] == steps
        assert len(report["failures"]) == 0
