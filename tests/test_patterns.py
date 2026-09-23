"""Agentic pattern checks."""

import json

import pytest

from regression_shield import evaluate_trace, run_pattern_checks
from regression_shield.server import SAMPLE_SCENARIOS_FILE


def tool(name, args=None, obs="ok", **extra):
    return {"action": {"type": "tool_call", "name": name, "args": args or {}}, "observation": obs, **extra}


def event(action, **extra):
    return {"action": action, **extra}


def check(scenario, steps, key):
    return run_pattern_checks(scenario, steps).get(key)


def test_plain_tool_calling_trace_runs_no_pattern_checks():
    report = evaluate_trace({"scenario_id": "plain", "expected_tools": ["a"]}, [tool("a")])
    assert report.patterns == {}


# -- policy --------------------------------------------------------------------------

def test_forbidden_tool_fails_even_when_every_expected_tool_ran():
    scenario = {"scenario_id": "wire", "expected_tools": ["verify", "transfer"], "forbidden_tools": ["delete_database"]}
    report = evaluate_trace(scenario, [tool("verify"), tool("transfer"), tool("delete_database")])
    assert not report.passed
    assert report.patterns["policy"]["violations"] == ["Step 3: called forbidden tool 'delete_database'"]


def test_max_tool_calls():
    result = check({"max_tool_calls": {"refund": 1}}, [tool("refund"), tool("refund", {"n": 2})], "policy")
    assert result["violations"] == ["'refund' was called 2 times (max 1)"]


# -- human approval ------------------------------------------------------------------

@pytest.mark.parametrize("steps, expected", [
    ([event({"type": "approval", "tool": "refund", "approved": True}), tool("refund")], []),
    ([tool("refund")], ["Step 1: 'refund' ran without approval"]),
    ([event({"type": "approval", "tool": "refund", "approved": False}), tool("refund")],
     ["Step 2: 'refund' ran after its approval was denied"]),
    ([event({"type": "approval", "approved": True}), tool("refund")], []),  # an approval not naming a tool
    ([event({"type": "approval", "tool": "refund", "approved": True}), tool("refund"), tool("refund", {"n": 2})],
     ["Step 3: 'refund' ran without approval"]),  # each approval covers one call
])
def test_human_approval(steps, expected):
    assert check({"requires_approval": ["refund"]}, steps, "human_approval")["violations"] == expected


def test_denied_approval_is_checked_without_configuration():
    steps = [event({"type": "approval", "tool": "deploy", "approved": False}), tool("deploy")]
    assert not check({}, steps, "human_approval")["passed"]


# -- plan and execute ----------------------------------------------------------------

def plan(*tools):
    return event({"type": "plan", "steps": list(tools)})


def test_plan_followed_with_replan_after_failure():
    steps = [plan("search", "book", "confirm"), tool("search"), tool("book", obs="ERROR: sold out"),
             plan("book", "confirm"), tool("book", {"flight": 2}), tool("confirm")]
    result = check({"require_plan": True, "expected_plan": ["search", "book"]}, steps, "plan_execute")
    assert result["passed"], result["violations"]
    assert result["details"]["replans"] == 1


def test_plan_violations():
    steps = [tool("search"), plan("search", "book", "confirm"), tool("book", obs="ERROR: sold out"),
             tool("weather"), tool("confirm")]
    violations = check({"require_plan": True}, steps, "plan_execute")["violations"]
    assert "Step 1: 'search' ran before any plan was made" in violations
    assert "Step 4: 'weather' is not in the plan" in violations
    assert "Step 4: continued with 'weather' after 'book' failed (step 3) without replanning" in violations
    assert "Planned step 'search' never ran" in violations


def test_missing_plan():
    assert check({"require_plan": True}, [tool("a")], "plan_execute")["violations"] == ["No plan was made"]


def test_plan_steps_can_be_dicts():
    steps = [event({"type": "plan", "steps": [{"tool": "search", "why": "find"}, {"tool": "book"}]}),
             tool("search"), tool("book")]
    assert check({"require_plan": True}, steps, "plan_execute")["passed"]


# -- multi-agent ---------------------------------------------------------------------

