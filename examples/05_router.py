"""Routing: an LLM router sends each support request to a team; RegShield reports routing accuracy.

The route is recorded with ``recorder.route(...)``. Several requests are
evaluated like a scenario file, so you get accuracy across the set.

    python examples/05_router.py
"""

from _llm import chat_model

from regression_shield import AgentTraceEvaluator, TraceRecorder

TEAMS = ["billing", "technical", "sales"]
REQUESTS = [
    ("I was charged twice for my subscription.", "billing"),
    ("The app crashes when I upload a photo.", "technical"),
    ("Do you offer a discount for 50 seats?", "sales"),
    ("My invoice shows the wrong VAT number.", "billing"),
    ("I can't log in after resetting my password.", "technical"),
]


def route(request: str, recorder: TraceRecorder) -> str:
    reply = chat_model().invoke(
        f"Route this support request to one team: {', '.join(TEAMS)}.\n"
        f"Request: {request}\nAnswer with the team name only."
    ).content.strip().lower()
    team = next((t for t in TEAMS if t in reply), reply)
    recorder.route(team, thought=f"Model answered: {reply!r}")
    return team


if __name__ == "__main__":
    evaluator = AgentTraceEvaluator()
    correct = 0
    for number, (request, expected) in enumerate(REQUESTS, 1):
        recorder = TraceRecorder()
        route(request, recorder)
        report = evaluator.evaluate({"scenario_id": f"route_{number}", "expected_route": expected}, recorder)
        correct += report.passed
        print(f"{'PASS' if report.passed else 'FAIL'}  {request!r} -> {report.patterns['routing']['details']['route']}"
              + ("" if report.passed else f"  ({report.failures[0]})"))
    print(f"\nRouting accuracy: {correct}/{len(REQUESTS)} ({correct / len(REQUESTS):.0%})")
