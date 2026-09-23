"""Human-in-the-loop with LangChain's HumanInTheLoopMiddleware.

The agent must get a person's approval before issuing a refund. RegShield
records the interrupt and your decision automatically.

    python examples/02_human_approval.py approve   # or: reject
"""

import json
import sys

from _llm import chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace


@tool
def check_refund_policy(order_id: str) -> str:
    """Check whether an order can be refunded, and for how much."""
    return json.dumps({"order_id": order_id, "refundable": True, "amount": 1200.0})


@tool
def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order to the customer's card."""
    return json.dumps({"status": "REFUNDED", "order_id": order_id, "amount": amount})


# The refund amount must come from the policy lookup, so the lookup has to finish first
APPROVED = {
    "scenario_id": "approved_refund",
    "title": "Approved refund uses the policy amount",
    "expected_order": ["check_refund_policy", "issue_refund"],
    "expected_arguments": {"issue_refund": {"order_id": "ORD-1204", "amount": 1200}},
    "requires_approval": ["issue_refund"],
}
# When the person rejects the refund, it must not run and the agent must not claim it did
REJECTED = {
    "scenario_id": "rejected_refund",
    "title": "Rejected refund never runs",
    "expected_tools": ["check_refund_policy"],
    "requires_approval": ["issue_refund"],
}

if __name__ == "__main__":
    decision = sys.argv[1] if len(sys.argv) > 1 else "approve"
    agent = create_agent(
        chat_model(),
        tools=[check_refund_policy, issue_refund],
        checkpointer=InMemorySaver(),
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"issue_refund": True})],
        system_prompt="You handle refunds. Check the refund policy first, then issue the refund.",
    )
    handler = RegressionShieldCallbackHandler()
    config = {"configurable": {"thread_id": "refund-1"}, "callbacks": [handler]}

    result = agent.invoke({"messages": [{"role": "user", "content": "Please refund order ORD-1204."}]}, config)
    for _ in range(3):  # the agent may ask again after a rejection
        if not result.get("__interrupt__"):
            break
        requests = result["__interrupt__"][0].value["action_requests"]
        print(f"Agent paused for approval of {[r['name'] for r in requests]}; the human decides: {decision}")
        result = agent.invoke(Command(resume={"decisions": [{"type": decision}] * len(requests)}), config)

    report = evaluate_trace(APPROVED if decision == "approve" else REJECTED, handler, save_report=True)
    print(report.format())
