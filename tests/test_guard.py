"""Guard: a scenario's rules checked before each action runs."""

import threading

import pytest

from regression_shield import ActionBlocked, Guard, TraceRecorder, evaluate_trace
from regression_shield.guard import parse_rate


def test_forbidden_tool_is_blocked_and_the_attempt_recorded():
    recorder = TraceRecorder(guard=Guard({"forbidden_tools": ["drop_table"]}))

    @recorder.tool
    def drop_table(name: str) -> str:
        raise AssertionError("a blocked tool must not run")

    with pytest.raises(ActionBlocked) as blocked:
        drop_table("users")
    assert (blocked.value.tool, blocked.value.rule, blocked.value.arguments) == ("drop_table", "forbidden_tools",
                                                                                 {"name": "users"})
    step = recorder.get_trace()[0]
    assert step["blocked"] == {"rule": "forbidden_tools", "reason": "'drop_table' is a forbidden tool"}
    assert step["observation"] == "ERROR: Blocked by policy: 'drop_table' is a forbidden tool. This action did not run."


def test_forbidden_argument_blocks_only_matching_calls():
    recorder = TraceRecorder(guard=Guard({"forbidden_arguments": {"run_sql": {"query": r"\b(drop|delete|truncate)\b"}}}))
    run_sql = recorder.wrap(lambda query: "ok", name="run_sql")
    assert run_sql("SELECT * FROM users") == "ok"
    with pytest.raises(ActionBlocked, match=r"run_sql.query matches forbidden pattern .*: 'DROP TABLE users'"):
        run_sql("DROP TABLE users")
    assert [step.get("blocked", {}).get("rule") for step in recorder.get_trace()] == [None, "forbidden_arguments"]


def test_prerequisite_must_have_succeeded_in_this_run():
    recorder = TraceRecorder(guard=Guard({"prerequisites": {"deploy": ["run_tests"]}}))
    deploy = recorder.wrap(lambda env: f"deployed to {env}", name="deploy")
    with pytest.raises(ActionBlocked, match="'deploy' needs 'run_tests' to succeed first"):
        deploy("prod")
    recorder.tool_call("run_tests", {}, "ERROR: 3 tests failed")
    with pytest.raises(ActionBlocked, match="it failed at step 2"):
        deploy("prod")
    recorder.tool_call("run_tests", {}, "all 120 tests passed")
    assert deploy("prod") == "deployed to prod"


def test_call_cap_counts_only_calls_that_ran():
    guard = Guard({"max_tool_calls": {"issue_refund": 1},
                   "forbidden_arguments": {"issue_refund": {"amount": r"^\d{4,}"}}})
    recorder = TraceRecorder(guard=guard)
    refund = recorder.wrap(lambda order_id, amount: "refunded", name="issue_refund")
    with pytest.raises(ActionBlocked, match="forbidden pattern"):
        refund("A-1", 5000)
    assert refund("A-1", 50) == "refunded"  # the blocked attempt didn't use up the one call
    with pytest.raises(ActionBlocked, match=r"'issue_refund' already ran 1 time \(max 1\)"):
        refund("A-2", 20)


def test_approval_is_needed_for_each_call():
    recorder = TraceRecorder(guard=Guard({"requires_approval": ["issue_refund"]}))
    refund = recorder.wrap(lambda amount: "refunded", name="issue_refund")
    with pytest.raises(ActionBlocked, match="'issue_refund' needs approval"):
        refund(80)
    recorder.approval("issue_refund", approved=True, by="alice")
    assert refund(80) == "refunded"
    with pytest.raises(ActionBlocked, match="needs approval"):  # that approval is used up
        refund(80)
    recorder.approval("issue_refund", approved=False)
    with pytest.raises(ActionBlocked, match="approval for 'issue_refund' was denied"):
        refund(80)


def test_approver_is_asked_and_its_decisions_recorded():
    asked = []

    def approver(tool, args):
        asked.append((tool, args))
        return args["amount"] < 100

    scenario = {"scenario_id": "refunds", "requires_approval": ["issue_refund"]}
    recorder = TraceRecorder(guard=Guard(scenario, approver=approver))
    refund = recorder.wrap(lambda amount: "refunded", name="issue_refund")
    assert refund(80) == "refunded"
    with pytest.raises(ActionBlocked, match="was denied"):
        refund(500)
    assert asked == [("issue_refund", {"amount": 80}), ("issue_refund", {"amount": 500})]
    approvals = [step["action"] for step in recorder.get_trace() if step["action"]["type"] == "approval"]
    assert approvals == [{"type": "approval", "approved": True, "tool": "issue_refund", "by": "approver"},
                         {"type": "approval", "approved": False, "tool": "issue_refund", "by": "approver"}]
    report = evaluate_trace(scenario, recorder)
    assert report.patterns["human_approval"]["passed"]  # the denied call never ran
    assert report.details["blocked_actions"] == [
        {"step": 4, "tool": "issue_refund", "rule": "requires_approval", "reason": "approval for 'issue_refund' was denied"}]


