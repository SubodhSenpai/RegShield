"""Record LangChain and LangGraph runs as RegShield traces.

Attach ``RegressionShieldCallbackHandler`` as a callback. It records every tool
call (arguments, result or error, and the model's reasoning before it) and,
for LangGraph, fills in agentic-pattern information automatically:

- graph nodes: each top-level node run becomes a node visit (graph checks);
  nodes that ran in the same graph step (fan-out) share a parallel group
- multi-agent: steps are tagged with the agent that ran them (``create_agent``
  names, supervisor/swarm sub-agents), and ``transfer_to_<agent>`` tool calls
  become handoffs
- parallel calls: calls in the same graph step but different tasks (a model
  requesting several tools at once, or fan-out branches) share a parallel group
- human approval: LangChain's ``HumanInTheLoopMiddleware`` interrupts and the
  decisions you resume with become approval events

The handler is also a ``TraceRecorder``, so you can add any other pattern event
(``plan``, ``route``, ``draft``, ``critique``, ``approval``...) to the same trace.

Give it a ``Guard`` to block risky calls while the agent runs: add
``handler.middleware()`` to ``create_agent(..., middleware=[...])``, or pass
``wrap_tool_call=handler.wrap_tool_call`` to a LangGraph ``ToolNode``.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from regression_shield.core.patterns import event_type, is_tool_call
from regression_shield.guard import ActionBlocked, Guard, blocked_observation
from regression_shield.recorder import TraceRecorder, usage_from_response

try:
    # LangChain's callback manager requires this base class (it reads
    # raise_error, ignore_agent, etc. from every handler).
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # LangChain is optional; the handler still works when called directly.
    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Stand-in base class when LangChain isn't installed."""


# Handoff tools used by langgraph-supervisor, langgraph-swarm and the OpenAI Agents SDK
_HANDOFF_TOOL = re.compile(r"^transfer_(?:back_)?to_(.+)$")
# Human-in-the-loop decisions (LangChain HumanInTheLoopMiddleware) that let the tool run
_APPROVING_DECISIONS = {"approve", "edit"}


def _checkpoint_ns(metadata: dict[str, Any]) -> str:
    return metadata.get("langgraph_checkpoint_ns") or metadata.get("checkpoint_ns") or ""


def _graph_path(metadata: dict[str, Any]) -> list[str]:
    """Graph path of a run, e.g. ['triage_agent', 'tools'], from LangGraph's checkpoint namespace."""
    return [segment.split(":", 1)[0] for segment in _checkpoint_ns(metadata).split("|") if segment]


def _scope(metadata: dict[str, Any]) -> str:
    """The sub-agent a run belongs to ('' in a single-level graph)."""
    path = _graph_path(metadata)
    return path[0] if len(path) > 1 else ""


def _parse_args(input_str: Any, inputs: Any) -> dict[str, Any]:
    if isinstance(inputs, dict):
        return inputs
    try:
        parsed = json.loads(input_str)
    except (TypeError, ValueError):
        return {"input": input_str}
    return parsed if isinstance(parsed, dict) else {"input": parsed}


