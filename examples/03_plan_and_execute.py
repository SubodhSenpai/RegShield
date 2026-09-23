"""Plan-and-execute with LangGraph: an LLM planner, a tool executor, and replanning on failure.

The first booking attempt fails (the flight is sold out), so a good agent
replans instead of pushing on. The planner's plans are recorded with
``handler.plan(...)``; tool calls are recorded automatically.

    python examples/03_plan_and_execute.py
"""

import json
import re
from typing import TypedDict

from _llm import chat_model
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

SOLD_OUT = {"UA-220"}


@tool
def search_flights(destination: str) -> str:
    """Find flights to a destination."""
    return json.dumps({"flights": ["UA-220", "UA-221"]})


@tool
def book_flight(flight: str) -> str:
    """Book a flight."""
    if flight in SOLD_OUT:
        raise ValueError(f"{flight} is sold out")
    return json.dumps({"status": "BOOKED", "flight": flight, "pnr": "K7XQ2P"})


@tool
def send_confirmation(pnr: str) -> str:
    """Email the booking confirmation."""
    return json.dumps({"status": "SENT", "pnr": pnr})


TOOLS = {t.name: t for t in (search_flights, book_flight, send_confirmation)}
handler = RegressionShieldCallbackHandler()  # records tool calls and graph nodes; the planner adds plans


class State(TypedDict):
    task: str
    plan: list
    done: list
    context: dict
    failed: str


def ask_for_plan(state: State) -> list:
    prompt = (f"Task: {state['task']}\nAvailable tools: {', '.join(TOOLS)}\n"
              f"Already done: {state['done'] or 'nothing'}\nLast failure: {state['failed'] or 'none'}\n"
              "Reply with only a JSON list of the tool names still needed, in order.")
    reply = chat_model().invoke(prompt).content
    names = json.loads(re.search(r"\[.*?\]", reply, re.S).group(0))
    return [name for name in names if name in TOOLS]


def planner(state: State) -> dict:
    plan = ask_for_plan(state)
    handler.plan(plan, thought=f"Plan: {' -> '.join(plan)}")
    return {"plan": plan, "failed": ""}


def executor(state: State) -> dict:
    """Run the plan step by step; stop at the first failure so the planner can replan."""
    context, done = dict(state["context"]), list(state["done"])
    for name in state["plan"]:
        if name == "book_flight":
            tried = context.setdefault("tried", [])
            args = {"flight": next(f for f in context["flights"] if f not in tried)}
            tried.append(args["flight"])
        elif name == "send_confirmation":
            args = {"pnr": context.get("pnr", "")}
        else:
            args = {"destination": "SFO"}
        try:
            result = json.loads(TOOLS[name].invoke(args))
        except ValueError as err:
            return {"context": context, "done": done, "failed": f"{name}: {err}"}
        context.update(result)
        done.append(name)
    return {"context": context, "done": done, "failed": ""}


graph = StateGraph(State)
graph.add_node("planner", planner)
graph.add_node("executor", executor)
graph.add_edge(START, "planner")
graph.add_edge("planner", "executor")
graph.add_conditional_edges("executor", lambda s: "planner" if s["failed"] else END)

SCENARIO = {
    "scenario_id": "trip_booking",
    "title": "Plan, execute, replan on failure",
    "require_plan": True,
    "expected_plan": ["search_flights", "book_flight", "send_confirmation"],
    "expected_order": ["search_flights", "book_flight", "send_confirmation"],
    "allowed_transitions": {"planner": ["executor"], "executor": ["planner"]},
    "max_node_visits": {"planner": 3},
}

if __name__ == "__main__":
    graph.compile().invoke({"task": "Book me a flight to SFO and send the confirmation.", "plan": [], "done": [],
                            "context": {}, "failed": ""}, config={"callbacks": [handler]})
    # A failed booking plus its retry is expected here, so allow the extra step
    report = evaluate_trace(SCENARIO, handler, min_step_efficiency=0.5, save_report=True)
    print(report.format())
