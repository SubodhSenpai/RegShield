"""Record OpenAI, Anthropic and Gemini SDK calls without changing your agent's code.

    import regression_shield as rs
    rs.instrument()                          # once, at startup

    with rs.TraceRecorder(guard=guard) as recorder:
        answer = run_my_agent(question)      # your own loop on the SDK
    report = rs.evaluate_trace(scenario, recorder)

Inside a ``with recorder:`` block every model call made through the SDKs is
recorded with its token usage. Tool calls are rebuilt from the conversation:
the tools a model asks for, and the results your code sends back with the next
request (OpenAI ``tool`` messages and ``function_call_output`` items, Anthropic
``tool_result`` blocks, Gemini ``function_response`` parts, including Gemini's
automatic function calling). A reply without tool calls is the final answer.

With a ``Guard`` on the recorder, a model's request for a tool call that breaks
a rule raises ``ActionBlocked`` from the SDK call, before your code receives the
reply and can run it. A used-up budget stops further model calls the same way.
Tools you wrap with ``@recorder.tool`` are guarded and recorded where they run.

Streaming (``stream=True``) is recorded when the stream ends; for OpenAI chat,
pass ``stream_options={"include_usage": True}`` to get token counts. The
``.stream()`` helper methods aren't captured. Calls made outside a
``with recorder:`` block are left alone.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from regression_shield.recorder import TraceRecorder, _field, active_recorder, usage_from_response

logger = logging.getLogger(__name__)

_patches: list[tuple[Any, str, Any]] = []  # (class, method name, original) for uninstrument()


@dataclass
class _Reply:
    """What one model reply says: model, token usage, text and the tool calls it requests."""

    model: str | None = None
    usage: dict[str, Any] | None = None
    text: str | None = None
    calls: list[tuple[str | None, str, Any]] = field(default_factory=list)


def _arguments(value: Any) -> dict[str, Any]:
    """Tool arguments as a dict (OpenAI sends JSON text)."""
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"input": value}
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {"input": str(value)}


def _text(content: Any) -> str | None:
    """Message text from a string or a list of content parts; None when there is none."""
    if isinstance(content, list):
        pieces = [_field(part, "text") for part in content]
        content = "".join(piece for piece in pieces if isinstance(piece, str))
    return content.strip() or None if isinstance(content, str) else None


def _after_last(items: list[Any], is_model_turn: Callable[[Any], bool]) -> list[Any]:
    """The items after the model's last turn: what's new since its last reply."""
    last = max((position for position, item in enumerate(items) if is_model_turn(item)), default=-1)
    return items[last + 1:]


# -- OpenAI chat completions ---------------------------------------------------------

class _OpenAIChat:
    @staticmethod
    def results(request: dict[str, Any]) -> list[tuple[Any, Any, Any, bool]]:
        messages = list(request.get("messages") or [])
        found = []
        for message in _after_last(messages, lambda m: _field(m, "role") == "assistant"):
            role = _field(message, "role")
            if role == "tool":
                found.append((_field(message, "tool_call_id"), None, _field(message, "content") or "", False))
            elif role == "function":
                found.append((None, _field(message, "name"), _field(message, "content") or "", False))
        return found

    @staticmethod
    def reply(response: Any, request: dict[str, Any]) -> _Reply | None:
        choices = _field(response, "choices")
        if not choices:
            return None
        message = _field(choices[0], "message")
        calls: list[tuple[str | None, str, Any]] = []
        for call in _field(message, "tool_calls") or []:
            function = _field(call, "function")
            if function is not None:
                calls.append((_field(call, "id"), str(_field(function, "name") or "tool"),
                               _arguments(_field(function, "arguments"))))
            elif (custom := _field(call, "custom")) is not None:
                calls.append((_field(call, "id"), str(_field(custom, "name") or "tool"), {"input": _field(custom, "input")}))
        legacy = _field(message, "function_call")
        if legacy is not None and not calls:
            calls.append((None, str(_field(legacy, "name") or "tool"), _arguments(_field(legacy, "arguments"))))
        return _Reply(_field(response, "model") or request.get("model"), usage_from_response(response),
                      _text(_field(message, "content")), calls)

    class Stream:
        def __init__(self, request: dict[str, Any]):
            self.request = request
            self.model: str | None = None
            self.usage: dict[str, Any] | None = None
            self.text: list[str] = []
            self.calls: dict[int, dict[str, Any]] = {}

        def add(self, chunk: Any) -> None:
            self.model = _field(chunk, "model") or self.model
            if _field(chunk, "usage") is not None:
                self.usage = usage_from_response(chunk) or self.usage
            for choice in _field(chunk, "choices") or []:
                delta = _field(choice, "delta")
                if delta is None:
                    continue
                content = _field(delta, "content")
                if isinstance(content, str):
                    self.text.append(content)
                for part in _field(delta, "tool_calls") or []:
                    index = _field(part, "index")
                    entry = self.calls.setdefault(index if isinstance(index, int) else len(self.calls),
                                                  {"id": None, "name": "", "arguments": ""})
                    entry["id"] = _field(part, "id") or entry["id"]
                    function = _field(part, "function")
                    if function is not None:
                        entry["name"] = entry["name"] or _field(function, "name") or ""
                        arguments = _field(function, "arguments")
                        if isinstance(arguments, str):
                            entry["arguments"] += arguments

        def reply(self) -> _Reply:
            calls = [(entry["id"], entry["name"] or "tool", _arguments(entry["arguments"]))
                     for _, entry in sorted(self.calls.items())]
            return _Reply(self.model or self.request.get("model"), self.usage, _text("".join(self.text)), calls)


# -- OpenAI Responses API ------------------------------------------------------------

class _OpenAIResponses:
    @staticmethod
    def results(request: dict[str, Any]) -> list[tuple[Any, Any, Any, bool]]:
        items = request.get("input")
        if not isinstance(items, list):
            return []

        def is_model_turn(item: Any) -> bool:
            return _field(item, "type") == "function_call" or _field(item, "role") == "assistant"

        return [(_field(item, "call_id"), None, _field(item, "output") or "", False)
                for item in _after_last(items, is_model_turn) if _field(item, "type") == "function_call_output"]

    @staticmethod
    def reply(response: Any, request: dict[str, Any]) -> _Reply | None:
        output = _field(response, "output")
        if not isinstance(output, list):
            return None
        calls: list[tuple[str | None, str, Any]] = []
        texts: list[str] = []
        for item in output:
            kind = _field(item, "type")
            if kind == "function_call":
                calls.append((_field(item, "call_id"), str(_field(item, "name") or "tool"),
                               _arguments(_field(item, "arguments"))))
            elif kind == "message":
                texts += [_field(part, "text") or "" for part in _field(item, "content") or []
                          if _field(part, "type") == "output_text"]
        return _Reply(_field(response, "model") or request.get("model"), usage_from_response(response),
                      _text("\n".join(texts)), calls)

    class Stream:
        def __init__(self, request: dict[str, Any]):
            self.request = request
            self.final: Any = None

        def add(self, event: Any) -> None:
            if _field(event, "type") in ("response.completed", "response.incomplete", "response.failed"):
                self.final = _field(event, "response")

        def reply(self) -> _Reply | None:
            return _OpenAIResponses.reply(self.final, self.request) if self.final is not None else None


# -- Anthropic messages --------------------------------------------------------------

class _AnthropicMessages:
    @staticmethod
    def results(request: dict[str, Any]) -> list[tuple[Any, Any, Any, bool]]:
        messages = list(request.get("messages") or [])
        found = []
        for message in _after_last(messages, lambda m: _field(m, "role") == "assistant"):
            content = _field(message, "content")
            for block in content if isinstance(content, list) else []:
                if _field(block, "type") == "tool_result":
                    found.append((_field(block, "tool_use_id"), None, _field(block, "content") or "",
                                  bool(_field(block, "is_error"))))
        return found

    @staticmethod
    def reply(response: Any, request: dict[str, Any]) -> _Reply | None:
        content = _field(response, "content")
        if not isinstance(content, list):
            return None
        texts: list[str] = []
        calls: list[tuple[str | None, str, Any]] = []
        for block in content:
            kind = _field(block, "type")
            if kind == "text":
                texts.append(_field(block, "text") or "")
            elif kind == "tool_use":
                calls.append((_field(block, "id"), str(_field(block, "name") or "tool"), _arguments(_field(block, "input"))))
        return _Reply(_field(response, "model") or request.get("model"), usage_from_response(response),
                      _text("\n".join(texts)), calls)

    class Stream:
        _USAGE = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

        def __init__(self, request: dict[str, Any]):
            self.request = request
            self.model: str | None = None
            self.usage: dict[str, Any] = {}
            self.blocks: dict[int, dict[str, Any]] = {}

        def _take_usage(self, usage: Any) -> None:
            for name in self._USAGE:
                value = _field(usage, name)
                if value is not None:
                    self.usage[name] = value

        def add(self, event: Any) -> None:
            kind = _field(event, "type")
            if kind == "message_start":
                message = _field(event, "message")
                self.model = _field(message, "model") or self.model
                self._take_usage(_field(message, "usage"))
            elif kind == "content_block_start":
                block = _field(event, "content_block")
                self.blocks[_field(event, "index") or 0] = {
                    "type": _field(block, "type"), "text": _field(block, "text") or "", "id": _field(block, "id"),
                    "name": _field(block, "name"), "json": ""}
            elif kind == "content_block_delta":
                entry = self.blocks.get(_field(event, "index") or 0)
                delta = _field(event, "delta")
                if entry is not None and delta is not None:
                    entry["text"] += _field(delta, "text") or ""
                    entry["json"] += _field(delta, "partial_json") or ""
            elif kind == "message_delta" and _field(event, "usage") is not None:
                self._take_usage(_field(event, "usage"))

        def reply(self) -> _Reply | None:
            content: list[dict[str, Any]] = []
            for _, block in sorted(self.blocks.items()):
                if block["type"] == "text":
                    content.append({"type": "text", "text": block["text"]})
                elif block["type"] == "tool_use":
                    content.append({"type": "tool_use", "id": block["id"], "name": block["name"],
                                    "input": _arguments(block["json"])})
            return _AnthropicMessages.reply({"model": self.model, "content": content, "usage": self.usage}, self.request)


# -- Gemini (google-genai) -------------------------------------------------------------

def _gemini_parts(content: Any) -> list[Any]:
    parts = _field(content, "parts")
    if isinstance(parts, list):
        return parts
    return [content] if _field(content, "function_response", "function_call", "text") is not None else []


def _gemini_output(result: Any) -> Any:
    """A function_response's result: {"result": x} and {"output": x} are just x."""
    if isinstance(result, dict) and len(result) == 1 and next(iter(result)) in ("result", "output", "content"):
        return next(iter(result.values()))
    return result


