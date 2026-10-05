"""instrument(): recording OpenAI, Anthropic and Gemini SDK calls with no code in the agent loop.

Each SDK runs for real against a scripted HTTP server (httpx.MockTransport), and the
agent loops are written the way an application would write them.
"""

import asyncio
import importlib
import json

import httpx
import pytest

from regression_shield import ActionBlocked, Guard, TraceRecorder, evaluate_trace, instrument, uninstrument

ORDER = '{"status": "DELIVERED", "amount": 40}'


class Server:
    """Replays scripted replies and keeps the JSON bodies of the requests it got. ``http`` is
    the HTTP library the SDK uses (httpx, or httpx2 for newer SDKs)."""

    def __init__(self, *replies, http=httpx):
        self.replies = list(replies)
        self.requests = []
        self.http = http

    def __call__(self, request):
        self.requests.append(json.loads(request.content or b"{}"))
        reply = self.replies.pop(0)
        return reply if isinstance(reply, self.http.Response) else self.http.Response(200, json=reply)


def sse(events, named=False, http=httpx):
    lines = "".join((f"event: {event['type']}\n" if named else "") + f"data: {json.dumps(event)}\n\n" for event in events)
    return http.Response(200, headers={"content-type": "text/event-stream"},
                         content=lines + ("" if named else "data: [DONE]\n\n"))


# -- OpenAI chat completions -------------------------------------------------------------

openai = pytest.importorskip("openai")


def chat(content=None, calls=(), prompt=100, completion=20):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}
                                 for i, (name, args) in enumerate(calls)]
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini-2024-07-18",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}}


def openai_client(server):
    return openai.OpenAI(api_key="test", base_url="http://test/v1", max_retries=0,
                         http_client=httpx.Client(transport=httpx.MockTransport(server)))


TOOLS = {"lookup_order": lambda order_id: ORDER, "issue_refund": lambda order_id, amount: '{"status": "REFUNDED"}'}


def openai_agent(client, question, tools=TOOLS):
    """A plain tool-calling loop on the OpenAI SDK, as an application would write it."""
    messages = [{"role": "user", "content": question}]
    while True:
        message = client.chat.completions.create(model="gpt-4o-mini", messages=messages).choices[0].message
        if not message.tool_calls:
            return message.content
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            result = tools[call.function.name](**json.loads(call.function.arguments))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})


def test_openai_tool_loop_is_recorded_without_code_in_the_loop():
    instrument()
    server = Server(chat("Let me look it up.", [("lookup_order", {"order_id": "A-1"})]),
                    chat(None, [("issue_refund", {"order_id": "A-1", "amount": 40})], prompt=150),
                    chat("Refunded $40 for order A-1.", prompt=200, completion=12))
    with TraceRecorder() as recorder:
        answer = openai_agent(openai_client(server), "Refund order A-1")
    assert answer == "Refunded $40 for order A-1."
    steps = recorder.get_trace()
    assert [(s["action"]["name"], s["action"]["args"], s["observation"]) for s in steps] == [
        ("lookup_order", {"order_id": "A-1"}, ORDER),
        ("issue_refund", {"order_id": "A-1", "amount": 40}, '{"status": "REFUNDED"}')]
    assert steps[0]["thought"] == "Let me look it up."
    assert recorder.final_response == "Refunded $40 for order A-1."
    assert [(c["model"], c["input_tokens"], c["output_tokens"]) for c in recorder.llm_calls] == [
        ("gpt-4o-mini-2024-07-18", 100, 20), ("gpt-4o-mini-2024-07-18", 150, 20), ("gpt-4o-mini-2024-07-18", 200, 12)]
    report = evaluate_trace({"scenario_id": "refund", "expected_tools": ["lookup_order", "issue_refund"]}, recorder)
    assert report.passed and report.cost["llm_calls"] == 3


def test_calls_outside_a_with_block_are_not_recorded():
    instrument()
    recorder = TraceRecorder()
    openai_agent(openai_client(Server(chat("Hi."))), "Hello")
    assert recorder.llm_calls == [] and recorder.final_response == ""


def test_several_calls_in_one_reply_are_one_parallel_group():
    instrument()
    server = Server(chat(None, [("lookup_order", {"order_id": "A-1"}), ("lookup_order", {"order_id": "B-2"})]),
                    chat("Both delivered."))
    with TraceRecorder() as recorder:
        openai_agent(openai_client(server), "Check A-1 and B-2")
    groups = {step.get("parallel_group") for step in recorder.get_trace()}
    assert len(groups) == 1 and None not in groups


