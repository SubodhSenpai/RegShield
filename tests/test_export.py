"""Live export: run events, sampling, rate limits and the exporters."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from regression_shield import (
    ActionBlocked,
    Exporter,
    Guard,
    HTTPExporter,
    JSONLExporter,
    TraceRecorder,
    evaluate_trace,
    export_stats,
    export_traces,
    stop_exporting,
)


class Collect(Exporter):
    """Keeps the events it gets."""

    def __init__(self, capture_content=False):
        self.capture_content = capture_content
        self.events = []

    def export(self, event):
        self.events.append(self.visible(event))


def support_run(recorder, *, fail=False):
    """A small run: a lookup, a refund (that may fail), a model call and an answer."""
    recorder.tool_call("lookup_order", {"order_id": "A-1"}, '{"status": "DELIVERED"}', thought="Check the order")
    recorder.tool_call("issue_refund", {"order_id": "A-1", "amount": 40},
                       "ERROR: payment gateway timeout" if fail else '{"status": "REFUNDED"}')
    recorder.llm_call("gpt-4o-mini", input_tokens=1200, output_tokens=80)
    recorder.final_answer("Your refund of $40 is on its way.")
    recorder.end_run()


def test_events_follow_the_run_and_leave_content_out_by_default():
    collect = Collect()
    export_traces(collect)
    support_run(TraceRecorder(agent="support"))
    kinds = [event["event"] for event in collect.events]
    assert kinds == ["run_start", "tool_call", "tool_call", "llm_call", "run_end"]
    start, lookup, refund, llm, end = collect.events
    assert start["agent"] == "support" and len({e["run_id"] for e in collect.events}) == 1
    assert (lookup["tool"], lookup["status"], lookup["step"]) == ("lookup_order", "ok", 1)
    assert "content" not in lookup  # arguments, results and thoughts stay out unless asked for
    assert (llm["model"], llm["input_tokens"], llm["output_tokens"]) == ("gpt-4o-mini", 1200, 80)
    assert llm["cost_usd"] == pytest.approx(0.000228)
    assert end["status"] == "ok" and (end["tool_calls"], end["errors"], end["llm_calls"]) == (2, 0, 1)
    assert end["cost_usd"] == pytest.approx(0.000228) and "content" not in end


def test_capture_content_includes_arguments_results_and_the_whole_trace(tmp_path):
    path = tmp_path / "runs.jsonl"
    export_traces(JSONLExporter(path, capture_content=True))
    support_run(TraceRecorder())
    stop_exporting()
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lookup = events[1]
    assert lookup["content"] == {"args": {"order_id": "A-1"}, "observation": '{"status": "DELIVERED"}',
                                 "thought": "Check the order"}
    trace = events[-1]["content"]["trace"]  # ready for a scenario file or evaluate_trace
    assert events[-1]["content"]["final_response"] == "Your refund of $40 is on its way."
    report = evaluate_trace({"scenario_id": "from_production", "expected_tools": ["lookup_order", "issue_refund"]}, trace)
    assert report.passed and report.cost["llm_calls"] == 1


def test_unsampled_runs_are_kept_only_when_something_goes_wrong():
    collect = Collect()
    export_traces(collect, sample_rate=0.0)  # keep_errors is on by default
    support_run(TraceRecorder())             # healthy: not exported
    support_run(TraceRecorder(), fail=True)  # a tool failed: exported in full
    kinds = [event["event"] for event in collect.events]
    assert kinds == ["run_start", "tool_call", "tool_call", "llm_call", "run_end"]
    assert collect.events[2]["status"] == "error"
    stats = export_stats()
    assert stats["runs_started"] == 2 and stats["runs_exported"] == 1
    assert stats["runs_sampled_out"] == 1 and stats["runs_kept_for_errors"] == 1


def test_sampling_without_keep_errors_drops_everything_unsampled():
    collect = Collect()
    export_traces(collect, sample_rate=0.0, keep_errors=False)
    support_run(TraceRecorder(), fail=True)
    assert collect.events == [] and export_stats()["runs_sampled_out"] == 1


def test_blocked_actions_and_guard_warnings_count_as_problems():
    collect = Collect()
    export_traces(collect, sample_rate=0.0)
    recorder = TraceRecorder(guard=Guard({"forbidden_tools": ["drop_table"]}))
    with pytest.raises(ActionBlocked):
        recorder.wrap(lambda: "dropped", name="drop_table")()
    recorder.end_run()
    warned = TraceRecorder(guard=Guard({"forbidden_tools": ["drop_table"]}, warn_only=True))
    warned.wrap(lambda: "dropped", name="drop_table")()
    warned.end_run()
    ends = [event for event in collect.events if event["event"] == "run_end"]
    assert [(e["status"], e["blocked"], e["warnings"]) for e in ends] == [("blocked", 1, 0), ("ok", 0, 1)]
    calls = [event for event in collect.events if event["event"] == "tool_call"]
    assert [(c["status"], c.get("blocked_rule"), c.get("warning_rule")) for c in calls] == [
        ("blocked", "forbidden_tools", None), ("ok", None, "forbidden_tools")]


def test_runs_per_minute_limit():
    collect = Collect()
    export_traces(collect, max_runs_per_minute=1)
    support_run(TraceRecorder())
    support_run(TraceRecorder())
    assert [e["event"] for e in collect.events].count("run_start") == 1
    assert export_stats()["runs_rate_limited"] == 1


def test_events_per_run_limit_marks_the_run_truncated():
    collect = Collect()
    export_traces(collect, max_events_per_run=2)
    support_run(TraceRecorder())
    assert [e["event"] for e in collect.events] == ["run_start", "tool_call", "run_end"]
    assert collect.events[-1]["truncated"] is True and export_stats()["events_dropped"] == 2


def test_a_failing_exporter_never_breaks_the_agent():
    class Broken(Exporter):
        def export(self, event):
            raise ConnectionError("collector down")

    collect = Collect()
    export_traces(Broken(), collect)
    support_run(TraceRecorder())
    assert len(collect.events) == 5 and export_stats()["export_errors"] == 5


def test_with_block_is_a_run_and_its_exception_is_reported():
    collect = Collect(capture_content=True)
    export_traces(collect)
    with pytest.raises(ZeroDivisionError):
        with TraceRecorder().start_run("nightly-report", user_id="u-42") as recorder:
            recorder.tool_call("fetch_sales", {}, "1,204 rows")
            recorder.final_answer(str(1 / 0))
    start, call, end = collect.events
    assert (start["name"], start["attributes"]) == ("nightly-report", {"user_id": "u-42"})
    assert (end["status"], end["error_type"], end["content"]["error"]) == ("error", "ZeroDivisionError", "division by zero")


def test_export_can_be_turned_off_per_recorder_and_stopped():
    collect = Collect()
    export_traces(collect)
    support_run(TraceRecorder(export=False))
    assert collect.events == []
    stop_exporting()
    support_run(TraceRecorder())
    assert collect.events == [] and export_stats() == {}


def test_pattern_events_are_exported():
    collect = Collect(capture_content=True)
    export_traces(collect)
    recorder = TraceRecorder(agent="triage")
    recorder.plan(["lookup_order", "issue_refund"])
    recorder.handoff("billing")
    recorder.approval("issue_refund", approved=True, by="alice")
    recorder.end_run()
    plan, handoff, approval = collect.events[1:4]
    assert plan["content"] == {"steps": ["lookup_order", "issue_refund"]}
    assert (handoff["event"], handoff["to"]) == ("handoff", "billing")
    assert (approval["tool"], approval["approved"], approval["by"], approval["agent"]) == (
        "issue_refund", True, "alice", "billing")


def test_bad_export_settings_are_rejected():
    with pytest.raises(ValueError, match="at least one exporter"):
        export_traces()
    with pytest.raises(ValueError, match="sample_rate"):
        export_traces(Collect(), sample_rate=1.5)
    with pytest.raises(ValueError, match="max_runs_per_minute"):
        export_traces(Collect(), max_runs_per_minute=-1)
    with pytest.raises(TypeError, match="not an Exporter"):
        export_traces(print)


# -- OpenTelemetry ----------------------------------------------------------------------

otel = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import StatusCode  # noqa: E402

from regression_shield import OpenTelemetryExporter  # noqa: E402


def spans_of(run, **options):
    memory = InMemorySpanExporter()
    export_traces(OpenTelemetryExporter(span_exporter=memory, **options))
    run()
    stop_exporting()
    return {span.name: span for span in memory.get_finished_spans()}


def test_runs_become_genai_spans():
    def run():
        recorder = TraceRecorder(agent="support", guard=Guard({"forbidden_tools": ["delete_account"]}))
        recorder.tool_call("lookup_order", {"order_id": "A-1"}, '{"status": "DELIVERED"}')
        recorder.llm_call("gpt-4o-mini", input_tokens=1200, output_tokens=80, cached_input_tokens=1024)
        with pytest.raises(ActionBlocked):
            recorder.wrap(lambda: "gone", name="delete_account")()
        recorder.end_run()

    spans = spans_of(run)
    assert set(spans) == {"invoke_agent support", "execute_tool lookup_order", "chat gpt-4o-mini",
                          "execute_tool delete_account"}
    root, tool, chat, blocked = (spans["invoke_agent support"], spans["execute_tool lookup_order"],
                                 spans["chat gpt-4o-mini"], spans["execute_tool delete_account"])
    assert all(span.parent.span_id == root.context.span_id for span in (tool, chat, blocked))
    assert root.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert root.attributes["regshield.run.status"] == "blocked" and root.status.status_code == StatusCode.ERROR
    assert tool.attributes["gen_ai.tool.name"] == "lookup_order" and tool.status.status_code == StatusCode.UNSET
    assert "gen_ai.tool.call.arguments" not in tool.attributes  # content is opt-in
    assert (chat.attributes["gen_ai.usage.input_tokens"], chat.attributes["gen_ai.usage.output_tokens"],
            chat.attributes["gen_ai.usage.cache_read.input_tokens"]) == (1200, 80, 1024)
    assert chat.attributes["regshield.cost_usd"] > 0
    assert blocked.status.status_code == StatusCode.ERROR
    assert blocked.attributes["regshield.blocked_rule"] == "forbidden_tools"


def test_span_content_with_capture_content():
    def run():
        recorder = TraceRecorder()
        recorder.tool_call("lookup_order", {"order_id": "A-1"}, '{"status": "DELIVERED"}')
        recorder.final_answer("Delivered.")
        recorder.end_run()

    spans = spans_of(run, capture_content=True)
    tool = spans["execute_tool lookup_order"]
    assert json.loads(tool.attributes["gen_ai.tool.call.arguments"]) == {"order_id": "A-1"}
    assert tool.attributes["gen_ai.tool.call.result"] == '{"status": "DELIVERED"}'
    assert spans["invoke_agent agent"].attributes["regshield.final_response"] == "Delivered."


def test_a_run_inside_your_span_becomes_its_child():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    export_traces(OpenTelemetryExporter(tracer_provider=provider))
    with provider.get_tracer("app").start_as_current_span("POST /chat") as request_span:
        with TraceRecorder() as recorder:
            recorder.tool_call("search", {"q": "x"}, "results")
    spans = {span.name: span for span in memory.get_finished_spans()}
    assert spans["invoke_agent agent"].parent.span_id == request_span.get_span_context().span_id
    assert spans["execute_tool search"].context.trace_id == request_span.get_span_context().trace_id


# -- HTTP ---------------------------------------------------------------------------------

def test_http_exporter_posts_batches_to_a_server():
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.headers["Authorization"], json.loads(body)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        exporter = HTTPExporter(f"http://127.0.0.1:{server.server_port}/events",
                                headers={"Authorization": "Bearer t0ken"}, flush_interval=0.05)
        export_traces(exporter)
        support_run(TraceRecorder())
        stop_exporting()
    finally:
        server.shutdown()
    events = [event for auth, batch in received for event in batch["events"]]
    assert {auth for auth, _ in received} == {"Bearer t0ken"}
    assert [event["event"] for event in events] == ["run_start", "tool_call", "tool_call", "llm_call", "run_end"]
    assert exporter.sent == 5 and exporter.dropped == 0


def test_http_exporter_gives_up_quietly_when_the_server_is_down():
    exporter = HTTPExporter("http://127.0.0.1:9/unreachable", flush_interval=0.01, retries=1, timeout=0.5)
    export_traces(exporter)
    support_run(TraceRecorder())  # the agent isn't slowed down or broken
    stop_exporting(timeout=10)
    assert exporter.sent == 0 and exporter.dropped == 5


# -- LangChain ------------------------------------------------------------------------------

def test_each_langchain_invocation_is_one_run():
    pytest.importorskip("langchain_core")
    from langchain_core.runnables import RunnableLambda
    from langchain_core.tools import tool

    from regression_shield import RegressionShieldCallbackHandler

    @tool
    def lookup(order_id: str) -> str:
        """Look up an order."""
        return "DELIVERED"

    collect = Collect()
    export_traces(collect)
    handler = RegressionShieldCallbackHandler()
    agent = RunnableLambda(lambda order_id, config: lookup.invoke({"order_id": order_id}, config=config))
    agent.invoke("A-1", config={"callbacks": [handler]})
    agent.invoke("B-2", config={"callbacks": [handler]})
    kinds = [event["event"] for event in collect.events]
    assert kinds == ["run_start", "tool_call", "run_end", "run_start", "tool_call", "run_end"]
    assert collect.events[1]["duration_ms"] >= 0
