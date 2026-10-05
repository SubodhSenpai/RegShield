"""Record a RegShield trace from any agent, in any framework.

Use a ``TraceRecorder`` when there is no ready-made adapter for your agent, or
to capture agentic patterns (plans, handoffs, approvals, routing, graph nodes,
parallel calls, draft/critique loops). Pass it straight to ``evaluate_trace``.

In production, give it a ``Guard`` to block risky calls before they run, and
use it as a context manager (``with recorder:``) so ``instrument()`` records the
OpenAI, Anthropic and Gemini SDK calls made inside the block. With
``export_traces`` configured, each run is also streamed to your monitoring service.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import itertools
import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, NoReturn

from regression_shield.export import current_pipeline, llm_event, step_event
from regression_shield.guard import ActionBlocked, Guard, Verdict, blocked_observation

logger = logging.getLogger(__name__)

# The recorders of the `with recorder:` blocks the current code runs in (innermost last)
_ACTIVE: contextvars.ContextVar[tuple[Any, ...]] = contextvars.ContextVar("regshield_recorders", default=())


def active_recorder() -> TraceRecorder | None:
    """The recorder of the innermost ``with recorder:`` block this code runs in, if any."""
    stack = _ACTIVE.get()
    return stack[-1] if stack else None


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


def _result_text(output: Any) -> str:
    """A tool result sent back to a model (text, content parts or an object) as text."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = [part.get("text") if isinstance(part, dict) else getattr(part, "text", None) for part in output]
        texts = [part for part in parts if isinstance(part, str)]
        if texts and len(texts) == len(parts):
            return "\n".join(texts)
    try:
        return json.dumps(output, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(output)


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

    ``guard``: a ``Guard`` whose rules are checked before each wrapped tool runs (see
    ``check``). ``export=False`` keeps this recorder's runs out of ``export_traces``.
    """

    # instrument() records SDK model calls into a recorder while it's active (`with recorder:`)
    sdk_capture = True

    def __init__(self, agent: str | None = None, *, guard: Guard | None = None, export: bool = True):
        self._initial_agent = agent
        self.guard = guard
        self.export = export
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._group_ids = itertools.count(1)
        self._wrapped_tools: set[str] = set()  # tools whose calls are guarded where they run
        self._run: Any = None                   # the current run's export, while exporting
        self._run_name: str | None = None
        self._run_attributes: dict[str, Any] = {}
        self.reset()

    def reset(self) -> None:
        """Clear everything recorded so far (and end the current exported run)."""
        self.end_run()
        with self._lock:
            self.steps: list[dict[str, Any]] = []
            self.llm_calls: list[dict[str, Any]] = []  # token usage, kept apart from the steps
            self.final_response = ""
            self.current_agent: str | None = self._initial_agent
            self.current_node: str | None = None
            self._pending_thought: str | None = None
            self._parallel_group: str | None = None
            self._in_flight: Counter = Counter()  # calls the guard allowed that aren't recorded yet
            self._pending_warnings: dict[str, dict[str, str]] = {}
            self._sdk_calls: dict[str, dict[str, Any]] = {}  # model-requested calls awaiting results
            self._sdk_responses = 0

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

    def __enter__(self) -> TraceRecorder:
        """Make this the active recorder: ``instrument()`` records SDK calls made inside the
        block, and an exported run spans the block."""
        _ACTIVE.set((*_ACTIVE.get(), self))
        self._current_run()
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        try:
            self.end_run(error=exc)
        finally:
            stack = list(_ACTIVE.get())
            for position in range(len(stack) - 1, -1, -1):
                if stack[position] is self:
                    del stack[position]
                    break
            _ACTIVE.set(tuple(stack))

    # -- runs (for export_traces) ------------------------------------------------

    def start_run(self, name: str | None = None, **attributes: Any) -> TraceRecorder:
        """Start a new exported run, ending the current one. ``name`` and ``attributes``
        (a user or session id...) are sent with it. The trace isn't cleared: see ``reset``."""
        self.end_run()
        self._run_name, self._run_attributes = name, dict(attributes)
        self._current_run()
        return self

    def end_run(self, error: BaseException | None = None) -> None:
        """Finish the current run: tool calls a model requested whose results never came back
        are recorded (``unconfirmed``), and the run's summary is exported."""
        if getattr(self, "_sdk_calls", None):
            self._record_unanswered_calls()
        with self._run_lock:
            run, self._run = self._run, None
        if run is not None:
            try:
                run.end(self._run_summary(error, run.pipeline.pricing))
            except Exception as err:  # exporting must never break the agent
                logger.warning("Could not export the end of a run: %s", err)

    def _current_run(self) -> Any:
        if not self.export or current_pipeline() is None and self._run is None:
            return None
        if self._run is None:
            with self._run_lock:
                pipeline = current_pipeline()
                if self._run is None and pipeline is not None:
                    self._run = pipeline.begin(self._run_name, self.current_agent or self._initial_agent,
                                               **self._run_attributes)
        return self._run

    def _run_summary(self, error: BaseException | None, pricing: dict[str, Any]) -> dict[str, Any]:
        from regression_shield.core.cost import summarize_cost
        from regression_shield.core.faithfulness import is_error_observation

        with self._lock:
            steps = list(self.steps)
            calls = list(self.llm_calls)
        tools = [s for s in steps if isinstance(s.get("action"), dict) and s["action"].get("type") == "tool_call"]
        blocked = sum(1 for s in tools if s.get("blocked"))
        errors = sum(1 for s in tools if not s.get("blocked")
                     and is_error_observation(s.get("observation"), str(s["action"].get("name", ""))))
        if error is not None and not isinstance(error, ActionBlocked):
            status = "error"
        elif blocked or isinstance(error, ActionBlocked):
            status = "blocked"
        else:
            status = "ok"
        summary: dict[str, Any] = {"status": status, "tool_calls": len(tools), "errors": errors, "blocked": blocked,
                                   "warnings": sum(1 for s in tools if s.get("guard_warning")),
                                   "llm_calls": len(calls)}
        cost = summarize_cost(steps, calls, pricing)
        if cost:
            summary.update(input_tokens=cost["input_tokens"], output_tokens=cost["output_tokens"],
                           total_tokens=cost["total_tokens"], cost_usd=cost["total_usd"], cost_complete=cost["complete"])
        content: dict[str, Any] = {"final_response": self.final_response, "trace": self.to_dict()}
        if error is not None:
            summary["error_type"] = type(error).__name__
            content["error"] = str(error)
        summary["content"] = content
        return summary

    def _export_step(self, step: dict[str, Any], timing: tuple[float, float] | None) -> None:
        run = self._current_run()
        if run is None:
            return
        try:
            now = time.time()
            start, end = timing or (now, now)
            run.emit(step_event(run.run_id, step, start, end))
        except Exception as err:
            logger.warning("Could not export a step: %s", err)

    # -- events ----------------------------------------------------------------

    def _add(self, action: dict[str, Any], thought: str | None = None, *,
             timing: tuple[float, float] | None = None, **fields: Any) -> dict[str, Any]:
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
            if action.get("type") == "tool_call" and not step.get("blocked"):
                name = action.get("name")
                if self._in_flight[name] > 0:
                    self._in_flight[name] -= 1  # the guard counted it until now
                warning = self._pending_warnings.pop(str(name), None)
                if warning:
                    step["guard_warning"] = warning
            self.steps.append(step)
        logger.debug("Recorded step %d: %s%s", step["step_index"], action["type"],
                     f" {action['name']}" if action.get("name") else "")
        self._export_step(step, timing)
        return step

    def tool_call(self, name: str, args: dict[str, Any] | None = None, observation: Any = "",
                  *, thought: str | None = None, agent: str | None = None,
                  cost_usd: float | None = None, timing: tuple[float, float] | None = None) -> dict[str, Any]:
        """Record a tool call and what it returned (use ``"ERROR: ..."`` for failures).

        ``agent`` names who made the call; it defaults to the current agent. Pass it
        when agents run concurrently, so calls aren't credited to the wrong one.
        ``cost_usd`` is what the call cost, for paid APIs (search, SMS, data providers).
        ``timing`` is the call's ``(start, end)`` in ``time.time()`` seconds, for exported spans.
        """
        action = {"type": "tool_call", "name": name, "args": dict(args or {})}
        fields: dict[str, Any] = {"observation": _jsonable(observation)}
        if agent:
            fields["agent"] = agent
        if cost_usd is not None:
            fields["cost_usd"] = float(cost_usd)
        return self._add(action, thought, timing=timing, **fields)

    def llm_call(self, model: str, input_tokens: int = 0, output_tokens: int = 0, *,
                 cached_input_tokens: int = 0, cache_write_tokens: int = 0,
                 cost_usd: float | None = None, agent: str | None = None,
                 timing: tuple[float, float] | None = None) -> dict[str, Any]:
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
        run = self._current_run()
        if run is not None:
            try:
                now = time.time()
                start, end = timing or (now, now)
                run.emit(llm_event(run.run_id, call, start, end, run.pipeline.pricing))
            except Exception as err:
                logger.warning("Could not export a model call: %s", err)
        return call

    def llm_response(self, response: Any, *, model: str | None = None, agent: str | None = None,
                     timing: tuple[float, float] | None = None) -> dict[str, Any] | None:
        """Record the token usage of a model response: an OpenAI, Anthropic or Gemini SDK
        response, a LangChain message, or a dict of one. Returns the record, or None if
        the response has no usage (nothing is recorded then)."""
        usage = usage_from_response(response)
        if usage is None:
            return None
        reported_model = usage.pop("model", None)
        return self.llm_call(model or reported_model or "unknown", agent=agent, timing=timing, **usage)

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

    # -- the guard ---------------------------------------------------------------

    def check(self, name: str, args: Any = None, *, agent: str | None = None) -> None:
        """Ask the guard whether tool ``name`` may run now with ``args``.

        If it may not, the attempt is recorded (``"blocked"`` on the step, and an
        ``ERROR: Blocked by policy: ...`` observation) and ``ActionBlocked`` is raised.
        Wrapped tools, the LangChain middleware and ``instrument()`` call this for you;
        call it yourself before running a tool any other way. Without a guard it does nothing.
        """
        if self.guard is None:
            return
        verdict = self.guard.check_tool(self, name, args, agent=agent)
        if verdict.warning:
            self._warn(name, verdict)
        if not verdict.allowed:
            self._block(name, args, verdict, agent)

    def check_llm(self) -> None:
        """Raise ``ActionBlocked`` if the run's budget (cost, tokens or model calls) is used up."""
        if self.guard is None:
            return
        verdict = self.guard.check_llm(self)
        if verdict.warning:
            logger.warning("Guard warning (%s): %s", verdict.rule, verdict.reason)
        if not verdict.allowed:
            logger.warning("Blocked a model call (%s): %s", verdict.rule, verdict.reason)
            raise ActionBlocked(verdict.reason, rule=verdict.rule)

    def _warn(self, name: str, verdict: Verdict) -> None:
        logger.warning("Guard warning for %s (%s): %s", name, verdict.rule, verdict.reason)
        with self._lock:
            self._pending_warnings[name] = {"rule": verdict.rule, "reason": verdict.reason}

    def _block(self, name: str, args: Any, verdict: Verdict, agent: str | None,
               thought: str | None = None) -> NoReturn:
        logger.warning("Blocked %s (%s): %s", name, verdict.rule, verdict.reason)
        call_args = dict(args) if isinstance(args, dict) else {} if args is None else {"input": _jsonable(args)}
        fields: dict[str, Any] = {"agent": agent} if agent else {}
        self._add({"type": "tool_call", "name": name, "args": call_args}, thought,
                  observation=blocked_observation(verdict.reason),
                  blocked={"rule": verdict.rule, "reason": verdict.reason}, **fields)
        raise ActionBlocked(verdict.reason, tool=name, rule=verdict.rule, arguments=call_args)

    def _release(self, name: str) -> None:
        """A call the guard allowed ended without a result to record (e.g. cancelled)."""
        with self._lock:
            if self._in_flight[name] > 0:
                self._in_flight[name] -= 1

    # -- tool calls a model requested (instrument()) -----------------------------

    def _model_requested(self, calls: list[tuple[str | None, str, Any]], text: str | None) -> None:
        """A model response asked for ``calls`` ``(call id, tool, args)``; the results come
        with the next request. Tools this recorder wraps are guarded and recorded where they
        run. Others are guarded here: a blocked one raises ``ActionBlocked`` before your
        code receives the response, so none of its calls run."""
        with self._lock:
            self._sdk_responses += 1
            response_number = self._sdk_responses
        group = f"m{response_number}" if len(calls) > 1 else None
        thought_used = False
        for position, (call_id, name, args) in enumerate(calls):
            call_args = args if isinstance(args, dict) else {"input": args}
            if name in self._wrapped_tools:
                if text and not thought_used:
                    self.thought(text)  # becomes the thought of the wrapped call's step
                    thought_used = True
                continue
            if self.guard is not None:
                verdict = self.guard.check_tool(self, name, call_args)
                if verdict.warning:
                    self._warn(name, verdict)
                if not verdict.allowed:
                    self._block(name, call_args, verdict, None, thought=text or "")
            key = call_id or f"{name}#{response_number}.{position}"
            with self._lock:
                self._sdk_calls[key] = {"name": name, "args": call_args, "thought": text or "", "group": group,
                                        "requested": time.time()}

    def _tool_results(self, results: list[tuple[str | None, str | None, Any, bool]]) -> None:
        """Results sent back to the model: ``(call id, tool name, output, is_error)``. Each one
        that answers a requested call is recorded as that call's step."""
        for call_id, name, output, is_error in results:
            with self._lock:
                key = call_id if call_id in self._sdk_calls else None
                if key is None and name:  # results without ids (Gemini) match the oldest call to that tool
                    key = next((k for k, call in self._sdk_calls.items() if call["name"] == name), None)
                call = self._sdk_calls.pop(key) if key is not None else None
            if call is None:
                continue  # earlier history, or a wrapped tool already recorded where it ran
            observation = _result_text(output)
            if is_error and not observation.startswith("ERROR"):
                observation = f"ERROR: {observation}"
            fields: dict[str, Any] = {"parallel_group": call["group"]} if call["group"] else {}
            self._add({"type": "tool_call", "name": call["name"], "args": call["args"]}, call["thought"],
                      timing=(call["requested"], time.time()), observation=observation, **fields)

    def _record_unanswered_calls(self) -> None:
        with self._lock:
            calls = list(self._sdk_calls.values())
            self._sdk_calls.clear()
        for call in calls:
            fields: dict[str, Any] = {"parallel_group": call["group"]} if call["group"] else {}
            self._add({"type": "tool_call", "name": call["name"], "args": call["args"]}, call["thought"],
                      timing=(call["requested"], time.time()), observation="", unconfirmed=True, **fields)

    # -- tools -----------------------------------------------------------------

    def wrap(self, fn: Callable | None = None, *, name: str | None = None, agent: str | None = None,
             cost_usd: float | None = None) -> Callable:
        """Wrap a tool so each call is recorded with its arguments and result or error.

        Use as ``@recorder.tool``, ``@recorder.tool(name="search")`` or
        ``recorder.wrap(fn)``. Exceptions are recorded and re-raised unchanged.
        ``agent`` credits every call to that agent (see ``tool_call``).
        ``cost_usd`` is the price of each call, for paid APIs. With a guard, each
        call is checked first and a blocked one raises ``ActionBlocked`` without running.
        """
        if fn is None:
            return lambda f: self.wrap(f, name=name, agent=agent, cost_usd=cost_usd)
        tool_name: str = name or getattr(fn, "__name__", None) or "tool"
        self._wrapped_tools.add(tool_name)
        try:
            signature: inspect.Signature | None = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

        def record_error(call_args: dict[str, Any], err: Exception, started: float) -> None:
            self.tool_call(tool_name, call_args, f"ERROR: {type(err).__name__}: {err}", agent=agent,
                           timing=(started, time.time()))

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                call_args = _bind_args(signature, args, kwargs)
                self.check(tool_name, call_args, agent=agent)
                started = time.time()
                try:
                    result = await fn(*args, **kwargs)
                except Exception as err:
                    record_error(call_args, err, started)
                    raise
                except BaseException:  # cancelled: nothing to record
                    self._release(tool_name)
                    raise
                self.tool_call(tool_name, call_args, result, agent=agent, cost_usd=cost_usd,
                               timing=(started, time.time()))
                return result
            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            call_args = _bind_args(signature, args, kwargs)
            self.check(tool_name, call_args, agent=agent)
            started = time.time()
            try:
                result = fn(*args, **kwargs)
            except Exception as err:
                record_error(call_args, err, started)
                raise
            except BaseException:
                self._release(tool_name)
                raise
            self.tool_call(tool_name, call_args, result, agent=agent, cost_usd=cost_usd, timing=(started, time.time()))
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
