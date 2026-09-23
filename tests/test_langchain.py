"""LangChain / LangGraph integration: the callback handler, with synthetic callbacks and real graphs."""

import operator
import subprocess
import sys
from types import SimpleNamespace as NS
from typing import Annotated, TypedDict
from uuid import uuid4

import pytest

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace


def run_tool(handler, name, args, output, metadata=None, error=None):
    run_id = uuid4()
    handler.on_tool_start({"name": name}, input_str="", run_id=run_id, inputs=args, metadata=metadata or {})
    if error:
        handler.on_tool_error(error, run_id=run_id)
    else:
        handler.on_tool_end(output, run_id=run_id)


def lg(node, step, ns, agent=None):
    """LangGraph-style callback metadata."""
    metadata = {"langgraph_node": node, "langgraph_step": step, "langgraph_checkpoint_ns": ns}
    if agent:
        metadata["lc_agent_name"] = agent
    return metadata


# -- the handler with synthetic callbacks (no LangChain needed) -----------------------

def test_records_tool_calls_results_and_errors():
    handler = RegressionShieldCallbackHandler()
    run_tool(handler, "lookup", {"id": 1}, NS(content="found"))           # agents return ToolMessages
    run_tool(handler, "transfer", {"amount": 5}, None, error=ValueError("insufficient funds"))
    trace = handler.get_trace()
    assert [(s["action"]["name"], s["observation"]) for s in trace] == [
        ("lookup", "found"), ("transfer", "ERROR: ValueError: insufficient funds")]


class Command:
    """Stands in for langgraph.types.Command (matched by class name)."""

    def __init__(self, resume):
        self.resume = resume


def test_new_top_level_run_resets_but_a_resume_continues():
    handler = RegressionShieldCallbackHandler()
    run_tool(handler, "a", {}, "ok")
    handler.on_chain_start({}, Command({"decisions": []}), run_id=uuid4(), parent_run_id=None)
    assert len(handler.get_trace()) == 1
    handler.on_chain_start({}, {"messages": []}, run_id=uuid4(), parent_run_id=None)
    assert handler.get_trace() == []


def test_hitl_middleware_interrupt_and_decisions_become_approvals():
    handler = RegressionShieldCallbackHandler()
    interrupt = NS(id="i1", value={"action_requests": [{"name": "issue_refund", "args": {}}]})
    handler.on_chain_error(type("GraphInterrupt", (Exception,), {})((interrupt,)))
    handler.on_chain_start({}, Command({"decisions": [{"type": "reject"}]}), run_id=uuid4(), parent_run_id=None)
    assert handler.get_trace()[0]["action"] == {"type": "approval", "approved": False, "tool": "issue_refund",
                                                "by": "human"}


def test_transfer_tools_become_handoffs():
    handler = RegressionShieldCallbackHandler()
    run_tool(handler, "transfer_to_billing_agent", {}, "Transferred", metadata=lg("tools", 2, "supervisor:1|tools:2"))
    run_tool(handler, "transfer_back_to_supervisor", {}, "Transferred", metadata=lg("tools", 4, "billing_agent:3|tools:4"))
    assert [s["action"] for s in handler.get_trace()] == [{"type": "handoff", "to": "billing_agent"},
                                                           {"type": "handoff", "to": "supervisor"}]


def test_agents_are_tagged_only_when_several_ran():
    single = RegressionShieldCallbackHandler()
    run_tool(single, "a", {}, "ok", metadata=lg("tools", 2, "tools:1", agent="assistant"))
    assert "agent" not in single.get_trace()[0]

    multi = RegressionShieldCallbackHandler()
    run_tool(multi, "a", {}, "ok", metadata=lg("tools", 2, "research:1|tools:2", agent="research"))
    run_tool(multi, "b", {}, "ok", metadata=lg("tools", 2, "writer:3|tools:4", agent="writer"))
    assert [s["agent"] for s in multi.get_trace()] == ["research", "writer"]


def test_parallel_groups_only_for_different_tasks_in_the_same_step():
    handler = RegressionShieldCallbackHandler()
    run_tool(handler, "weather", {}, "sunny", metadata=lg("weather", 1, "weather:a"))
    run_tool(handler, "prices", {}, "$300", metadata=lg("prices", 1, "prices:b"))
    run_tool(handler, "summary", {"part": 1}, "ok", metadata=lg("summary", 2, "summary:c"))  # same task, sequential
    run_tool(handler, "summary", {"part": 2}, "ok", metadata=lg("summary", 2, "summary:c"))
    trace = handler.get_trace()
    assert trace[0]["parallel_group"] == trace[1]["parallel_group"]
    assert "parallel_group" not in trace[2] and "parallel_group" not in trace[3]


