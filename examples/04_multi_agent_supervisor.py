"""Multi-agent with langgraph-supervisor: a supervisor hands work to a triage and a billing agent.

RegShield tags each step with the agent that ran it and records the
supervisor's transfer_to_* calls as handoffs, with no extra code.

    pip install "regression-shield[langgraph]" langchain langchain-openai langgraph-supervisor
    python examples/04_multi_agent_supervisor.py
"""

import json

from _llm import chat_model
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph_supervisor import create_supervisor

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order's status and amount."""
    return json.dumps({"order_id": order_id, "status": "DELIVERED", "amount": 89.0, "refundable": True})


@tool
def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order."""
    return json.dumps({"status": "REFUNDED", "order_id": order_id, "amount": amount})


triage = create_agent(chat_model(), tools=[lookup_order], name="triage_agent",
                      system_prompt="You look up orders. Report the order status and amount.")
billing = create_agent(chat_model(), tools=[issue_refund], name="billing_agent",
                       system_prompt="You issue refunds for the order and amount you are given.")
app = create_supervisor(
    [triage, billing],
    model=chat_model(),
    prompt="You manage a support team. First send the request to triage_agent to look up the order, "
           "then send it to billing_agent to refund it. Then answer the customer.",
).compile()

SCENARIO = {
    "scenario_id": "support_refund",
    "title": "Supervisor delegates lookup and refund",
    "expected_tools": ["lookup_order", "issue_refund"],
    "expected_order": ["lookup_order", "issue_refund"],
    "expected_arguments": {"issue_refund": {"order_id": "A-1", "amount": 89}},  # the amount triage found
    "agent_tools": {"triage_agent": ["lookup_order"], "billing_agent": ["issue_refund"], "supervisor": []},
    "expected_agents": ["triage_agent", "billing_agent"],
    "max_handoffs": 4,
    "max_tool_calls": {"issue_refund": 1},
}

if __name__ == "__main__":
    handler = RegressionShieldCallbackHandler()
    app.invoke({"messages": [{"role": "user", "content": "Order A-1 arrived broken. Please refund it."}]},
               config={"callbacks": [handler]})
    report = evaluate_trace(SCENARIO, handler, save_report=True)
    print(report.format())
    print("agents:", report.patterns["multi_agent"]["details"]["agents"])
