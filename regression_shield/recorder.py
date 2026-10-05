"""Record a RegShield trace from any agent, in any framework.

Use a ``TraceRecorder`` when there is no ready-made adapter for your agent, or
to capture agentic patterns (plans, handoffs, approvals, routing, graph nodes,
parallel calls, draft/critique loops). Pass it straight to ``evaluate_trace``.
"""

from __future__ import annotations

import functools
import inspect
import itertools
import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """Keep JSON-friendly values as they are; turn anything else into text."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _bind_args(signature: inspect.Signature | None, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Arguments of a call as a name -> value dict, including defaults."""
    if signature is not None:
        try:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            call_args: dict[str, Any] = {}
            for name, value in bound.arguments.items():
                kind = signature.parameters[name].kind
                if name in ("self", "cls"):
                    continue
                if kind is inspect.Parameter.VAR_KEYWORD:
                    call_args.update({k: _jsonable(v) for k, v in value.items()})
                else:
                    call_args[name] = _jsonable(value)
            return call_args
        except TypeError:
            pass
    call_args = {f"arg{i}": _jsonable(value) for i, value in enumerate(args)}
    call_args.update({k: _jsonable(v) for k, v in kwargs.items()})
    return call_args


class TraceRecorder:
    """Builds a trace while your agent runs: tool calls plus agentic-pattern events.

    Example:
        recorder = TraceRecorder(agent="triage")

        @recorder.tool                       # every call is recorded, errors included
        def lookup_order(order_id: str) -> dict: ...

        recorder.thought("I need the order first.")
        lookup_order("A-1")
        recorder.handoff("billing")          # later steps belong to "billing"
        recorder.approval("issue_refund", approved=True)

        report = evaluate_trace(scenario, recorder)
    """

    def __init__(self, agent: str | None = None):
        self._initial_agent = agent
        self._lock = threading.Lock()
        self._group_ids = itertools.count(1)
        self.reset()

    def reset(self) -> None:
        """Clear everything recorded so far."""
        with self._lock:
            self.steps: list[dict[str, Any]] = []
            self.llm_calls: list[dict[str, Any]] = []  # token usage, kept apart from the steps
            self.final_response = ""
            self.current_agent: str | None = self._initial_agent
            self.current_node: str | None = None
            self._pending_thought: str | None = None
            self._parallel_group: str | None = None

    # -- context ---------------------------------------------------------------

    def thought(self, text: str) -> None:
        """Attach reasoning to the next recorded step."""
        self._pending_thought = text

    @contextmanager
    def parallel(self, group: str | None = None) -> Iterator[str]:
        """Steps recorded inside this block ran concurrently.

        Example:
            with recorder.parallel():
                fetch_weather("SF")
                fetch_flights("SF")
        """
        previous = self._parallel_group
        self._parallel_group = group or f"p{next(self._group_ids)}"
        try:
            yield self._parallel_group
        finally:
            self._parallel_group = previous

    # -- events ----------------------------------------------------------------

    def _add(self, action: dict[str, Any], thought: str | None = None, **fields: Any) -> dict[str, Any]:
        with self._lock:
            step: dict[str, Any] = {"step_index": len(self.steps) + 1}
            if self.current_agent:
                step["agent"] = self.current_agent
            if self.current_node:
                step["node"] = self.current_node
            if self._parallel_group is not None:
                step["parallel_group"] = self._parallel_group
            text = thought if thought is not None else self._pending_thought
            self._pending_thought = None
            if text:
                step["thought"] = text
            step["action"] = action
            step.update(fields)
            self.steps.append(step)
        logger.debug("Recorded step %d: %s%s", step["step_index"], action["type"],
                     f" {action['name']}" if action.get("name") else "")
        return step

    def tool_call(self, name: str, args: dict[str, Any] | None = None, observation: Any = "",
                  *, thought: str | None = None, agent: str | None = None,
                  cost_usd: float | None = None) -> dict[str, Any]:
        """Record a tool call and what it returned (use ``"ERROR: ..."`` for failures).

        ``agent`` names who made the call; it defaults to the current agent. Pass it
        when agents run concurrently, so calls aren't credited to the wrong one.
        ``cost_usd`` is what the call cost, for paid APIs (search, SMS, data providers).
        """
        action = {"type": "tool_call", "name": name, "args": dict(args or {})}
        fields: dict[str, Any] = {"observation": _jsonable(observation)}
        if agent:
            fields["agent"] = agent
        if cost_usd is not None:
            fields["cost_usd"] = float(cost_usd)
        return self._add(action, thought, **fields)

    def llm_call(self, model: str, input_tokens: int = 0, output_tokens: int = 0, *,
                 cached_input_tokens: int = 0, cache_write_tokens: int = 0,
                 cost_usd: float | None = None, agent: str | None = None) -> dict[str, Any]:
        """Record the token usage of one model call, for cost tracking and budgets.

        ``input_tokens`` counts all input tokens, including ``cached_input_tokens``
        (read from the provider's prompt cache) and ``cache_write_tokens``. Pass
        ``cost_usd`` when the provider reports the real cost; otherwise RegShield
        prices the call from the model's list price. Usage is kept apart from the
        steps, so it never changes step numbers.
        """
        call: dict[str, Any] = {"model": str(model), "input_tokens": int(input_tokens),
                                "output_tokens": int(output_tokens)}
        if cached_input_tokens:
            call["cached_input_tokens"] = int(cached_input_tokens)
        if cache_write_tokens:
            call["cache_write_tokens"] = int(cache_write_tokens)
        if cost_usd is not None:
            call["cost_usd"] = float(cost_usd)
        agent = agent or self.current_agent
        if agent:
            call["agent"] = agent
        with self._lock:
            self.llm_calls.append(call)
        logger.debug("Recorded LLM call: %s, %d in / %d out", call["model"], call["input_tokens"], call["output_tokens"])
        return call

    def llm_response(self, response: Any, *, model: str | None = None, agent: str | None = None) -> dict[str, Any] | None:
        """Record the token usage of a model response: an OpenAI, Anthropic or Gemini SDK
        response, a LangChain message, or a dict of one. Returns the record, or None if
        the response has no usage (nothing is recorded then)."""
        usage = usage_from_response(response)
        if usage is None:
            return None
        reported_model = usage.pop("model", None)
        return self.llm_call(model or reported_model or "unknown", agent=agent, **usage)

    def plan(self, steps: Iterable[Any], *, thought: str | None = None) -> dict[str, Any]:
        """Record a plan: tool names in the order the agent intends to run them."""
        return self._add({"type": "plan", "steps": list(steps)}, thought)

    def handoff(self, to: str, *, thought: str | None = None) -> dict[str, Any]:
        """Record control passing to another agent; later steps belong to it."""
        step = self._add({"type": "handoff", "to": to}, thought)
        self.current_agent = to
        return step

    def approval(self, tool: str | None = None, approved: bool = True, *, by: str | None = None) -> dict[str, Any]:
        """Record a human approval decision for the next call to ``tool`` (or to any guarded tool)."""
        action: dict[str, Any] = {"type": "approval", "approved": bool(approved)}
        if tool:
            action["tool"] = tool
        if by:
            action["by"] = by
        return self._add(action)

    def route(self, to: str, *, thought: str | None = None) -> dict[str, Any]:
        """Record a router's decision."""
        return self._add({"type": "route", "to": to}, thought)

    def node(self, name: str) -> dict[str, Any]:
        """Record entering a graph node; later steps are tagged with it."""
        self.current_node = name
        return self._add({"type": "node", "name": name})

    def draft(self, content: str) -> dict[str, Any]:
        """Record an output produced by the generator in an evaluator-optimizer loop."""
        return self._add({"type": "draft", "content": content})

    def critique(self, approved: bool, feedback: str = "") -> dict[str, Any]:
        """Record the evaluator's verdict on the latest draft."""
        return self._add({"type": "critique", "approved": bool(approved), "feedback": feedback})

    def final_answer(self, text: Any) -> None:
        """Record the agent's final response (checked for claims that contradict errors)."""
        self.final_response = text if isinstance(text, str) else str(text)

    # -- tools -----------------------------------------------------------------

    def wrap(self, fn: Callable | None = None, *, name: str | None = None, agent: str | None = None,
             cost_usd: float | None = None) -> Callable:
        """Wrap a tool so each call is recorded with its arguments and result or error.

        Use as ``@recorder.tool``, ``@recorder.tool(name="search")`` or
        ``recorder.wrap(fn)``. Exceptions are recorded and re-raised unchanged.
        ``agent`` credits every call to that agent (see ``tool_call``).
        ``cost_usd`` is the price of each call, for paid APIs.
        """
        if fn is None:
            return lambda f: self.wrap(f, name=name, agent=agent, cost_usd=cost_usd)
        tool_name: str = name or getattr(fn, "__name__", None) or "tool"
        try:
            signature: inspect.Signature | None = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

        def record_error(call_args: dict[str, Any], err: Exception) -> None:
            self.tool_call(tool_name, call_args, f"ERROR: {type(err).__name__}: {err}", agent=agent)

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                call_args = _bind_args(signature, args, kwargs)
                try:
                    result = await fn(*args, **kwargs)
                except Exception as err:
                    record_error(call_args, err)
                    raise
                self.tool_call(tool_name, call_args, result, agent=agent, cost_usd=cost_usd)
                return result
            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            call_args = _bind_args(signature, args, kwargs)
            try:
                result = fn(*args, **kwargs)
            except Exception as err:
                record_error(call_args, err)
                raise
            self.tool_call(tool_name, call_args, result, agent=agent, cost_usd=cost_usd)
            return result
        return wrapper

    tool = wrap

    # -- output ----------------------------------------------------------------

    def get_trace(self) -> list[dict[str, Any]]:
        """The recorded steps, ready for ``evaluate_trace``."""
        with self._lock:
            return [dict(step) for step in self.steps]

    def to_dict(self) -> dict[str, Any]:
        """The whole run as one JSON-ready dict: steps, final response and LLM usage.
        Save it as a ``trace`` in a scenario file for ``regshield eval``."""
        trace: dict[str, Any] = {"steps": self.get_trace(), "final_response": self.final_response}
        with self._lock:
            if self.llm_calls:
                trace["llm_calls"] = [dict(call) for call in self.llm_calls]
        return trace