def test_async_openai_client():
    instrument()
    server = Server(chat(None, [("lookup_order", {"order_id": "A-1"})]), chat("Delivered."))
    client = openai.AsyncOpenAI(api_key="test", base_url="http://test/v1", max_retries=0,
                                http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))

    async def agent():
        messages = [{"role": "user", "content": "Where is A-1?"}]
        while True:
            message = (await client.chat.completions.create(model="gpt-4o-mini", messages=messages)).choices[0].message
            if not message.tool_calls:
                return message.content
            messages.append(message.model_dump(exclude_none=True))
            messages += [{"role": "tool", "tool_call_id": c.id, "content": ORDER} for c in message.tool_calls]

    async def main():
        with TraceRecorder() as recorder:
            await agent()
        return recorder

    recorder = asyncio.run(main())
    assert [s["action"]["name"] for s in recorder.get_trace()] == ["lookup_order"]
    assert recorder.final_response == "Delivered." and len(recorder.llm_calls) == 2


def test_streamed_openai_reply_is_recorded_when_the_stream_ends():
    instrument()
    base = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-4o-mini"}
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": "call_7", "type": "function", "function": {"name": "lookup_order", "arguments": ""}}]}}]},
        {**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"order_id": '}}]}}]},
        {**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"A-1"}'}}]}}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {**base, "choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}},
    ]
    server = Server(sse(chunks), chat("Delivered."))
    client = openai_client(server)
    with TraceRecorder() as recorder:
        stream = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "A-1?"}],
                                                stream=True, stream_options={"include_usage": True})
        received = list(stream)  # the application sees every chunk, unchanged
        client.chat.completions.create(model="gpt-4o-mini", messages=[
            {"role": "user", "content": "A-1?"},
            {"role": "assistant", "tool_calls": [{"id": "call_7", "type": "function",
                                                  "function": {"name": "lookup_order", "arguments": '{"order_id": "A-1"}'}}]},
            {"role": "tool", "tool_call_id": "call_7", "content": ORDER}])
    assert len(received) == 5
    assert [(s["action"]["name"], s["action"]["args"], s["observation"]) for s in recorder.get_trace()] == [
        ("lookup_order", {"order_id": "A-1"}, ORDER)]
    assert (recorder.llm_calls[0]["input_tokens"], recorder.llm_calls[0]["output_tokens"]) == (50, 10)


def test_guard_blocks_a_requested_call_before_the_app_can_run_it():
    instrument()
    refunds = []
    tools = {**TOOLS, "issue_refund": lambda order_id, amount: refunds.append(amount) or '{"status": "REFUNDED"}'}
    server = Server(chat(None, [("lookup_order", {"order_id": "A-1"})]),
                    chat("Refunding in full.", [("issue_refund", {"order_id": "A-1", "amount": 4000})]))
    guard = Guard({"forbidden_arguments": {"issue_refund": {"amount": r"^\d{4,}"}}})
    with pytest.raises(ActionBlocked, match="issue_refund.amount matches forbidden pattern"):
        with TraceRecorder(guard=guard) as recorder:
            openai_agent(openai_client(server), "Refund A-1", tools)
    assert refunds == []  # the app never got the reply asking for the refund
    steps = recorder.get_trace()
    assert [(s["action"]["name"], bool(s.get("blocked"))) for s in steps] == [("lookup_order", False), ("issue_refund", True)]
    assert steps[1]["thought"] == "Refunding in full."
    assert len(recorder.llm_calls) == 2  # the blocked reply's usage is still counted


def test_budget_stops_a_runaway_loop_before_the_request_is_sent():
    instrument()
    server = Server(*[chat(None, [("lookup_order", {"order_id": "A-1"})]) for _ in range(10)])
    with pytest.raises(ActionBlocked, match="made 3 of its 3 model calls"):
        with TraceRecorder(guard=Guard({"max_llm_calls": 3})):
            openai_agent(openai_client(server), "Keep checking A-1")
    assert len(server.requests) == 3


def test_wrapped_tools_are_recorded_once_with_the_models_reasoning():
    instrument()
    server = Server(chat("Checking the order.", [("lookup_order", {"order_id": "A-1"})]), chat("Delivered."))
    with TraceRecorder() as recorder:
        tools = {"lookup_order": recorder.tool(lambda order_id: ORDER, name="lookup_order")}
        openai_agent(openai_client(server), "A-1?", tools)
    steps = recorder.get_trace()
    assert [(s["action"]["name"], s.get("thought")) for s in steps] == [("lookup_order", "Checking the order.")]