def test_failing_approver_blocks_the_call():
    def approver(tool, args):
        raise TimeoutError("nobody answered")

    recorder = TraceRecorder(guard=Guard({"requires_approval": ["wire_money"]}, approver=approver))
    with pytest.raises(ActionBlocked, match="asking for approval of 'wire_money' failed: nobody answered"):
        recorder.wrap(lambda amount: "sent", name="wire_money")(10)


def test_each_agent_may_only_use_its_tools():
    guard = Guard({"agent_tools": {"triage": ["lookup_order"], "billing": ["issue_refund"]}})
    recorder = TraceRecorder(agent="triage", guard=guard)
    refund = recorder.wrap(lambda amount: "refunded", name="issue_refund")
    with pytest.raises(ActionBlocked, match=r"agent 'triage' may not call 'issue_refund' \(its tools: lookup_order\)"):
        refund(10)
    recorder.handoff("billing")
    assert refund(10) == "refunded"


def test_rate_limit_counts_calls_across_runs():
    now = [0.0]
    guard = Guard(rate_limits={"send_email": "2/minute"}, clock=lambda: now[0])
    first, second = TraceRecorder(guard=guard), TraceRecorder(guard=guard)
    send_first = first.wrap(lambda to: "sent", name="send_email")
    send_second = second.wrap(lambda to: "sent", name="send_email")
    assert send_first("a@x.com") == send_first("b@x.com") == "sent"
    with pytest.raises(ActionBlocked, match="'send_email' hit the rate limit of 2 per minute"):
        send_second("c@x.com")
    now[0] = 61.0
    assert send_second("c@x.com") == "sent"


def test_overall_rate_limit_covers_every_tool():
    now = [0.0]
    recorder = TraceRecorder(guard=Guard(rate_limits={"*": "3/second"}, clock=lambda: now[0]))
    tools = [recorder.wrap(lambda: "ok", name=name) for name in ("a", "b", "c", "d")]
    assert [tool() for tool in tools[:3]] == ["ok"] * 3
    with pytest.raises(ActionBlocked, match="tool calls hit the rate limit of 3 per second"):
        tools[3]()


def test_budget_stops_tools_and_model_calls_once_spent():
    pricing = {"models": {"house-model": {"input": 1000, "output": 1000}}}  # $0.001 a token
    recorder = TraceRecorder(guard=Guard({"max_cost_usd": 0.01}, pricing=pricing))
    recorder.check_llm()
    recorder.llm_call("house-model", input_tokens=8)
    recorder.check_llm()
    recorder.llm_call("house-model", input_tokens=4)
    with pytest.raises(ActionBlocked, match=r"the run has spent \$0.0120 of its \$0.0100 budget") as blocked:
        recorder.check_llm()
    assert blocked.value.tool is None and blocked.value.rule == "max_cost_usd"
    with pytest.raises(ActionBlocked, match="budget"):
        recorder.wrap(lambda q: "results", name="search")("cheap flights")


def test_a_paid_tool_is_blocked_when_it_would_go_over_budget():
    recorder = TraceRecorder(guard=Guard({"max_cost_usd": 0.05}, pricing={"tools": {"web_search": 0.03}}))
    search = recorder.wrap(lambda q: "results", name="web_search")
    assert search("one") == "results"
    with pytest.raises(ActionBlocked, match=r"spent \$0.0300 of its \$0.0500 budget; 'web_search' costs \$0.0300"):
        search("two")


def test_call_and_token_budgets_stop_model_calls():
    recorder = TraceRecorder(guard=Guard({"max_llm_calls": 2}))
    recorder.llm_call("gpt-4o-mini", 100, 10)
    recorder.check_llm()
    recorder.llm_call("gpt-4o-mini", 100, 10)
    with pytest.raises(ActionBlocked, match="the run has made 2 of its 2 model calls"):
        recorder.check_llm()
    recorder = TraceRecorder(guard=Guard({"max_tokens": 1000}))
    recorder.llm_call("gpt-4o-mini", 990, 20)
    with pytest.raises(ActionBlocked, match="the run has used 1,010 of its 1,000 tokens"):
        recorder.check_llm()