class _Gemini:
    @staticmethod
    def results(request: dict[str, Any]) -> list[tuple[Any, Any, Any, bool]]:
        contents = request.get("contents")
        items = contents if isinstance(contents, list) else [] if contents is None else [contents]
        found = []
        for content in _after_last(items, lambda c: _field(c, "role") == "model"):
            for part in _gemini_parts(content):
                response = _field(part, "function_response")
                if response is not None:
                    result = _field(response, "response")
                    found.append((_field(response, "id"), _field(response, "name"), _gemini_output(result),
                                  isinstance(result, dict) and "error" in result))
        return found

    @staticmethod
    def parse(response: Any) -> tuple[list[str], list[tuple[str | None, str, Any]]] | None:
        candidates = _field(response, "candidates")
        if candidates is None:
            return None
        texts: list[str] = []
        calls: list[tuple[str | None, str, Any]] = []
        for part in _gemini_parts(_field(candidates[0], "content")) if candidates else []:
            call = _field(part, "function_call")
            if call is not None:
                calls.append((_field(call, "id"), str(_field(call, "name") or "tool"), _arguments(_field(call, "args"))))
            elif isinstance(_field(part, "text"), str) and not _field(part, "thought"):
                texts.append(_field(part, "text"))
        return texts, calls

    @staticmethod
    def reply(response: Any, request: dict[str, Any]) -> _Reply | None:
        parsed = _Gemini.parse(response)
        if parsed is None:
            return None
        texts, calls = parsed
        return _Reply(_field(response, "model_version") or request.get("model"), usage_from_response(response),
                      _text("".join(texts)), calls)

    class Stream:
        def __init__(self, request: dict[str, Any]):
            self.request = request
            self.model: str | None = None
            self.usage: dict[str, Any] | None = None
            self.texts: list[str] = []
            self.calls: list[tuple[str | None, str, Any]] = []

        def add(self, chunk: Any) -> None:
            parsed = _Gemini.parse(chunk)
            if parsed is not None:
                self.texts += parsed[0]
                self.calls += parsed[1]
            self.model = _field(chunk, "model_version") or self.model
            self.usage = usage_from_response(chunk) or self.usage

        def reply(self) -> _Reply:
            return _Reply(self.model or self.request.get("model"), self.usage, _text("".join(self.texts)), self.calls)