def test_unanswered_calls_are_recorded_as_unconfirmed():
    instrument()
    server = Server(chat(None, [("send_email", {"to": "a@b.com"})]))
    with TraceRecorder() as recorder:
        openai_client(server).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "Email"}])
    step = recorder.get_trace()[0]
    assert (step["action"]["name"], step["observation"], step["unconfirmed"]) == ("send_email", "", True)


def test_sdk_errors_pass_through_unchanged():
    instrument()
    server = Server(httpx.Response(429, json={"error": {"message": "rate limited", "type": "rate_limit"}}))
    with TraceRecorder() as recorder:
        with pytest.raises(openai.RateLimitError):
            openai_client(server).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}])
    assert recorder.llm_calls == []


def test_uninstrument_restores_the_sdk():
    from openai.resources.chat.completions import Completions

    original = Completions.create
    instrument()
    assert Completions.create is not original
    instrument()  # twice is harmless
    uninstrument()
    assert Completions.create is original


def test_responses_api():
    instrument()
    usage = {"input_tokens": 80, "output_tokens": 12, "total_tokens": 92,
             "input_tokens_details": {"cached_tokens": 64}, "output_tokens_details": {"reasoning_tokens": 0}}
    base = {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-4.1-mini", "status": "completed",
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "usage": usage}
    server = Server(
        {**base, "output": [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup_order",
                             "arguments": '{"order_id": "A-1"}', "status": "completed"}]},
        {**base, "output": [{"type": "message", "id": "m_1", "role": "assistant", "status": "completed",
                             "content": [{"type": "output_text", "text": "It was delivered.", "annotations": []}]}]})
    client = openai_client(server)
    with TraceRecorder() as recorder:
        first = client.responses.create(model="gpt-4.1-mini", input="Where is A-1?")
        call = first.output[0]
        client.responses.create(model="gpt-4.1-mini", previous_response_id=first.id,
                                input=[{"type": "function_call_output", "call_id": call.call_id, "output": ORDER}])
    assert [(s["action"]["name"], s["observation"]) for s in recorder.get_trace()] == [("lookup_order", ORDER)]
    assert recorder.final_response == "It was delivered."
    assert recorder.llm_calls[0]["cached_input_tokens"] == 64


# -- Anthropic --------------------------------------------------------------------------

def anthropic_http():
    """The installed Anthropic SDK and the HTTP library it uses (httpx2 from 1.x on, httpx before)."""
    anthropic = pytest.importorskip("anthropic")
    client_class = next(c for c in anthropic.DefaultHttpxClient.__mro__ if c.__name__ == "Client")
    return anthropic, importlib.import_module(client_class.__module__.split(".")[0])


def anthropic_client(server):
    anthropic, http = anthropic_http()
    return anthropic.Anthropic(api_key="test", base_url="http://test", max_retries=0,
                               http_client=http.Client(transport=http.MockTransport(server)))


def claude(content, stop="end_turn", input_tokens=300, output_tokens=40, cached=0):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}}


def test_anthropic_tool_loop_with_a_failed_tool():
    instrument()
    _, http = anthropic_http()
    server = Server(
        claude([{"type": "text", "text": "I'll issue the refund."},
                {"type": "tool_use", "id": "toolu_1", "name": "issue_refund", "input": {"order_id": "A-1", "amount": 40}}],
               stop="tool_use", cached=200),
        claude([{"type": "text", "text": "Your refund has been issued."}]), http=http)
    client = anthropic_client(server)
    with TraceRecorder() as recorder:
        messages = [{"role": "user", "content": "Refund A-1"}]
        while True:
            reply = client.messages.create(model="claude-sonnet-5-5", max_tokens=500, messages=messages)
            calls = [block for block in reply.content if block.type == "tool_use"]
            if not calls:
                break
            messages.append({"role": "assistant", "content": [block.model_dump() for block in reply.content]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": "payment gateway timeout", "is_error": True}
                for call in calls]})
    step = recorder.get_trace()[0]
    assert (step["action"]["name"], step["observation"], step["thought"]) == (
        "issue_refund", "ERROR: payment gateway timeout", "I'll issue the refund.")
    assert recorder.llm_calls[0] == {"model": "claude-sonnet-5-5", "input_tokens": 500, "output_tokens": 40,
                                     "cached_input_tokens": 200}
    report = evaluate_trace({"scenario_id": "refund", "expected_tools": ["issue_refund"]}, recorder)
    assert not report.passed  # the answer claims a refund that failed
    assert any("Reasoning faithfulness" in failure for failure in report.failures)


