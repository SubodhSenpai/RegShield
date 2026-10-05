"""The guard inside real frameworks: LangChain middleware, a LangGraph ToolNode, smolagents."""

import pytest

from regression_shield import ActionBlocked, Guard, RegressionShieldCallbackHandler, evaluate_trace

ran: list[str] = []  # tools that really ran


# -- LangChain / LangGraph -------------------------------------------------------------

langchain_core = pytest.importorskip("langchain_core")
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
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


def ai(content="", calls=(), tokens=0):
    usage = {"input_tokens": tokens, "output_tokens": tokens, "total_tokens": 2 * tokens} if tokens else None
    return AIMessage(content=content, usage_metadata=usage,
                     tool_calls=[{"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}
                                 for i, (name, args) in enumerate(calls)])


@tool
def run_sql(query: str) -> str:
    """Run a SQL query."""
    ran.append(query)
    return "1 row"


def test_langchain_middleware_blocks_and_the_agent_carries_on():
    ran.clear()
    agents = pytest.importorskip("langchain.agents")
    handler = RegressionShieldCallbackHandler(guard=Guard({"forbidden_arguments": {"run_sql": {"query": r"\bdrop\b"}}}))
    model = ScriptedChatModel(responses=[
        ai(calls=[("run_sql", {"query": "DROP TABLE orders"})]),
        ai(calls=[("run_sql", {"query": "SELECT count(*) FROM orders"})]),
        ai("I can't drop tables during the freeze; there is 1 order."),
    ])
    agent = agents.create_agent(model, tools=[run_sql], middleware=[handler.middleware()])
    result = agent.invoke({"messages": [{"role": "user", "content": "Drop the orders table"}]},
                          config={"callbacks": [handler]})
    assert ran == ["SELECT count(*) FROM orders"]  # the DROP never ran
    blocked = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
    assert blocked[0].content.startswith("ERROR: Blocked by policy: run_sql.query matches forbidden pattern")
    steps = handler.get_trace()
    assert [(s["action"]["name"], bool(s.get("blocked"))) for s in steps if s["action"]["type"] == "tool_call"] == [
        ("run_sql", True), ("run_sql", False)]
    assert handler.final_response == "I can't drop tables during the freeze; there is 1 order."


def test_langchain_budget_stops_the_agent():
    agents = pytest.importorskip("langchain.agents")
    handler = RegressionShieldCallbackHandler(guard=Guard({"max_llm_calls": 1}))
    model = ScriptedChatModel(responses=[ai(calls=[("run_sql", {"query": "SELECT 1"})], tokens=50), ai("done")])
    agent = agents.create_agent(model, tools=[run_sql], middleware=[handler.middleware()])
    with pytest.raises(ActionBlocked, match="the run has made 1 of its 1 model calls"):
        agent.invoke({"messages": [{"role": "user", "content": "go"}]}, config={"callbacks": [handler]})


def test_langgraph_tool_node_uses_the_guard():
    ran.clear()
    prebuilt = pytest.importorskip("langgraph.prebuilt")
    handler = RegressionShieldCallbackHandler(guard=Guard({"forbidden_tools": ["run_sql"]}))
    node = prebuilt.ToolNode([run_sql], wrap_tool_call=handler.wrap_tool_call)
    graph_module = pytest.importorskip("langgraph.graph")
    graph = graph_module.StateGraph(graph_module.MessagesState)
    graph.add_node("tools", node)
    graph.add_edge(graph_module.START, "tools")
    app = graph.compile()
    result = app.invoke({"messages": [ai(calls=[("run_sql", {"query": "SELECT 1"})])]}, config={"callbacks": [handler]})
    assert ran == []
    assert result["messages"][-1].content == ("ERROR: Blocked by policy: 'run_sql' is a forbidden tool. "
                                              "This action did not run.")
    assert handler.get_trace()[-1]["blocked"]["rule"] == "forbidden_tools"


# -- smolagents -------------------------------------------------------------------------

def test_smolagents_blocked_call_is_shown_to_the_model_and_the_run_continues():
    smolagents = pytest.importorskip("smolagents")
    from smolagents import tool  # smolagents wants the decorator written as @tool
    from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole, Model

    from regression_shield import TraceRecorder, instrument_smolagents

    class ScriptedModel(Model):
        def __init__(self, replies):
            super().__init__(model_id="scripted")
            self.replies = list(replies)
            self.seen: list = []

        def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs):
            self.seen.append(messages)
            thought, name, args = self.replies.pop(0)
            call = ChatMessageToolCall(id=f"call_{len(self.replies)}", type="function",
                                       function=ChatMessageToolCallFunction(name=name, arguments=args))
            return ChatMessage(role=MessageRole.ASSISTANT, content=thought, tool_calls=[call])

    deployed = []

    @tool
    def run_unit_tests() -> str:
        """Run the unit test suite."""
        return "PASSED: 120 tests"

    @tool
    def deploy_production(env: str) -> str:
        """Deploy the build.

        Args:
            env: where to deploy
        """
        deployed.append(env)
        return f"deployed to {env}"

    model = ScriptedModel([
        ("Deploying now.", "deploy_production", {"env": "prod"}),
        ("Tests first, then.", "run_unit_tests", {}),
        ("Now deploy.", "deploy_production", {"env": "prod"}),
        ("Done.", "final_answer", {"answer": "Deployed to prod after 120 tests passed."}),
    ])
    agent = smolagents.ToolCallingAgent(tools=[run_unit_tests, deploy_production], model=model, max_steps=6,
                                        verbosity_level=0)
    scenario = {"scenario_id": "deploy", "prerequisites": {"deploy_production": ["run_unit_tests"]}}
    recorder = instrument_smolagents(agent, TraceRecorder(guard=Guard(scenario)))
    agent.run("Deploy to production")
    assert deployed == ["prod"]  # only the call after the tests ran
    calls = [(s["action"]["name"], bool(s.get("blocked"))) for s in recorder.get_trace()]
    assert calls == [("deploy_production", True), ("run_unit_tests", False), ("deploy_production", False)]
    told = str(model.seen[1])
    assert "Blocked by policy: 'deploy_production' needs 'run_unit_tests' to succeed first" in told
    report = evaluate_trace(scenario, recorder)
    assert any("(blocked)" in failure for failure in report.failures)  # the first attempt is still a bug


