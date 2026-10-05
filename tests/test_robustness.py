"""Odd but possible inputs are evaluated instead of crashing (several crashed in 0.4.0)."""

import pytest

from regression_shield import evaluate_trace


@pytest.fixture(autouse=True)
def no_config(monkeypatch):
    monkeypatch.setenv("REGSHIELD_CONFIG", "")


SCENARIO = {"scenario_id": "odd", "expected_tools": ["lookup", "issue_refund"],
            "expected_arguments": {"issue_refund": {"amount": 50}}, "requires_approval": ["issue_refund"]}


@pytest.mark.parametrize("steps", [
    [{"action": {"name": "issue_refund", "args": ["a", "b"]}, "observation": "ok"}],      # list arguments
    [{"action": {"name": "issue_refund", "args": "amount=50"}, "observation": "ok"}],     # a bare string
    [{"action": "lookup", "observation": "ok"}],                                          # action as a string
    [{"action": {"type": "approval", "tool": 5, "approved": True}},                      # a non-string tool name
     {"action": {"name": "issue_refund"}, "observation": "ok"}],
    [{"thought": 42, "action": {"name": "lookup"}, "observation": "ERROR"}],              # a non-string thought
    [{"thought": ["refund processed"], "action": {"name": "lookup"}, "observation": "ok"}],
    [{"action": {"name": "lookup"}, "observation": "ok", "parallel_group": ["g"]},        # unhashable groups
     {"action": {"name": "issue_refund"}, "observation": "ok", "parallel_group": ["g"]}],
    [{"action": {"name": "lookup"}, "observation": b"ERROR: bytes"}],
    [{"action": {"name": "send_email", "args": {"body": None, "subject": 5}}, "observation": "ok"}],
])
def test_odd_steps_are_evaluated(steps):
    report = evaluate_trace(SCENARIO, {"steps": steps, "final_response": "Your refund has been processed."})
    assert report.status in ("PASSED", "FAILED")


def test_list_arguments_are_compared_as_input():
    trace = [{"action": {"name": "search", "args": "refund policy"}, "observation": "ok"}]
    assert evaluate_trace({"scenario_id": "s", "expected_arguments": {"search": {"input": "Refund Policy"}}}, trace).passed


def test_unhashable_parallel_groups_still_group():
    steps = [{"action": {"name": "weather"}, "observation": "ok", "parallel_group": ["g"]},
             {"action": {"name": "flights"}, "observation": "ok", "parallel_group": ["g"]}]
    assert evaluate_trace({"scenario_id": "s", "expected_parallel": [["weather", "flights"]]}, steps).passed


def test_malformed_usage_is_ignored_but_a_non_list_is_rejected():
    junk = [None, "x", {"model": None}, {"input_tokens": "lots"}, {"model": 5, "input_tokens": -3}]
    report = evaluate_trace({"scenario_id": "s"}, {"steps": [], "llm_calls": junk})
    assert report.cost["llm_calls"] == 3 and report.cost["total_tokens"] == 0
    with pytest.raises(TypeError, match="llm_calls must be a list"):
        evaluate_trace({"scenario_id": "s"}, {"steps": [], "llm_calls": {"model": "gpt-4o"}})
