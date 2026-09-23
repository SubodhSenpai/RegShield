"""The five core metrics."""

import pytest

from regression_shield.core.metrics import (
    WEIGHTS,
    ArgumentCorrectnessMetric,
    ReasoningFaithfulnessMetric,
    StepEfficiencyMetric,
    ToolCallOrderMetric,
    ToolSelectionMetric,
    claims_success,
    composite_score,
)


def call(name, args=None):
    return {"action": {"type": "tool_call", "name": name, "args": args or {}}}


class TestToolSelection:
    def test_exact_match(self):
        result = ToolSelectionMetric.evaluate(["verify", "check"], ["verify", "check"])
        assert (result["score"], result["missing"], result["unexpected"]) == (1.0, [], [])

    def test_missing_and_unexpected(self):
        result = ToolSelectionMetric.evaluate(["verify", "check", "transfer"], ["verify", "check", "delete"])
        assert result["score"] == round(2 / 3, 2)
        assert result["missing"] == ["transfer"] and result["unexpected"] == ["delete"]

    def test_nothing_expected_nothing_called(self):
        assert ToolSelectionMetric.evaluate([], [])["score"] == 1.0


class TestArgumentCorrectness:
    def test_numbers_compare_numerically_and_text_loosely(self):
        expected = {"transfer": {"amount": 4500, "currency": "usd", "mode": "wire_transfer"}}
        result = ArgumentCorrectnessMetric.evaluate(expected, [call("transfer", {"amount": "4500.0", "currency": "USD",
                                                                                   "mode": "Wire-Transfer"})])
        assert result["score"] == 1.0

    def test_best_matching_call_is_used(self):
        expected = {"transfer": {"amount": 4500, "to": "ACCT-9"}}
        trace = [call("transfer", {"amount": 1, "to": "X"}), call("transfer", {"amount": 4500, "to": "X"})]
        result = ArgumentCorrectnessMetric.evaluate(expected, trace)
        assert result["score"] == 0.5
        assert result["mismatches"] == [{"tool": "transfer", "param": "to", "expected": "ACCT-9", "actual": "X"}]

    def test_tool_never_called(self):
        result = ArgumentCorrectnessMetric.evaluate({"transfer": {"amount": 1}}, [call("other")])
        assert result["score"] == 0.0
        assert result["mismatches"][0]["actual"] == "<never called>"


class TestCallOrdering:
    def test_sequence_respected(self):
        assert ToolCallOrderMetric.evaluate(["a", "b", "c"], ["a", "b", "c"])["score"] == 1.0

    def test_inversion(self):
        result = ToolCallOrderMetric.evaluate(["test", "deploy"], ["deploy", "test"])
        assert result["score"] == 0.0
        assert result["violations"] == ["'deploy' (step 1) ran before its prerequisite 'test' (step 2)"]

    def test_single_pair_is_a_constraint(self):
        assert ToolCallOrderMetric.evaluate([["verify", "transfer"]], ["transfer", "verify"])["score"] == 0.0

    def test_partial_order_pairs(self):
        pairs = [["weather", "summary"], ["prices", "summary"]]
        assert ToolCallOrderMetric.evaluate(pairs, ["prices", "weather", "summary"])["score"] == 1.0

    def test_missing_tool_is_reported(self):
        result = ToolCallOrderMetric.evaluate(["test", "deploy"], ["deploy"])
        assert result["violations"] == ["'test' never ran ('test' must come before 'deploy')"]

    def test_same_parallel_batch_is_a_violation(self):
        result = ToolCallOrderMetric.evaluate([["prices", "summary"]], ["prices", "summary"], batches=[0, 0],
                                              step_numbers=[4, 5])
        assert result["violations"] == ["'summary' (step 5) ran in parallel with its prerequisite 'prices' (step 4)"]


class TestStepEfficiency:
    def test_optimal(self):
        assert StepEfficiencyMetric.evaluate([call("a"), call("b")], optimal_steps=2)["score"] == 1.0

    def test_repeated_identical_calls(self):
        result = StepEfficiencyMetric.evaluate([call("fetch", {"s": 1})] * 3, optimal_steps=1)
        assert result["redundant_calls"] == 2
        assert result["score"] < 0.7


