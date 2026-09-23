"""Your own agent loop, no framework: the OpenAI SDK with function calling, recorded with TraceRecorder.

Works with any OpenAI-compatible API (OpenAI, Ollama, vLLM, OpenRouter...).
Wrap your tool functions with ``recorder.wrap`` and add the model's text as
thoughts; the same pattern fits CrewAI, AutoGen, Pydantic AI or any SDK.

    pip install regression-shield openai
    python examples/08_custom_agent_loop.py
"""

import json

from _llm import MODEL, openai_client

from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()


@recorder.tool
def get_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "SHIPPED", "carrier": "UPS", "tracking": "1Z999"}


@recorder.tool
def track_package(tracking: str) -> dict:
    return {"tracking": tracking, "location": "Lisbon depot", "eta": "tomorrow"}


TOOLS = {"get_order": get_order, "track_package": track_package}
SCHEMAS = [
    {"type": "function", "function": {"name": "get_order", "description": "Look up an order.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {"name": "track_package", "description": "Track a package by tracking number.",
     "parameters": {"type": "object", "properties": {"tracking": {"type": "string"}}, "required": ["tracking"]}}},
]


def run_agent(question: str, max_turns: int = 6) -> str:
    client = openai_client()
    messages = [{"role": "system", "content": "Answer using the tools. Look up the order before tracking it."},
                {"role": "user", "content": question}]
    for _ in range(max_turns):
        message = client.chat.completions.create(model=MODEL, messages=messages, tools=SCHEMAS,
                                                 temperature=0).choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        if not message.tool_calls:
            recorder.final_answer(message.content or "")
            return message.content or ""
        if message.content:
            recorder.thought(message.content)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = TOOLS[call.function.name](**args)  # recorded by recorder.wrap
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
    return "Stopped after too many turns."


SCENARIO = {
    "scenario_id": "where_is_my_order",
    "title": "Order lookup, then tracking",
    "expected_tools": ["get_order", "track_package"],
    "expected_order": ["get_order", "track_package"],
    "expected_arguments": {"track_package": {"tracking": "1Z999"}},
}

if __name__ == "__main__":
    print("Answer:", run_agent("Where is my order ORD-55?"), "\n")
    report = evaluate_trace(SCENARIO, recorder, save_report=True)
    print(report.format())
