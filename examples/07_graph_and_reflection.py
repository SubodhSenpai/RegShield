"""Graph workflow + evaluator-optimizer: an LLM writer and an LLM reviewer loop until the copy is approved.

LangGraph nodes are recorded automatically (graph checks). Each draft and
review verdict is recorded with ``handler.draft`` / ``handler.critique``
(reflection checks).

    python examples/07_graph_and_reflection.py
"""

import json
import re
from typing import TypedDict

from _llm import chat_model
from langgraph.graph import END, START, StateGraph

from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

MAX_ROUNDS = 3
handler = RegressionShieldCallbackHandler()


class State(TypedDict):
    product: str
    draft: str
    feedback: str
    approved: bool
    rounds: int


def writer(state: State) -> dict:
    prompt = f"Write a two-sentence product description for: {state['product']}."
    if state["feedback"]:
        prompt += f"\nRevise this draft:\n{state['draft']}\nReviewer feedback: {state['feedback']}"
    prompt += "\nReply with only the description."
    draft = chat_model().invoke(prompt).content.strip()
    handler.draft(draft)
    return {"draft": draft}


def reviewer(state: State) -> dict:
    reply = chat_model().invoke(
        "You review product copy. It must mention the battery life and end with a call to action.\n"
        f"Copy:\n{state['draft']}\n"
        'Reply with only JSON: {"approved": true or false, "feedback": "what to fix"}'
    ).content
    match = re.search(r"\{.*\}", reply, re.S)
    verdict = json.loads(match.group(0)) if match else {"approved": False, "feedback": "Unreadable review."}
    handler.critique(bool(verdict.get("approved")), str(verdict.get("feedback", "")))
    return {"approved": bool(verdict.get("approved")), "feedback": verdict.get("feedback", ""),
            "rounds": state["rounds"] + 1}


def publish(state: State) -> dict:
    return {}


graph = StateGraph(State)
graph.add_node("writer", writer)
graph.add_node("reviewer", reviewer)
graph.add_node("publish", publish)
graph.add_edge(START, "writer")
graph.add_edge("writer", "reviewer")
graph.add_conditional_edges(
    "reviewer", lambda s: "publish" if s["approved"] or s["rounds"] >= MAX_ROUNDS else "writer")
graph.add_edge("publish", END)

SCENARIO = {
    "scenario_id": "product_copy",
    "title": "Copy is reviewed before publishing",
    "allowed_transitions": {"writer": ["reviewer"], "reviewer": ["writer", "publish"]},
    "max_node_visits": {"reviewer": MAX_ROUNDS},
    "max_revision_rounds": MAX_ROUNDS,
}

if __name__ == "__main__":
    result = graph.compile().invoke(
        {"product": "Aero X wireless earbuds with 30-hour battery life", "draft": "", "feedback": "",
         "approved": False, "rounds": 0},
        config={"callbacks": [handler]},
    )
    print("Final copy:", result["draft"], "\n")
    report = evaluate_trace(SCENARIO, handler, save_report=True)
    print(report.format())
    print("path:", report.patterns["graph"]["details"]["path"])