def trace_after(observation, thought):
    return [
        {"step_index": 1, "thought": "Calling the tool.", "action": {"name": "send"}, "observation": observation},
        {"step_index": 2, "thought": thought, "action": {"name": "notify"}, "observation": "sent"},
    ]


class TestReasoningFaithfulness:
    @pytest.mark.parametrize("thought", [
        "Deployment succeeded, moving on.",
        "Transfer completed successfully.",
        "The refund went through.",
        "Account confirmed and funds available.",
    ])
    def test_success_claims_after_an_error_are_flagged(self, thought):
        result = ReasoningFaithfulnessMetric.evaluate(trace_after("ERROR: permission denied", thought))
        assert result["anomalies"] == ["Step 2: claims success right after an error"]

    @pytest.mark.parametrize("thought", [
        "The deploy was unsuccessful, retrying.",
        "Deployment did not succeed; escalating.",
        "Transfer was not successful.",
        "Error confirmed, escalating to on-call.",
        "The transfer failed; no success yet, retrying.",
    ])
    def test_acknowledging_the_error_is_fine(self, thought):
        assert ReasoningFaithfulnessMetric.evaluate(trace_after("ERROR: permission denied", thought))["score"] == 1.0

    @pytest.mark.parametrize("observation", [
        '{"status": "success", "error": null}',
        "{'status': 'ok', 'error': None}",
        '{"errors": [], "result": "sent"}',
        '{"error_count": 0}',
        "Build finished with 0 errors",
        "No errors found. Tests passed.",
        "error-free run",
    ])
    def test_results_reporting_no_error_are_not_errors(self, observation):
        result = ReasoningFaithfulnessMetric.evaluate(trace_after(observation, "Transfer completed successfully."))
        assert result["score"] == 1.0

    @pytest.mark.parametrize("observation", [
        '{"error": "insufficient funds"}',
        '{"error": null, "status": "error"}',
        '{"errors": ["timeout"]}',
        "403 Access Denied",
    ])
    def test_real_errors_are_errors(self, observation):
        result = ReasoningFaithfulnessMetric.evaluate(trace_after(observation, "Transfer completed successfully."))
        assert result["score"] < 1.0

    def test_final_response_is_checked_against_the_last_result(self):
        steps = [{"thought": "Deploying.", "action": {"name": "deploy"}, "observation": "ERROR: denied"}]
        bad = ReasoningFaithfulnessMetric.evaluate(steps, final_response="Deployment succeeded.")
        assert bad["anomalies"] == ["Final response claims success right after an error"]
        assert ReasoningFaithfulnessMetric.evaluate(steps, final_response="Deployment failed.")["score"] == 1.0

    def test_events_without_an_observation_keep_the_error_context(self):
        steps = [{"action": {"name": "transfer"}, "observation": "ERROR: insufficient funds"},
                 {"thought": "Transfer completed successfully.", "action": {"type": "handoff", "to": "notifier"}}]
        assert ReasoningFaithfulnessMetric.evaluate(steps)["score"] < 1.0


def test_composite_score_weights():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert composite_score(dict.fromkeys(WEIGHTS, 1.0)) == 1.0
    assert composite_score({**dict.fromkeys(WEIGHTS, 1.0), "call_ordering": 0.0}) == 0.8


def test_success_claim_after_a_denied_approval_is_flagged():
    trace = [{"action": {"type": "tool_call", "name": "check_policy"}, "observation": '{"refundable": true}'},
             {"action": {"type": "approval", "tool": "issue_refund", "approved": False}}]
    result = ReasoningFaithfulnessMetric.evaluate(trace, "Your refund has been processed.")
    assert result["anomalies"] == ["Final response claims success right after a denied approval"]
    honest = ReasoningFaithfulnessMetric.evaluate(trace, "The refund was rejected, so I couldn't issue it.")
    assert honest["anomalies"] == []


@pytest.mark.parametrize("text", ["The order has been processed.", "All done!", "Your transfer is all set.",
                                  "I've taken care of it."])
def test_generic_completion_phrases_count_as_success_claims(text):
    assert claims_success(text)


@pytest.mark.parametrize("text", ["The payment was not processed.", "What should be done next?"])
def test_non_claims(text):
    assert not claims_success(text)
