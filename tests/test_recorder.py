"""TraceRecorder: building traces and pattern events from any agent."""

import asyncio
import threading

import pytest

from regression_shield import TraceRecorder, evaluate_trace


def test_recorder_builds_a_pattern_trace():
    recorder = TraceRecorder(agent="triage")

    @recorder.tool
    def lookup(order_id: str, verbose: bool = False) -> dict:
        return {"status": "DELIVERED"}

    @recorder.tool(name="refund")
    def issue_refund(order_id, amount):
        raise ValueError("card expired")

    recorder.plan(["lookup", "refund"])
    recorder.thought("Need the order first.")
    lookup("A-1")
    recorder.handoff("billing")
    recorder.approval("refund", approved=True, by="lead@acme.com")
    with pytest.raises(ValueError):
        issue_refund("A-1", 25)
    recorder.final_answer("Refund failed: card expired.")

    trace = recorder.get_trace()
    assert [s["action"]["type"] for s in trace] == ["plan", "tool_call", "handoff", "approval", "tool_call"]
    assert trace[1] == {"step_index": 2, "agent": "triage", "thought": "Need the order first.",
                        "action": {"type": "tool_call", "name": "lookup", "args": {"order_id": "A-1", "verbose": False}},
                        "observation": {"status": "DELIVERED"}}
    assert trace[4]["agent"] == "billing"
    assert trace[4]["observation"] == "ERROR: ValueError: card expired"

    scenario = {"scenario_id": "rec", "expected_tools": ["lookup", "refund"], "requires_approval": ["refund"],
                "agent_tools": {"triage": ["lookup"], "billing": ["refund"]}}
    report = evaluate_trace(scenario, recorder)
    assert report.patterns["human_approval"]["passed"] and report.patterns["multi_agent"]["passed"]
    assert report.details["final_response"] == "Refund failed: card expired."


def test_parallel_graph_and_reflection_events():
    recorder = TraceRecorder()
    recorder.node("research")
    with recorder.parallel() as group:
        recorder.tool_call("weather", {"city": "SF"}, "sunny")
        recorder.tool_call("prices", {"to": "SFO"}, "$300")
    recorder.tool_call("summary")
    recorder.draft("v1")
    recorder.critique(approved=True)
    trace = recorder.get_trace()
    assert trace[1]["parallel_group"] == trace[2]["parallel_group"] == group
    assert "parallel_group" not in trace[3]
    assert all(step["node"] == "research" for step in trace)


def test_async_tools_and_reset():
    recorder = TraceRecorder(agent="main")

    @recorder.tool
    async def fetch(url: str) -> str:
        return "<html>"

    assert asyncio.run(fetch("https://example.com")) == "<html>"
    assert recorder.get_trace()[0]["action"]["args"] == {"url": "https://example.com"}
    recorder.handoff("other")
    recorder.reset()
    assert recorder.get_trace() == [] and recorder.current_agent == "main"


def test_non_json_results_are_stored_as_text():
    recorder = TraceRecorder()
    recorder.wrap(lambda: object(), name="make")()
    assert isinstance(recorder.get_trace()[0]["observation"], str)


def test_concurrent_calls_from_threads_are_all_recorded():
    recorder = TraceRecorder()
    work = recorder.wrap(lambda n: n * 2, name="work")
    with recorder.parallel():
        threads = [threading.Thread(target=work, args=(n,)) for n in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    trace = recorder.get_trace()
    assert len(trace) == 50
    assert sorted(s["step_index"] for s in trace) == list(range(1, 51))
    assert len({s["parallel_group"] for s in trace}) == 1