def test_smolagents_budget_stops_the_run():
    smolagents = pytest.importorskip("smolagents")
    from smolagents import tool  # smolagents wants the decorator written as @tool
    from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole, Model
    from smolagents.monitoring import TokenUsage

    from regression_shield import TraceRecorder, instrument_smolagents

    class LoopingModel(Model):
        def __init__(self):
            super().__init__(model_id="gpt-4o-mini")
            self.calls = 0

        def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs):
            self.calls += 1
            call = ChatMessageToolCall(id=f"call_{self.calls}", type="function",
                                       function=ChatMessageToolCallFunction(name="web_search", arguments={"q": "more"}))
            return ChatMessage(role=MessageRole.ASSISTANT, content="Searching again.", tool_calls=[call],
                               token_usage=TokenUsage(input_tokens=1000, output_tokens=100))

    @tool
    def web_search(q: str) -> str:
        """Search the web.

        Args:
            q: the query
        """
        return "nothing new"

    model = LoopingModel()
    agent = smolagents.ToolCallingAgent(tools=[web_search], model=model, max_steps=20, verbosity_level=0)
    recorder = instrument_smolagents(agent, TraceRecorder(guard=Guard({"max_llm_calls": 3})))
    with pytest.raises(Exception) as stopped:
        agent.run("Find everything")
    chain = [stopped.value, stopped.value.__cause__, stopped.value.__context__]
    assert any(isinstance(error, ActionBlocked) for error in chain)
    assert model.calls == 3 and len(recorder.llm_calls) == 3
