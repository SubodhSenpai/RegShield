"""smolagents integration: real agents, driven offline by scripted models."""

from types import SimpleNamespace as NS

import pytest

from regression_shield import evaluate_trace, extract_smolagents_trace, instrument_smolagents


def test_extract_keeps_failed_tool_calls():
    # smolagents leaves tool_calls empty on failure; the attempt is on the model's message
    failed = NS(tool_calls=None, error="Error executing tool 'transfer': ValueError: insufficient funds",
                observations=None, model_output="Sending.",
                model_output_message=NS(tool_calls=[NS(function=NS(name="transfer", arguments='{"amount": 5}'))]))
    succeeded = NS(tool_calls=[NS(name="notify", arguments={"msg": "hi"})], error=None,
                   observations="sent", model_output="Notifying.")
    trace = extract_smolagents_trace(NS(memory=NS(steps=[failed, succeeded])))
    assert [(s["action"]["name"], s["action"]["args"], s["observation"]) for s in trace] == [
        ("transfer", {"amount": 5}, "ERROR: Error executing tool 'transfer': ValueError: insufficient funds"),
        ("notify", {"msg": "hi"}, "sent"),
    ]


smolagents = pytest.importorskip("smolagents")
from smolagents import CodeAgent, ToolCallingAgent, tool  # noqa: E402
from smolagents.models import (  # noqa: E402
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
    Model,
)


class ScriptedModel(Model):
    """Stands in for an LLM: replays replies in order. A reply is plain text (for CodeAgent),
    (thought, tool, args), or (thought, [(tool, args), ...]) for several calls in one step."""

    def __init__(self, replies):
        super().__init__(model_id="scripted")
        self.replies = list(replies)

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, str):
            return ChatMessage(role=MessageRole.ASSISTANT, content=reply)
        thought, *rest = reply
        calls = rest[0] if len(rest) == 1 else [tuple(rest)]
        tool_calls = [ChatMessageToolCall(id=f"call_{len(self.replies)}_{i}", type="function",
                                          function=ChatMessageToolCallFunction(name=name, arguments=args))
                      for i, (name, args) in enumerate(calls)]
        return ChatMessage(role=MessageRole.ASSISTANT, content=thought, tool_calls=tool_calls)


@tool
def run_unit_tests() -> str:
    """Run the unit test suite."""
    return "PASSED"


@tool
def deploy_production(env: str) -> str:
    """Deploy the build.

    Args:
        env: Target environment.
    """
    return "DEPLOYED"