def test_multi_agent_infers_the_agent_after_a_handoff():
    steps = [tool("lookup", agent="triage"), event({"type": "handoff", "to": "billing"}, agent="triage"), tool("refund")]
    scenario = {"agent_tools": {"triage": ["lookup"], "billing": ["refund"]}, "expected_agents": ["triage", "billing"]}
    result = check(scenario, steps, "multi_agent")
    assert result["passed"], result["violations"]
    assert result["details"]["agents"] == ["triage", "billing"]


def test_multi_agent_violations():
    handoffs = [event({"type": "handoff", "to": t}) for t in ("billing", "triage", "billing", "triage")]
    scenario = {"agent_tools": {"triage": ["lookup"]}, "expected_agents": ["triage", "legal"], "max_handoffs": 2}
    violations = check(scenario, [tool("refund", agent="triage"), *handoffs], "multi_agent")["violations"]
    assert "Step 1: agent 'triage' called 'refund', which isn't in its allowed tools" in violations
    assert any(v.startswith("Expected agents triage -> legal") for v in violations)
    assert "4 handoffs (max 2)" in violations
    assert "Agents 'billing' and 'triage' handed off to each other 4 times" in violations


# -- routing -------------------------------------------------------------------------

@pytest.mark.parametrize("expected, route, passed", [
    ("billing", "billing", True), ("Billing", "billing ", True), (["billing", "refunds"], "refunds", True),
    ("billing", "technical", False),
])
def test_routing(expected, route, passed):
    assert check({"expected_route": expected}, [event({"type": "route", "to": route})], "routing")["passed"] is passed


def test_routing_without_a_decision():
    assert check({"expected_route": "billing"}, [tool("a")], "routing")["violations"] == ["No routing decision was recorded"]


# -- parallel ------------------------------------------------------------------------

def test_parallel_group_satisfies_expected_parallel_and_order():
    steps = [tool("weather", parallel_group="g"), tool("prices", parallel_group="g"), tool("summary")]
    scenario = {"scenario_id": "p", "expected_tools": ["weather", "prices", "summary"],
                "expected_parallel": [["weather", "prices"]],
                "expected_order": [["weather", "summary"], ["prices", "summary"]]}
    report = evaluate_trace(scenario, steps)
    assert report.passed, report.failures
    assert report.patterns["parallel"]["details"]["parallel_batches"] == [["weather", "prices"]]


def test_prerequisite_in_the_same_parallel_batch_is_an_order_violation():
    steps = [tool("weather"), tool("prices", parallel_group="g"), tool("summary", parallel_group="g")]
    report = evaluate_trace({"scenario_id": "p", "expected_order": [["prices", "summary"]]}, steps)
    assert any("'summary' (step 3) ran in parallel with its prerequisite 'prices' (step 2)" in f for f in report.failures)


def test_expected_parallel_violation():
    result = check({"expected_parallel": [["weather", "prices"]]}, [tool("weather"), tool("prices")], "parallel")
    assert result["violations"] == ["weather, prices should run in parallel but ran one after another"]


# -- graph ---------------------------------------------------------------------------

GRAPH = {"allowed_transitions": {"draft": ["review"], "review": ["draft", "publish"]}, "max_node_visits": {"review": 2}}


def nodes(*names):
    return [event({"type": "node", "name": n}, node=n) for n in names]


def test_graph_allowed_path():
    result = check(GRAPH, nodes("draft", "review", "draft", "review", "publish"), "graph")
    assert result["passed"], result["violations"]
    assert result["details"]["path"] == ["draft", "review", "draft", "review", "publish"]


def test_graph_violations():
    violations = check(GRAPH, nodes("draft", "publish", "review", "draft", "review", "draft", "review"), "graph")["violations"]
    assert "Step 2: 'draft' -> 'publish' is not an allowed transition" in violations
    assert "Step 3: 'publish' -> 'review' is not an allowed transition" in violations  # publish lists no edges
    assert "Node 'review' was entered 3 times (max 2)" in violations


def test_consecutive_steps_in_one_node_are_one_visit():
    steps = [*nodes("draft"), tool("write", node="draft"), *nodes("review")]
    assert check({"max_node_visits": 1}, steps, "graph")["passed"]


# -- reflection ----------------------------------------------------------------------

def draft(text):
    return event({"type": "draft", "content": text})


def critique(approved):
    return event({"type": "critique", "approved": approved, "feedback": "..."})