def test_handler_works_without_langchain_installed():
    code = ("import sys; sys.modules['langchain_core'] = None\n"   # makes 'import langchain_core' fail
            "from regression_shield import RegressionShieldCallbackHandler\n"
            "handler = RegressionShieldCallbackHandler(); handler.tool_call('lookup', {}, 'ok')\n"
            "print(len(handler.get_trace()))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_handler_is_a_trace_recorder():
    handler = RegressionShieldCallbackHandler()
    handler.plan(["lookup"])
    run_tool(handler, "lookup", {}, "ok")
    handler.route("billing")
    assert [s["action"]["type"] for s in handler.get_trace()] == ["plan", "tool_call", "route"]


# -- real LangChain / LangGraph ----------------------------------------------------------

langchain_core = pytest.importorskip("langchain_core")
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402


class ScriptedChatModel(BaseChatModel):
    """Stands in for an LLM: replays AIMessages in order."""
    responses: list

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, index):
    return {"name": name, "args": args, "id": f"call_{name}_{index}", "type": "tool_call"}


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order."""
    return '{"status": "DELIVERED", "amount": 89.0}'


@tool
def issue_refund(order_id: str, amount: float) -> str:
    """Issue a refund."""
    return '{"status": "REFUNDED"}'


def test_real_tool_invocation():
    handler = RegressionShieldCallbackHandler()
    lookup_order.invoke({"order_id": "A-1"}, config={"callbacks": [handler]})
    assert handler.get_trace()[0]["observation"] == '{"status": "DELIVERED", "amount": 89.0}'


def test_create_agent_parallel_tool_calls():
    agents = pytest.importorskip("langchain.agents")
    model = ScriptedChatModel(responses=[
        AIMessage(content="Checking both orders.", tool_calls=[call("lookup_order", {"order_id": "A-1"}, 1),
                                                               call("lookup_order", {"order_id": "B-2"}, 2)]),
        AIMessage(content="Both delivered."),
    ])
    handler = RegressionShieldCallbackHandler()
    agents.create_agent(model, tools=[lookup_order]).invoke(
        {"messages": [{"role": "user", "content": "status of A-1 and B-2"}]}, config={"callbacks": [handler]})
    calls = [s for s in handler.get_trace() if s["action"]["type"] == "tool_call"]
    assert len(calls) == 2 and calls[0]["parallel_group"] == calls[1]["parallel_group"]
    assert calls[0]["thought"] == "Checking both orders."


def test_graph_fan_out_is_parallel_and_nodes_are_recorded():
    graph_module = pytest.importorskip("langgraph.graph")

    class State(TypedDict):
        log: Annotated[list, operator.add]

    @tool
    def get_weather(city: str) -> str:
        """Weather."""
        return "sunny"

    @tool
    def get_prices(city: str) -> str:
        """Flight prices."""
        return "$300"

    @tool
    def summarize(city: str) -> str:
        """Summarize."""
        return "sunny, $300"

    def node(fn):
        return lambda state: (fn.invoke({"city": "Lisbon"}), {"log": [fn.name]})[1]

    graph = graph_module.StateGraph(State)
    for name, fn in (("weather", get_weather), ("prices", get_prices), ("summary", summarize)):
        graph.add_node(name, node(fn))
    graph.add_edge(graph_module.START, "weather")
    graph.add_edge(graph_module.START, "prices")
    graph.add_edge("weather", "summary")
    graph.add_edge("prices", "summary")
    graph.add_edge("summary", graph_module.END)

    handler = RegressionShieldCallbackHandler()
    graph.compile().invoke({"log": []}, config={"callbacks": [handler]})
    scenario = {
        "scenario_id": "fan_out",
        "allowed_transitions": {"weather": ["summary"], "prices": ["summary"]},
        "max_node_visits": 1,
        "expected_order": [["get_weather", "summarize"], ["get_prices", "summarize"]],
        "expected_parallel": [["get_weather", "get_prices"]],
    }
    report = evaluate_trace(scenario, handler)
    assert report.passed, report.failures
    batches = report.patterns["parallel"]["details"]["parallel_batches"]
    assert [sorted(batch) for batch in batches] == [["get_prices", "get_weather"]]  # the branches, not the summary
    first, second = report.patterns["graph"]["details"]["path"]
    assert sorted(first) == ["prices", "weather"] and second == "summary"

    only_weather = {**scenario, "allowed_transitions": {"weather": ["summary"]}}
    assert evaluate_trace(only_weather, handler).patterns["graph"]["passed"]  # summary is reachable from weather
    no_summary = {**scenario, "allowed_transitions": {"weather": ["prices"], "prices": ["weather"]}}
    assert "-> 'summary' is not an allowed transition" in " ".join(evaluate_trace(no_summary, handler).failures)


def test_parallel_tool_calls_count_as_one_node_visit():
    agents = pytest.importorskip("langchain.agents")
    model = ScriptedChatModel(responses=[
        AIMessage(content="", tool_calls=[call("lookup_order", {"order_id": "A-1"}, 1),
                                          call("lookup_order", {"order_id": "A-2"}, 2)]),
        AIMessage(content="Both shipped."),
    ])
    handler = RegressionShieldCallbackHandler()
    agents.create_agent(model, tools=[lookup_order]).invoke(
        {"messages": [{"role": "user", "content": "status of A-1 and A-2"}]}, config={"callbacks": [handler]})
    trace = handler.get_trace()
    assert [s["node"] for s in trace if s["action"]["type"] == "node"] == ["model", "tools", "model"]
    assert all("parallel_group" not in s for s in trace if s["action"]["type"] == "node")
    report = evaluate_trace({"scenario_id": "s", "max_node_visits": {"tools": 1}}, handler)
    assert report.passed, report.failures


def test_supervisor_multi_agent_is_captured_automatically():
    agents = pytest.importorskip("langchain.agents")
    supervisor_module = pytest.importorskip("langgraph_supervisor")
    triage = agents.create_agent(ScriptedChatModel(responses=[
        AIMessage(content="Looking up.", tool_calls=[call("lookup_order", {"order_id": "A-1"}, 1)]),
        AIMessage(content="Refundable."),
    ]), tools=[lookup_order], name="triage_agent")
    billing = agents.create_agent(ScriptedChatModel(responses=[
        AIMessage(content="Refunding.", tool_calls=[call("issue_refund", {"order_id": "A-1", "amount": 89.0}, 2)]),
        AIMessage(content="Refunded."),
    ]), tools=[issue_refund], name="billing_agent")
    supervisor = ScriptedChatModel(responses=[
        AIMessage(content="", tool_calls=[call("transfer_to_triage_agent", {}, 3)]),
        AIMessage(content="", tool_calls=[call("transfer_to_billing_agent", {}, 4)]),
        AIMessage(content="The refund is done."),
    ])
    app = supervisor_module.create_supervisor([triage, billing], model=supervisor).compile()
    handler = RegressionShieldCallbackHandler()
    app.invoke({"messages": [{"role": "user", "content": "Refund order A-1"}]}, config={"callbacks": [handler]})

    scenario = {"scenario_id": "support", "expected_tools": ["lookup_order", "issue_refund"],
                "agent_tools": {"triage_agent": ["lookup_order"], "billing_agent": ["issue_refund"]},
                "expected_agents": ["supervisor", "triage_agent", "billing_agent"], "max_handoffs": 2}
    report = evaluate_trace(scenario, handler)
    assert report.passed, report.failures
    handoffs = report.patterns["multi_agent"]["details"]["handoffs"]
    assert [(h["from"], h["to"]) for h in handoffs] == [("supervisor", "triage_agent"), ("supervisor", "billing_agent")]
    assert report.patterns["multi_agent"]["details"]["agents"] == [
        "supervisor", "triage_agent", "supervisor", "billing_agent", "supervisor"]

    wrong = {**scenario, "agent_tools": {"triage_agent": ["lookup_order", "issue_refund"], "billing_agent": []}}
    assert "agent 'billing_agent' called 'issue_refund'" in " ".join(evaluate_trace(wrong, handler).failures)


def test_an_agent_turn_without_tool_calls_is_in_the_agent_chain():
    agents = pytest.importorskip("langchain.agents")
    supervisor_module = pytest.importorskip("langgraph_supervisor")
    triage = agents.create_agent(ScriptedChatModel(responses=[AIMessage(content="I can't find that order.")]),
                                 tools=[lookup_order], name="triage_agent")
    supervisor = ScriptedChatModel(responses=[
        AIMessage(content="", tool_calls=[call("transfer_to_triage_agent", {}, 1)]),
        AIMessage(content="Sorry, we couldn't find it."),
    ])
    app = supervisor_module.create_supervisor([triage], model=supervisor).compile()
    handler = RegressionShieldCallbackHandler()
    app.invoke({"messages": [{"role": "user", "content": "Where is A-9?"}]}, config={"callbacks": [handler]})
    report = evaluate_trace({"scenario_id": "s", "expected_agents": ["supervisor", "triage_agent", "supervisor"]}, handler)
    assert report.passed, report.failures


@pytest.mark.parametrize("decision, passed", [("approve", True), ("reject", True), ("edit", True)])
def test_human_in_the_loop_middleware_decisions(decision, passed):
    agents = pytest.importorskip("langchain.agents")
    middleware = pytest.importorskip("langchain.agents.middleware")
    memory = pytest.importorskip("langgraph.checkpoint.memory")
    types = pytest.importorskip("langgraph.types")
    model = ScriptedChatModel(responses=[
        AIMessage(content="Refunding.", tool_calls=[call("issue_refund", {"order_id": "A-1", "amount": 89.0}, 1)]),
        AIMessage(content="Done."),
    ])
    agent = agents.create_agent(model, tools=[issue_refund], checkpointer=memory.InMemorySaver(),
                                middleware=[middleware.HumanInTheLoopMiddleware(interrupt_on={"issue_refund": True})])
    handler = RegressionShieldCallbackHandler()
    config = {"configurable": {"thread_id": decision}, "callbacks": [handler]}
    agent.invoke({"messages": [{"role": "user", "content": "refund A-1"}]}, config)
    choice = {"type": decision}
    if decision == "edit":
        choice["edited_action"] = {"name": "issue_refund", "args": {"order_id": "A-1", "amount": 89.0}}
    agent.invoke(types.Command(resume={"decisions": [choice]}), config)

    trace = handler.get_trace()
    approvals = [s["action"] for s in trace if s["action"]["type"] == "approval"]
    refunds = [s for s in trace if s["action"].get("name") == "issue_refund"]
    assert approvals == [{"type": "approval", "approved": decision != "reject", "tool": "issue_refund", "by": "human"}]
    assert len(refunds) == (0 if decision == "reject" else 1)  # a rejected call never runs
    report = evaluate_trace({"scenario_id": "hitl", "requires_approval": ["issue_refund"]}, handler)
    assert report.passed is passed, report.failures


def test_graph_transitions_from_a_real_graph():
    graph_module = pytest.importorskip("langgraph.graph")

    @tool
    def write_draft(topic: str) -> str:
        """Write a draft."""
        return "draft"

    class State(TypedDict):
        reviews: int

    graph = graph_module.StateGraph(State)
    graph.add_node("draft", lambda s: (write_draft.invoke({"topic": f"v{s['reviews']}"}), {})[1])
    graph.add_node("review", lambda s: {"reviews": s["reviews"] + 1})
    graph.add_node("publish", lambda s: {})
    graph.add_edge(graph_module.START, "draft")
    graph.add_edge("draft", "review")
    graph.add_conditional_edges("review", lambda s: "draft" if s["reviews"] < 2 else "publish")
    graph.add_edge("publish", graph_module.END)

    handler = RegressionShieldCallbackHandler()
    graph.compile().invoke({"reviews": 0}, config={"callbacks": [handler]})
    scenario = {"scenario_id": "graph", "allowed_transitions": {"draft": ["review"], "review": ["draft", "publish"]},
                "max_node_visits": {"review": 2}}
    report = evaluate_trace(scenario, handler)
    assert report.passed, report.failures
    assert report.patterns["graph"]["details"]["path"] == ["draft", "review", "draft", "review", "publish"]
    strict = {**scenario, "max_node_visits": {"review": 1}}
    assert "Node 'review' was entered 2 times (max 1)" in " ".join(evaluate_trace(strict, handler).failures)


def test_final_answer_is_captured_from_the_last_ai_message():
    agents = pytest.importorskip("langchain.agents")
    model = ScriptedChatModel(responses=[
        AIMessage(content="Refunding.", tool_calls=[call("issue_refund", {"order_id": "A-1", "amount": 89.0}, 1)]),
        AIMessage(content="The refund went through."),
    ])
    handler = RegressionShieldCallbackHandler()
    agents.create_agent(model, tools=[issue_refund]).invoke(
        {"messages": [{"role": "user", "content": "refund A-1"}]}, config={"callbacks": [handler]})
    assert handler.final_response == "The refund went through."


def test_a_run_paused_on_a_tool_request_has_no_final_answer():
    handler = RegressionShieldCallbackHandler()
    run = uuid4()
    handler.on_chain_start({}, {"messages": []}, run_id=run)
    pending = AIMessage(content="Let me try the refund again.", tool_calls=[call("issue_refund", {"order_id": "A-1"}, 1)])
    handler.on_chain_end({"messages": [AIMessage(content="Checking."), pending]}, run_id=run)
    assert handler.final_response == ""