# -- recording one call ---------------------------------------------------------------

class _Call:
    """One SDK call made inside a ``with recorder:`` block."""

    def __init__(self, recorder: TraceRecorder, adapter: Any, request: dict[str, Any]):
        self.recorder = recorder
        self.adapter = adapter
        self.request = request
        self.started = time.time()
        try:
            results = adapter.results(request)
            if results:
                recorder._tool_results(results)
        except Exception as err:  # recording must never break the SDK call
            logger.debug("Could not read tool results from a request: %s", err)
        recorder.check_llm()  # a used-up budget raises ActionBlocked: the request isn't sent

    def reply(self, response: Any) -> _Reply | None:
        try:
            return self.adapter.reply(response, self.request)
        except Exception as err:
            logger.debug("Could not read a model reply: %s", err)
            return None

    def done(self, reply: _Reply | None) -> None:
        if reply is None:
            return
        try:
            usage = dict(reply.usage or {})
            model = usage.pop("model", None) or reply.model or "unknown"
            self.recorder.llm_call(str(model), timing=(self.started, time.time()), **usage)
        except Exception as err:
            logger.debug("Could not record a model call: %s", err)
        if reply.calls:
            self.recorder._model_requested(reply.calls, reply.text)  # may raise ActionBlocked
        elif reply.text:
            self.recorder.final_answer(reply.text)