class RegressionShieldCallbackHandler(BaseCallbackHandler, TraceRecorder):
    """LangChain / LangGraph callback handler that records a RegShield trace.

    Example:
        handler = RegressionShieldCallbackHandler()
        app.invoke(inputs, config={"callbacks": [handler]})
        report = evaluate_trace(scenario, handler)

    Each new top-level run starts a fresh trace, except resuming an interrupted
    graph (``Command(resume=...)``), which continues the same trace.
    """

    # The callbacks record model calls, so instrument() leaves this recorder alone
    sdk_capture = False

    def __init__(self, agent: str | None = None, *, guard: Guard | None = None):
        TraceRecorder.__init__(self, agent=agent, guard=guard)

    def reset(self) -> None:
        TraceRecorder.reset(self)
        self._thoughts: dict[str, str] = {}               # scope -> latest model text
        self._llm_scopes: dict[UUID, str] = {}             # model run -> scope
        self._llm_models: dict[UUID, str] = {}             # model run -> model name it was called with
        self._llm_started: dict[UUID, float] = {}          # model run -> when it started
        self._tool_runs: dict[UUID, dict[str, Any]] = {}   # tool calls in progress
        self._node_visits: set[Any] = set()
        self._interrupts: set[Any] = set()
        self._pending_approvals: list[str] = []            # tools awaiting a human decision

    def _context(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Step fields derived from LangGraph metadata: node, agent, and parallel-grouping keys."""
        path = _graph_path(metadata)
        context: dict[str, Any] = {}
        node = path[0] if path else metadata.get("langgraph_node")
        if node:
            context["node"] = node
        agent = metadata.get("lc_agent_name") or _scope(metadata)
        if agent and agent != "LangGraph":
            context["agent"], context["_auto_agent"] = agent, True
        if "langgraph_step" in metadata:
            # Runs in the same graph step but different tasks ran concurrently
            ns = _checkpoint_ns(metadata)
            context["_step_key"] = f"{ns.rsplit('|', 1)[0] if '|' in ns else ''}@{metadata['langgraph_step']}"
            context["_task"] = ns
        return context

    # -- LangChain callbacks ---------------------------------------------------------

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                       parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None,
                       **kwargs: Any) -> None:
        if parent_run_id is None:
            resume = getattr(inputs, "resume", None) if type(inputs).__name__ == "Command" else None
            if resume is None:
                self.reset()
            else:
                self._record_decisions(resume)
            return
        metadata = metadata or {}
        node = metadata.get("langgraph_node")
        # Only nodes of the top-level graph count as visits; sub-agent internals don't
        if not node or str(node).startswith("__") or len(_graph_path(metadata)) > 1:
            return
        # One visit per node and graph step: runnables inside a node, and the parallel
        # tasks of one node (ToolNode runs each tool call as its own task), all count once
        step = metadata.get("langgraph_step")
        visit = (node, step) if step is not None else _checkpoint_ns(metadata)
        if visit in self._node_visits:
            return
        self._node_visits.add(visit)
        context = self._context(metadata)
        context.pop("agent", None)
        context.pop("_auto_agent", None)
        self._add({"type": "node", "name": node}, **context)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any) -> None:
        """At the end of a top-level run, keep the agent's final answer (checked for hallucinated
        success), and finish the exported run."""
        if parent_run_id is not None:
            return
        if isinstance(outputs, dict):
            self._keep_final_answer(outputs)
        self.end_run()

    def _keep_final_answer(self, outputs: dict[str, Any]) -> None:
        if isinstance(outputs.get("output"), str):  # AgentExecutor
            self.final_answer(outputs["output"])
            return
        for message in reversed(outputs.get("messages") or []):  # LangGraph / create_agent message state
            if getattr(message, "type", None) != "ai":
                continue
            # A message that still requests tools (e.g. paused for approval) is not an answer
            if isinstance(message.content, str) and message.content and not getattr(message, "tool_calls", None):
                self.final_answer(message.content)
            return

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        interrupted = type(error).__name__ == "GraphInterrupt"
        if kwargs.get("parent_run_id") is None and "run_id" in kwargs:
            self.end_run(error=None if interrupted else error)  # a top-level run ended
        # HumanInTheLoopMiddleware pauses the graph with an interrupt listing the calls to review
        if not interrupted or not error.args:
            return
        for interrupt in error.args[0]:
            value = getattr(interrupt, "value", None)
            interrupt_id = getattr(interrupt, "id", id(interrupt))
            if isinstance(value, dict) and interrupt_id not in self._interrupts:
                self._interrupts.add(interrupt_id)
                self._pending_approvals += [r["name"] for r in value.get("action_requests", []) if r.get("name")]

    def _record_decisions(self, resume: Any) -> None:
        decisions = resume.get("decisions") if isinstance(resume, dict) else None
        if not decisions or not self._pending_approvals:
            return
        for tool, decision in zip(self._pending_approvals, decisions, strict=False):
            kind = decision.get("type") if isinstance(decision, dict) else str(decision)
            self.approval(tool, approved=kind in _APPROVING_DECISIONS, by="human")
        self._pending_approvals = []

    def _start_model(self, run_id: UUID, metadata: dict[str, Any] | None, kwargs: dict[str, Any]) -> None:
        self._llm_scopes[run_id] = _scope(metadata or {})
        self._llm_started[run_id] = time.time()
        params = kwargs.get("invocation_params") or {}
        model = (params.get("model") or params.get("model_name") or params.get("model_id")
                 or (metadata or {}).get("ls_model_name"))
        if model:
            self._llm_models[run_id] = str(model)

    def on_chat_model_start(self, serialized: dict[str, Any] | None, messages: Any, *, run_id: UUID,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._start_model(run_id, metadata, kwargs)

    def on_llm_start(self, serialized: dict[str, Any] | None, prompts: Any, *, run_id: UUID,
                     metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._start_model(run_id, metadata, kwargs)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        """Keep the model's text (it becomes the thought of the tool calls that follow)
        and the call's token usage (for cost tracking)."""
        scope = self._llm_scopes.pop(run_id, "")
        model_hint = self._llm_models.pop(run_id, None)
        started = self._llm_started.pop(run_id, None)
        try:
            generation = response.generations[0][0]
        except (AttributeError, IndexError, TypeError):
            return
        text = (getattr(generation, "text", "") or "").strip()
        if text:
            self._thoughts[scope] = text
        self._record_usage(response, generation, scope, model_hint, started)

    def _record_usage(self, response: Any, generation: Any, scope: str, model_hint: str | None,
                      started: float | None = None) -> None:
        message = getattr(generation, "message", None)
        usage = usage_from_response(message) if message is not None else None
        llm_output = getattr(response, "llm_output", None) or {}
        if usage is None and isinstance(llm_output.get("token_usage"), dict):  # completion-style LLMs
            usage = usage_from_response({"usage": llm_output["token_usage"]})
        if usage is None:
            return
        metadata = getattr(message, "response_metadata", None) or {}
        reported = (metadata.get("token_usage") or {}).get("cost") if isinstance(metadata, dict) else None
        if isinstance(reported, (int, float)) and not isinstance(reported, bool) and "cost_usd" not in usage:
            usage["cost_usd"] = float(reported)  # OpenRouter reports what the call cost
        model = (usage.pop("model", None) or (metadata.get("model_name") if isinstance(metadata, dict) else None)
                 or llm_output.get("model_name") or model_hint or "unknown")
        timing = (started, time.time()) if started is not None else None
        self.llm_call(model, agent=scope or None, timing=timing, **usage)

    def on_tool_start(self, serialized: dict[str, Any] | None, input_str: str, *, run_id: UUID,
                      metadata: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None,
                      **kwargs: Any) -> None:
        metadata = metadata or {}
        self._tool_runs[run_id] = {
            "name": (serialized or {}).get("name") or kwargs.get("name") or "tool",
            "args": _parse_args(input_str, inputs),
            "scope": _scope(metadata),
            "context": self._context(metadata),
            "started": time.time(),
        }

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        # Tools invoked by an agent return a ToolMessage; record just its content
        self._record_tool(run_id, str(getattr(output, "content", output)))

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._record_tool(run_id, f"ERROR: {type(error).__name__}: {error}")

    def _record_tool(self, run_id: UUID, observation: str) -> None:
        run = self._tool_runs.pop(run_id, None)
        if run is None:
            return
        thought = self._thoughts.pop(run["scope"], None)
        handoff = _HANDOFF_TOOL.match(run["name"])
        timing = (run["started"], time.time())
        if handoff:
            self._add({"type": "handoff", "to": handoff.group(1)}, thought, timing=timing, **run["context"])
        else:
            self._add({"type": "tool_call", "name": run["name"], "args": run["args"]}, thought,
                      timing=timing, observation=observation, **run["context"])

    # -- the guard: LangChain agent middleware and LangGraph ToolNode -----------------

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Check a tool call with the guard before it runs. A blocked call doesn't run: the
        agent gets an error ``ToolMessage`` saying why. For a LangGraph
        ``ToolNode(tools, wrap_tool_call=handler.wrap_tool_call)``; ``middleware()`` uses it too."""
        blocked = self._blocked_tool_message(request)
        return blocked if blocked is not None else handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        """Async version of ``wrap_tool_call``."""
        blocked = self._blocked_tool_message(request)
        return blocked if blocked is not None else await handler(request)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Stop the agent with ``ActionBlocked`` once the run's budget is used up."""
        self.check_llm()
        return handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        """Async version of ``wrap_model_call``."""
        self.check_llm()
        return await handler(request)

    def _blocked_tool_message(self, request: Any) -> Any:
        call = getattr(request, "tool_call", None) or {}
        name = str(call.get("name") or getattr(getattr(request, "tool", None), "name", None) or "tool")
        try:
            self.check(name, call.get("args") or {})
        except ActionBlocked as blocked:
            from langchain_core.messages import ToolMessage

            return ToolMessage(content=blocked_observation(blocked.reason), tool_call_id=str(call.get("id") or ""),
                               name=name, status="error")
        return None

    def middleware(self) -> Any:
        """LangChain agent middleware that applies this handler's guard:
        ``create_agent(model, tools, middleware=[handler.middleware()])``. A blocked tool call
        returns an error message to the agent instead of running; a used-up budget stops the
        run with ``ActionBlocked``. Also pass the handler as a callback, to record the run."""
        from langchain.agents.middleware import AgentMiddleware

        recorder = self

        class RegShieldGuard(AgentMiddleware):  # type: ignore[misc]
            def wrap_tool_call(self, request: Any, handler: Any) -> Any:
                return recorder.wrap_tool_call(request, handler)

            async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
                return await recorder.awrap_tool_call(request, handler)

            def wrap_model_call(self, request: Any, handler: Any) -> Any:
                return recorder.wrap_model_call(request, handler)

            async def awrap_model_call(self, request: Any, handler: Any) -> Any:
                return await recorder.awrap_model_call(request, handler)

        return RegShieldGuard()

    # -- output ----------------------------------------------------------------------

    def get_trace(self) -> list[dict[str, Any]]:
        """The recorded steps. Automatic agent tags are kept only when several agents ran,
        and parallel groups only where calls or nodes really ran concurrently."""
        steps = TraceRecorder.get_trace(self)
        tasks: dict[str, set[str]] = {}
        calls: Counter = Counter()
        nodes: dict[str, set[str]] = {}
        for step in steps:
            key = step.get("_step_key")
            if key is None:
                continue
            if event_type(step) == "node":
                nodes.setdefault(key, set()).add(step["node"])
            else:
                tasks.setdefault(key, set()).add(step.get("_task", ""))
                calls[key] += is_tool_call(step)
        concurrent_calls = {key for key, task_set in tasks.items() if len(task_set) > 1 and calls[key] > 1}
        concurrent_nodes = {key for key, node_set in nodes.items() if len(node_set) > 1}
        # In supervisor/swarm graphs each agent is a node: entering it is that agent's turn,
        # even when the turn makes no tool call
        agents = {s["agent"] for s in steps if s.get("_auto_agent")}
        agents |= {s["action"]["to"] for s in steps if event_type(s) == "handoff"}
        for step in steps:
            if event_type(step) == "node" and step["node"] in agents:
                step["agent"], step["_auto_agent"] = step["node"], True
        several_agents = len({s["agent"] for s in steps if s.get("_auto_agent")}) > 1

        for step in steps:
            key = step.pop("_step_key", None)
            step.pop("_task", None)
            if step.pop("_auto_agent", False) and not several_agents:
                step.pop("agent", None)
            concurrent = concurrent_nodes if event_type(step) == "node" else concurrent_calls
            if key in concurrent and "parallel_group" not in step:
                step["parallel_group"] = key
        return steps