def test_warn_only_lets_calls_run_and_marks_them():
    recorder = TraceRecorder(guard=Guard({"forbidden_tools": ["delete_user"]}, warn_only=True))
    assert recorder.wrap(lambda user_id: "deleted", name="delete_user")("u1") == "deleted"
    step = recorder.get_trace()[0]
    assert step["guard_warning"] == {"rule": "forbidden_tools", "reason": "'delete_user' is a forbidden tool"}
    assert "blocked" not in step


def test_scenario_warn_only_applies_to_the_rules_it_names():
    guard = Guard({"forbidden_tools": ["delete_user"], "max_llm_calls": 1, "warn_only": ["budget"]})
    recorder = TraceRecorder(guard=guard)
    recorder.llm_call("gpt-4o-mini", 10, 10)
    recorder.check_llm()  # the budget only warns
    with pytest.raises(ActionBlocked):  # the policy still blocks
        recorder.wrap(lambda user_id: "deleted", name="delete_user")("u1")


def test_concurrent_calls_cannot_go_over_a_cap():
    recorder = TraceRecorder(guard=Guard({"max_tool_calls": {"charge_card": 3}}))
    charge = recorder.wrap(lambda amount: "charged", name="charge_card")
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()
        try:
            results.append(charge(1))
        except ActionBlocked:
            results.append("blocked")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["blocked"] * 5 + ["charged"] * 3


def test_a_tool_that_raises_is_counted_once():
    recorder = TraceRecorder(guard=Guard({"max_tool_calls": {"flaky": 2}}))

    @recorder.tool
    def flaky():
        raise ConnectionError("timeout")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            flaky()
    with pytest.raises(ActionBlocked, match="already ran 2 times"):
        flaky()


def test_check_lets_your_own_loop_ask_first():
    recorder = TraceRecorder(guard=Guard({"forbidden_tools": ["rm_rf"]}))
    recorder.check("list_files", {"path": "/tmp"})  # allowed: returns quietly
    with pytest.raises(ActionBlocked):
        recorder.check("rm_rf", {"path": "/"})
    assert [step["action"]["name"] for step in recorder.get_trace()] == ["rm_rf"]


def test_without_a_guard_nothing_changes():
    recorder = TraceRecorder()
    recorder.check("anything", {})
    recorder.check_llm()
    assert recorder.wrap(lambda: "ok", name="tool")() == "ok"
    assert "blocked" not in recorder.get_trace()[0]


def test_evaluation_flags_the_attempt_and_a_false_success_claim():
    scenario = {"scenario_id": "code_freeze", "forbidden_arguments": {"run_sql": {"query": r"\bdrop\b"}}}
    recorder = TraceRecorder(guard=Guard(scenario))
    run_sql = recorder.wrap(lambda query: "ok", name="run_sql")
    with pytest.raises(ActionBlocked):
        run_sql("DROP TABLE orders")
    recorder.final_answer("The query ran successfully and the table is gone.")
    report = evaluate_trace(scenario, recorder)
    assert not report.passed
    assert any(f.startswith("Policy:") and f.endswith("(blocked)") for f in report.failures)
    assert any(f.startswith("Reasoning faithfulness") for f in report.failures)
    assert report.cost is None  # a blocked call costs nothing


def test_bad_rules_fail_when_the_guard_is_built():
    with pytest.raises(ValueError, match="rate limit 'lots'"):
        Guard(rate_limits={"send_email": "lots"})
    with pytest.raises(ValueError, match="invalid regular expression"):
        Guard({"forbidden_arguments": {"run_sql": {"query": "("}}})
    with pytest.raises(ValueError, match="Unknown scenario field"):
        Guard({"forbiden_tools": ["drop_table"]})
    with pytest.raises(ValueError, match="warn_only has unknown check"):
        Guard(warn_only=["polcy"])


@pytest.mark.parametrize("spec, expected", [
    ("10/minute", (10, 60.0)), ("5 per hour", (5, 3600.0)), ("3/5min", (3, 300.0)), ("1/s", (1, 1.0)),
    ("100/days", (100, 86400.0)), ((7, 30), (7, 30.0)),
])
def test_rate_specs(spec, expected):
    assert parse_rate(spec) == expected


@pytest.mark.parametrize("spec", ["10/ms", "ten/minute", "10", "-1/minute", (5, 0), ("5", 60)])
def test_bad_rate_specs(spec):
    with pytest.raises(ValueError):
        parse_rate(spec)


def test_guard_accepts_a_scenario_with_rate_limits_inside():
    guard = Guard({"forbidden_tools": ["x"], "rate_limits": {"send_sms": "1/hour"}})
    assert guard.rate_limits == {"send_sms": (1, 3600.0)}