def test_reflection_loop_that_improves():
    steps = [draft("v1"), critique(False), draft("v2"), critique(True)]
    assert check({"max_revision_rounds": 3}, steps, "reflection")["passed"]


def test_reflection_violations():
    steps = [draft("v1"), critique(False), draft(" V1 "), critique(False)]
    violations = check({"max_revision_rounds": 1}, steps, "reflection")["violations"]
    assert violations == ["Step 3: revision is unchanged after the critique at step 2",
                          "Step 4: the final draft was rejected by the evaluator",
                          "2 review rounds (max 1)"]


# -- interplay with the core metrics -------------------------------------------------

def test_pattern_events_do_not_count_as_steps_for_efficiency():
    steps = [plan("a"), event({"type": "approval", "tool": "a", "approved": True}), tool("a"),
             event({"type": "handoff", "to": "x"}), event({"type": "critique", "approved": True})]
    report = evaluate_trace({"scenario_id": "e", "expected_tools": ["a"], "optimal_step_count": 1}, steps)
    assert report.metrics["step_efficiency"] == 1.0


def test_bundled_samples_baselines_pass_and_regressions_fail():
    with open(SAMPLE_SCENARIOS_FILE, encoding="utf-8") as f:
        items = json.load(f)
    covered = set()
    for item in items:
        baseline = evaluate_trace(item["scenario"], item["trace"])
        regression = evaluate_trace(item["scenario"], item["regression_trace"])
        assert baseline.passed, (item["scenario"]["scenario_id"], baseline.failures)
        assert not regression.passed, item["scenario"]["scenario_id"]
        covered |= set(baseline.patterns)
    assert covered == {"policy", "human_approval", "plan_execute", "multi_agent",
                       "routing", "parallel", "graph", "reflection"}


def test_graph_fan_out_layer_can_reach_the_next_node_from_any_branch():
    steps = [event({"type": "node", "name": "weather"}, node="weather", parallel_group="s1"),
             event({"type": "node", "name": "prices"}, node="prices", parallel_group="s1"),
             event({"type": "node", "name": "summary"}, node="summary")]
    result = check({"allowed_transitions": {"prices": ["summary"]}}, steps, "graph")
    assert result["passed"], result["violations"]
    assert result["details"]["path"] == [["weather", "prices"], "summary"]


def test_graph_transitions_without_any_nodes():
    assert check({"allowed_transitions": {"a": ["b"]}}, [tool("a")], "graph")["violations"] == [
        "No graph nodes were recorded"]


def test_checks_that_assert_nothing_are_not_reported():
    steps = [event({"type": "node", "name": "a"}, node="a"), tool("x", parallel_group="g"), tool("y", parallel_group="g"),
             event({"type": "route", "to": "billing"})]
    report = evaluate_trace({"scenario_id": "s"}, steps)
    assert report.patterns == {}


def test_configured_policy_is_reported_even_without_tool_calls():
    result = check({"forbidden_tools": ["drop_table"]}, [], "policy")
    assert result["passed"] and result["score"] == 1.0


def test_denied_tool_that_never_ran_passes_human_approval():
    steps = [event({"type": "approval", "tool": "refund", "approved": False})]
    assert check({}, steps, "human_approval")["passed"]


def test_a_handoff_the_target_never_acted_on_is_not_in_the_agent_chain():
    # The supervisor asked for two transfers in one turn; only triage actually ran
    steps = [event({"type": "handoff", "to": "triage"}, agent="supervisor"),
             event({"type": "handoff", "to": "billing"}, agent="supervisor"),
             tool("lookup", agent="triage"),
             event({"type": "handoff", "to": "billing"}, agent="supervisor")]
    result = check({"expected_agents": ["supervisor", "triage", "billing"]}, steps, "multi_agent")
    assert result["details"]["agents"] == ["supervisor", "triage", "supervisor", "billing"]
    assert result["passed"]
    assert len(result["details"]["handoffs"]) == 3


def test_untagged_actions_after_a_handoff_belong_to_its_target():
    steps = [event({"type": "handoff", "to": "billing"}), tool("refund")]
    result = check({"agent_tools": {"billing": ["refund"]}}, steps, "multi_agent")
    assert result["passed"] and result["details"]["agents"] == ["billing"]