def test_anthropic_stream():
    instrument()
    events = [
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                              "model": "claude-sonnet-5-5", "content": [], "stop_reason": None,
                                              "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_9",
                                                                      "name": "lookup_order", "input": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"order_id": "A-'}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '1"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 25}},
        {"type": "message_stop"},
    ]
    _, http = anthropic_http()
    server = Server(sse(events, named=True, http=http), http=http)
    with TraceRecorder() as recorder:
        for _event in anthropic_client(server).messages.create(model="claude-sonnet-5-5", max_tokens=100, stream=True,
                                                              messages=[{"role": "user", "content": "A-1?"}]):
            pass
    assert recorder.llm_calls == [{"model": "claude-sonnet-5-5", "input_tokens": 120, "output_tokens": 25}]
    step = recorder.get_trace()[0]  # never answered, so recorded when the run ended
    assert (step["action"]["name"], step["action"]["args"], step["unconfirmed"]) == ("lookup_order", {"order_id": "A-1"}, True)


# -- Gemini -------------------------------------------------------------------------------

def gemini_client(server):
    genai = pytest.importorskip("google.genai")
    from google.genai import types

    return genai.Client(api_key="test", http_options=types.HttpOptions(
        base_url="http://test", httpx_client=httpx.Client(transport=httpx.MockTransport(server))))


def gemini(parts, prompt=90, output=15):
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": output,
                              "totalTokenCount": prompt + output},
            "modelVersion": "gemini-2.5-flash"}


def test_gemini_manual_function_calling():
    instrument()
    from google.genai import types

    server = Server(gemini([{"functionCall": {"name": "lookup_order", "args": {"order_id": "A-1"}}}]),
                    gemini([{"text": "Order A-1 was delivered."}], prompt=140, output=9))
    client = gemini_client(server)
    config = types.GenerateContentConfig(automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    with TraceRecorder() as recorder:
        contents = [types.Content(role="user", parts=[types.Part(text="Where is A-1?")])]
        reply = client.models.generate_content(model="gemini-2.5-flash", contents=contents, config=config)
        call = reply.function_calls[0]
        contents += [reply.candidates[0].content,
                     types.Content(role="user", parts=[types.Part.from_function_response(
                         name=call.name, response={"result": ORDER})])]
        client.models.generate_content(model="gemini-2.5-flash", contents=contents, config=config)
    assert [(s["action"]["name"], s["action"]["args"], s["observation"]) for s in recorder.get_trace()] == [
        ("lookup_order", {"order_id": "A-1"}, ORDER)]
    assert recorder.final_response == "Order A-1 was delivered."
    assert [(c["model"], c["input_tokens"], c["output_tokens"]) for c in recorder.llm_calls] == [
        ("gemini-2.5-flash", 90, 15), ("gemini-2.5-flash", 140, 9)]


def test_gemini_automatic_function_calling_is_recorded_and_guarded():
    instrument()
    from google.genai import types

    looked_up, deleted = [], []

    def lookup_order(order_id: str) -> str:
        """Look up an order by id."""
        looked_up.append(order_id)
        return ORDER

    def delete_order(order_id: str) -> str:
        """Delete an order."""
        deleted.append(order_id)
        return "deleted"

    server = Server(gemini([{"functionCall": {"name": "lookup_order", "args": {"order_id": "A-1"}}}]),
                    gemini([{"text": "Delivered."}]))
    config = types.GenerateContentConfig(tools=[lookup_order])
    with TraceRecorder() as recorder:
        reply = gemini_client(server).models.generate_content(model="gemini-2.5-flash", contents="Where is A-1?",
                                                              config=config)
    assert reply.text == "Delivered." and looked_up == ["A-1"]  # the SDK ran the function itself
    assert [(s["action"]["name"], s["observation"]) for s in recorder.get_trace()] == [("lookup_order", ORDER)]
    assert len(recorder.llm_calls) == 2  # both turns of the automatic loop

    server = Server(gemini([{"functionCall": {"name": "delete_order", "args": {"order_id": "A-1"}}}]),
                    gemini([{"text": "Deleted."}]))
    guard = Guard({"forbidden_tools": ["delete_order"]})
    with pytest.raises(ActionBlocked, match="'delete_order' is a forbidden tool"):
        with TraceRecorder(guard=guard):
            gemini_client(server).models.generate_content(
                model="gemini-2.5-flash", contents="Delete A-1", config=types.GenerateContentConfig(tools=[delete_order]))
    assert deleted == []  # blocked before the SDK could run it