class _SyncStream:
    """Passes a stream through unchanged and records the call when it ends."""

    def __init__(self, stream: Any, call: _Call, collector: Any):
        self._stream = stream
        self._call = call
        self._collector = collector
        self._iterator: Any = None
        self._finished = False

    def __iter__(self) -> _SyncStream:
        return self

    def __next__(self) -> Any:
        if self._iterator is None:
            self._iterator = iter(self._stream)
        try:
            item = next(self._iterator)
        except StopIteration:
            self._finish()
            raise
        _collect(self._collector, item)
        return item

    def _finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._call.done(_collected(self._collector))

    def __enter__(self) -> _SyncStream:
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, *exc: Any) -> Any:
        try:
            if exc[0] is None:
                self._finish()
        finally:
            exit_ = getattr(self._stream, "__exit__", None)
            result = exit_(*exc) if exit_ is not None else None
        return result

    def close(self) -> None:
        self._finish()
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _AsyncStream:
    """The async version of ``_SyncStream``."""

    def __init__(self, stream: Any, call: _Call, collector: Any):
        self._stream = stream
        self._call = call
        self._collector = collector
        self._iterator: Any = None
        self._finished = False

    def __aiter__(self) -> _AsyncStream:
        return self

    async def __anext__(self) -> Any:
        if self._iterator is None:
            self._iterator = self._stream.__aiter__()
        try:
            item = await self._iterator.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        _collect(self._collector, item)
        return item

    def _finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._call.done(_collected(self._collector))

    async def __aenter__(self) -> _AsyncStream:
        enter = getattr(self._stream, "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        try:
            if exc[0] is None:
                self._finish()
        finally:
            exit_ = getattr(self._stream, "__aexit__", None)
            result = await exit_(*exc) if exit_ is not None else None
        return result

    async def close(self) -> None:
        self._finish()
        for name in ("close", "aclose"):
            close = getattr(self._stream, name, None)
            if close is not None:
                await close()
                return

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _collect(collector: Any, item: Any) -> None:
    try:
        collector.add(item)
    except Exception as err:
        logger.debug("Could not read a stream chunk: %s", err)


def _collected(collector: Any) -> _Reply | None:
    try:
        reply: _Reply | None = collector.reply()
        return reply
    except Exception as err:
        logger.debug("Could not read a finished stream: %s", err)
        return None


# -- patching -----------------------------------------------------------------------

def _capturing() -> TraceRecorder | None:
    recorder = active_recorder()
    return recorder if recorder is not None and recorder.sdk_capture else None


def _wrapper(original: Callable[..., Any], adapter: Any, *, is_async: bool, streams: bool) -> Callable[..., Any]:
    """``streams``: the method always returns a stream (Gemini's *_stream methods)."""
    if is_async:
        @functools.wraps(original)
        async def async_method(self: Any, *args: Any, **kwargs: Any) -> Any:
            recorder = _capturing()
            if recorder is None:
                return await original(self, *args, **kwargs)
            call = _Call(recorder, adapter, kwargs)
            result = await original(self, *args, **kwargs)
            if streams or kwargs.get("stream") is True:
                return _AsyncStream(result, call, adapter.Stream(kwargs))
            call.done(call.reply(result))
            return result
        return async_method

    @functools.wraps(original)
    def method(self: Any, *args: Any, **kwargs: Any) -> Any:
        recorder = _capturing()
        if recorder is None:
            return original(self, *args, **kwargs)
        call = _Call(recorder, adapter, kwargs)
        result = original(self, *args, **kwargs)
        if streams or kwargs.get("stream") is True:
            return _SyncStream(result, call, adapter.Stream(kwargs))
        call.done(call.reply(result))
        return result
    return method


def _patch(owner: Any, name: str, adapter: Any, *, is_async: bool, streams: bool = False) -> bool:
    original = owner.__dict__.get(name)
    if original is None:
        return False
    if getattr(original, "__regshield_original__", None) is not None:
        return True  # already instrumented
    wrapper = _wrapper(original, adapter, is_async=is_async, streams=streams)
    wrapper.__regshield_original__ = original  # type: ignore[attr-defined]
    setattr(owner, name, wrapper)
    _patches.append((owner, name, original))
    return True


def _instrument_openai() -> bool:
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions
    except ImportError:
        return False
    done = _patch(Completions, "create", _OpenAIChat, is_async=False)
    _patch(AsyncCompletions, "create", _OpenAIChat, is_async=True)
    _patch(Completions, "parse", _OpenAIChat, is_async=False)
    _patch(AsyncCompletions, "parse", _OpenAIChat, is_async=True)
    try:
        from openai.resources.responses import AsyncResponses, Responses
    except ImportError:
        return done
    for method in ("create", "parse"):
        _patch(Responses, method, _OpenAIResponses, is_async=False)
        _patch(AsyncResponses, method, _OpenAIResponses, is_async=True)
    return done


def _instrument_anthropic() -> bool:
    try:
        from anthropic.resources.messages import AsyncMessages, Messages
    except ImportError:
        return False
    done = _patch(Messages, "create", _AnthropicMessages, is_async=False)
    _patch(AsyncMessages, "create", _AnthropicMessages, is_async=True)
    return done


def _instrument_gemini() -> bool:
    try:
        from google.genai import models
    except ImportError:
        return False
    done = False
    for owner, is_async in ((models.Models, False), (models.AsyncModels, True)):
        # The private methods run once per model turn, including each turn of automatic
        # function calling, so every turn's usage and requested calls are seen
        prefix = "_" if "_generate_content" in owner.__dict__ else ""
        done = _patch(owner, f"{prefix}generate_content", _Gemini, is_async=is_async) or done
        _patch(owner, f"{prefix}generate_content_stream", _Gemini, is_async=is_async, streams=True)
    return done


def instrument(*, openai: bool = True, anthropic: bool = True, gemini: bool = True) -> list[str]:
    """Record the installed OpenAI, Anthropic and Gemini SDKs' calls inside ``with recorder:``
    blocks. Returns the SDKs instrumented. Calling it again is harmless; ``uninstrument``
    undoes it."""
    done = []
    if openai and _instrument_openai():
        done.append("openai")
    if anthropic and _instrument_anthropic():
        done.append("anthropic")
    if gemini and _instrument_gemini():
        done.append("gemini")
    logger.debug("Instrumented: %s", ", ".join(done) or "nothing (no supported SDK installed)")
    return done


def uninstrument() -> None:
    """Restore the SDKs' original methods."""
    while _patches:
        owner, name, original = _patches.pop()
        setattr(owner, name, original)
