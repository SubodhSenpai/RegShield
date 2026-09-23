"""Parallel calls: a LangGraph fan-out fetches weather and flight prices at the same time, then an LLM summarizes.

RegShield detects the concurrent branches from LangGraph's metadata and checks
that the summary waited for both.

    python examples/06_parallel_calls.py
"""

import operator
from typing import Annotated, TypedDict

from _llm import chat_model
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace


@tool
def get_weather(city: str) -> str:
    """Weather forecast for a city."""
    return "Sunny, 24C"


@tool
def get_flight_prices(city: str) -> str:
    """Cheapest round-trip flight price to a city."""
    return "$412 on TAP"


class State(TypedDict):
    city: str
    facts: Annotated[list, operator.add]
    summary: str


def weather(state: State) -> dict:
    return {"facts": [f"weather: {get_weather.invoke({'city': state['city']})}"]}


def prices(state: State) -> dict:
    return {"facts": [f"flights: {get_flight_prices.invoke({'city': state['city']})}"]}


def summary(state: State) -> dict:
    text = chat_model().invoke(f"In one sentence, summarize a trip to {state['city']}: {'; '.join(state['facts'])}")
    return {"summary": text.content}


graph = StateGraph(State)
graph.add_node("weather", weather)
graph.add_node("prices", prices)
graph.add_node("summary", summary)
graph.add_edge(START, "weather")
graph.add_edge(START, "prices")           # fan out: both run in the same step
graph.add_edge(["weather", "prices"], "summary")
graph.add_edge("summary", END)

SCENARIO = {
    "scenario_id": "trip_research",
    "title": "Independent lookups run in parallel",
    "expected_tools": ["get_weather", "get_flight_prices"],
    "expected_parallel": [["get_weather", "get_flight_prices"]],
    "allowed_transitions": {"weather": ["summary"], "prices": ["summary"]},  # the graph's own edges
}

if __name__ == "__main__":
    handler = RegressionShieldCallbackHandler()
    result = graph.compile().invoke({"city": "Lisbon", "facts": [], "summary": ""}, config={"callbacks": [handler]})
    print("Summary:", result["summary"], "\n")
    report = evaluate_trace(SCENARIO, handler, save_report=True)
    print(report.format())
    print("concurrent batches:", report.patterns["parallel"]["details"]["parallel_batches"])
