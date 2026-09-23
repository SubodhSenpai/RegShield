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
                  *, thought: str | None = None, agent: str | None = None) -> dict[str, Any]:
        """Record a tool call and what it returned (use ``"ERROR: ..."`` for failures).

        ``agent`` names who made the call; it defaults to the current agent. Pass it
        when agents run concurrently, so calls aren't credited to the wrong one.
        """
        action = {"type": "tool_call", "name": name, "args": dict(args or {})}
        fields: dict[str, Any] = {"observation": _jsonable(observation)}
        if agent:
            fields["agent"] = agent
        return self._add(action, thought, **fields)

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

    def wrap(self, fn: Callable | None = None, *, name: str | None = None, agent: str | None = None) -> Callable:
        """Wrap a tool so each call is recorded with its arguments and result or error.

        Use as ``@recorder.tool``, ``@recorder.tool(name="search")`` or
        ``recorder.wrap(fn)``. Exceptions are recorded and re-raised unchanged.
        ``agent`` credits every call to that agent (see ``tool_call``).
        """
        if fn is None:
            return lambda f: self.wrap(f, name=name, agent=agent)
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
                self.tool_call(tool_name, call_args, result, agent=agent)
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
            self.tool_call(tool_name, call_args, result, agent=agent)
            return result
        return wrapper

    tool = wrap

    # -- output ----------------------------------------------------------------

    def get_trace(self) -> list[dict[str, Any]]:
        """The recorded steps, ready for ``evaluate_trace``."""
        with self._lock:
            return [dict(step) for step in self.steps]