@tool
def execute_wire_transfer(amount: int) -> str:
    """Send a wire transfer.

    Args:
        amount: Amount to send.
    """
    raise ValueError("insufficient funds")


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order.

    Args:
        order_id: The order.
    """
    return '{"status": "DELIVERED", "amount": 89.0}'


DEPLOY_GATE = {"scenario_id": "deploy_gate", "expected_tools": ["run_unit_tests", "deploy_production"],
               "expected_order": ["run_unit_tests", "deploy_production"],
               "expected_arguments": {"deploy_production": {"env": "staging"}}}


def test_tool_calling_agent_extracted_after_the_run():
    agent = ToolCallingAgent(tools=[run_unit_tests, deploy_production], verbosity_level=0, max_steps=5, model=ScriptedModel([
        ("I'll run the tests first.", "run_unit_tests", {}),
        ("Tests passed. Deploying to staging.", "deploy_production", {"env": "staging"}),
        ("Done.", "final_answer", {"answer": "Deployed to staging."}),
    ]))
    agent.run("Deploy to staging")
    trace = extract_smolagents_trace(agent)
    assert [(s["action"]["name"], s["observation"]) for s in trace] == [("run_unit_tests", "PASSED"),
                                                                        ("deploy_production", "DEPLOYED")]
    assert evaluate_trace(DEPLOY_GATE, trace).passed


def test_instrumented_tool_calling_agent_catches_a_hallucinated_success():
    agent = ToolCallingAgent(tools=[execute_wire_transfer], verbosity_level=0, max_steps=5, model=ScriptedModel([
        ("Sending the transfer.", "execute_wire_transfer", {"amount": 500}),
        ("Transfer completed successfully.", "final_answer", {"answer": "Transfer completed successfully."}),
    ]))
    recorder = instrument_smolagents(agent)
    agent.run("Send 500")
    trace = recorder.get_trace()
    assert [s["action"]["name"] for s in trace] == ["execute_wire_transfer"]
    assert trace[0]["observation"] == "ERROR: ValueError: insufficient funds"
    assert recorder.final_response == "Transfer completed successfully."
    report = evaluate_trace({"scenario_id": "wire", "expected_tools": ["execute_wire_transfer"]}, recorder)
    assert report.failures == [
        "Reasoning faithfulness 0.50 < 0.85: Final response claims success right after an error"]


def test_code_agent_tool_calls_are_recorded_as_they_run():
    agent = CodeAgent(tools=[run_unit_tests, deploy_production], max_steps=4, verbosity_level=0, model=ScriptedModel([
        'Thought: test, then deploy.\n<code>\nrun_unit_tests()\ndeploy_production(env="staging")\n</code>',
        'Thought: done.\n<code>\nfinal_answer("Deployed to staging")\n</code>',
    ]))
    recorder = instrument_smolagents(agent)
    agent.run("Deploy to staging")
    trace = recorder.get_trace()
    assert [(s["action"]["name"], s["action"]["args"], s["observation"]) for s in trace] == [
        ("run_unit_tests", {}, "PASSED"), ("deploy_production", {"env": "staging"}, "DEPLOYED")]
    assert trace[0]["thought"].startswith("Thought: test, then deploy.")
    assert recorder.final_response == "Deployed to staging"
    assert evaluate_trace(DEPLOY_GATE, recorder).passed


def test_managed_agents_are_recorded_as_handoffs():
    orders = ToolCallingAgent(tools=[lookup_order], name="orders_agent", description="Looks up orders.",
                              verbosity_level=0, max_steps=4, model=ScriptedModel([
                                  ("Looking it up.", "lookup_order", {"order_id": "A-1"}),
                                  ("Found it.", "final_answer", {"answer": "Delivered, $89."}),
                              ]))
    manager = ToolCallingAgent(tools=[], managed_agents=[orders], name="manager", verbosity_level=0, max_steps=4,
                               model=ScriptedModel([
                                   ("Ask the orders agent.", "orders_agent", {"task": "Status of order A-1?"}),
                                   ("Answering.", "final_answer", {"answer": "Order A-1 was delivered."}),
                               ]))
    recorder = instrument_smolagents(manager)
    manager.run("Where is order A-1?")
    trace = recorder.get_trace()
    assert [(s["action"]["type"], s.get("agent")) for s in trace] == [("handoff", "manager"), ("tool_call", "orders_agent")]
    report = evaluate_trace({"scenario_id": "delegation", "agent_tools": {"orders_agent": ["lookup_order"]},
                             "expected_agents": ["manager", "orders_agent"]}, recorder)
    assert report.patterns["multi_agent"]["passed"], report.failures
    assert report.patterns["multi_agent"]["details"]["agents"] == ["manager", "orders_agent"]


@tool
def convert_currency(amount: float) -> float:
    """Convert USD to EUR.

    Args:
        amount: Amount in USD.
    """
    return round(amount * 0.92, 2)


def test_parallel_calls_are_credited_to_the_agent_that_made_them():
    # The manager asks its sub-agent and calls its own tool in the same step; smolagents
    # runs both in threads, so the sub-agent is still working while the manager's call runs
    orders = ToolCallingAgent(tools=[lookup_order], name="orders_agent", description="Looks up orders.",
                              verbosity_level=0, max_steps=4, model=ScriptedModel([
                                  ("Looking it up.", "lookup_order", {"order_id": "A-1"}),
                                  ("Found it.", "final_answer", {"answer": "$89."}),
                              ]))
    manager = ToolCallingAgent(tools=[convert_currency], managed_agents=[orders], name="manager", verbosity_level=0,
                               max_steps=4, model=ScriptedModel([
                                   ("Both at once.", [("orders_agent", {"task": "Amount of A-1?"}),
                                                      ("convert_currency", {"amount": 1})]),
                                   ("Answering.", "final_answer", {"answer": "About 0.92 EUR."}),
                               ]))
    recorder = instrument_smolagents(manager)
    manager.run("What is order A-1's amount in EUR?")
    trace = recorder.get_trace()
    by_name = {s["action"].get("name") or s["action"]["type"]: s for s in trace}
    assert by_name["convert_currency"]["agent"] == "manager"
    assert by_name["lookup_order"]["agent"] == "orders_agent"
    assert by_name["handoff"]["parallel_group"] == by_name["convert_currency"]["parallel_group"]
    assert "parallel_group" not in by_name["lookup_order"]

    scenario = {"scenario_id": "s", "agent_tools": {"manager": ["convert_currency"], "orders_agent": ["lookup_order"]},
                "expected_order": ["lookup_order", "convert_currency"]}
    report = evaluate_trace(scenario, recorder)
    assert report.patterns["multi_agent"]["passed"], report.failures
    # The conversion was requested before the amount was known
    assert any("'convert_currency'" in f and "lookup_order" in f for f in report.failures)


def test_answer_after_max_steps_is_captured():
    agent = ToolCallingAgent(tools=[lookup_order], verbosity_level=0, max_steps=1, model=ScriptedModel([
        ("Looking it up.", "lookup_order", {"order_id": "A-1"}),
        "Order A-1 was delivered.",  # smolagents asks for an answer once max_steps is reached
    ]))
    recorder = instrument_smolagents(agent)
    agent.run("Where is order A-1?")
    assert recorder.final_response == "Order A-1 was delivered."


def test_each_run_starts_a_new_trace():
    agent = ToolCallingAgent(tools=[lookup_order], verbosity_level=0, max_steps=3, model=ScriptedModel([
        ("Looking.", "lookup_order", {"order_id": "A-1"}), ("Done.", "final_answer", {"answer": "Delivered."}),
        ("Looking.", "lookup_order", {"order_id": "B-2"}), ("Done.", "final_answer", {"answer": "Delivered too."}),
    ]))
    recorder = instrument_smolagents(agent)
    agent.run("Where is A-1?")
    agent.run("Where is B-2?")
    trace = recorder.get_trace()
    assert [s["action"]["args"] for s in trace] == [{"order_id": "B-2"}]
    assert trace[0]["thought"] == "Looking." and recorder.final_response == "Delivered too."