def _field(obj: Any, *names: str) -> Any:
    """The first of ``names`` found on an object or in a dict."""
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def usage_from_response(response: Any) -> dict[str, Any] | None:
    """Token usage of a model response, in RegShield's fields, or None if it has none.

    Understands OpenAI chat and Responses API objects, Anthropic messages, Gemini
    ``usage_metadata``, LangChain messages (``usage_metadata``) and dicts of them.
    ``input_tokens`` always includes cached tokens (Anthropic reports them apart).
    """
    usage = _field(response, "usage_metadata", "usage")
    if usage is None:
        return None
    model = _field(response, "model", "model_version")
    if model is None:
        metadata = _field(response, "response_metadata") or {}
        model = _field(metadata, "model_name", "model")
    record: dict[str, Any]
    if _field(usage, "prompt_token_count", "candidates_token_count") is not None:  # Gemini
        record = {"input_tokens": _count(_field(usage, "prompt_token_count")),
                  "output_tokens": _count(_field(usage, "candidates_token_count"))
                  + _count(_field(usage, "thoughts_token_count")),
                  "cached_input_tokens": _count(_field(usage, "cached_content_token_count"))}
    elif _field(usage, "cache_read_input_tokens", "cache_creation_input_tokens") is not None:  # Anthropic
        cached = _count(_field(usage, "cache_read_input_tokens"))
        written = _count(_field(usage, "cache_creation_input_tokens"))
        record = {"input_tokens": _count(_field(usage, "input_tokens")) + cached + written,
                  "output_tokens": _count(_field(usage, "output_tokens")),
                  "cached_input_tokens": cached, "cache_write_tokens": written}
    else:  # OpenAI chat / Responses API, LangChain usage_metadata
        details = _field(usage, "prompt_tokens_details", "input_tokens_details", "input_token_details") or {}
        record = {"input_tokens": _count(_field(usage, "prompt_tokens", "input_tokens")),
                  "output_tokens": _count(_field(usage, "completion_tokens", "output_tokens")),
                  "cached_input_tokens": _count(_field(details, "cached_tokens", "cache_read")),
                  "cache_write_tokens": _count(_field(details, "cache_write_tokens", "cache_creation"))}
    if not record["input_tokens"] and not record["output_tokens"]:
        return None
    cost = _field(usage, "cost")  # OpenRouter reports the real cost
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        record["cost_usd"] = float(cost)
    if model:
        record["model"] = str(model)
    return {key: value for key, value in record.items() if value or key in ("input_tokens", "output_tokens")}
