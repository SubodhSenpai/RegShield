"""Record Hugging Face smolagents runs as RegShield traces.

``instrument_smolagents(agent)`` (recommended) records each tool call as it
runs. It works for ``CodeAgent`` (whose tools are called from generated
Python code) and ``ToolCallingAgent``, and records managed sub-agents as
handoffs. ``extract_smolagents_trace(agent)`` rebuilds a trace from a
finished ``ToolCallingAgent``'s memory when you couldn't instrument it first.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from regression_shield.recorder import TraceRecorder

logger = logging.getLogger(__name__)


def instrument_smolagents(agent: Any, recorder: TraceRecorder | None = None) -> TraceRecorder:
    """Record every tool call of ``agent`` (and its managed agents) as it runs.

    Call it once before ``agent.run`` and pass the returned recorder to
    ``evaluate_trace``. Each ``agent.run`` starts a new trace (unless you pass
    ``reset=False`` to continue the conversation), and its answer is kept for
    the faithfulness check. Each step's model output becomes the thought of the
    calls it made, and calls made together in one step (which smolagents runs
    in parallel) share a parallel group. With managed agents, calling one is
    recorded as a handoff and every step is tagged with the agent that made it.
    """
    recorder = recorder or TraceRecorder()
    managed = dict(getattr(agent, "managed_agents", None) or {})
    owner = (getattr(agent, "name", None) or "manager") if managed else None
    _wrap_tools(agent, recorder, owner, final=True)
    _attach_step_callback(agent, recorder, owner)
    for name, sub_agent in managed.items():
        _instrument_managed(sub_agent, name, recorder, parent=owner)

    original_run = agent.run

    def run(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("reset", True):
            recorder.reset()
        result = original_run(*args, **kwargs)
        # With stream=True the answer arrives through the final_answer tool instead
        if not inspect.isgenerator(result):
            output = getattr(result, "output", result)  # RunResult when return_full_result=True
            if output is not None:
                recorder.final_answer(str(output))
        return result

    agent.run = run
    return recorder


def _wrap_tools(agent: Any, recorder: TraceRecorder, owner: str | None, final: bool) -> None:
    wrapped = 0
    for name, tool in getattr(agent, "tools", {}).items():
        if getattr(tool, "_regshield_recorder", None) is recorder:
            continue
        if name == "final_answer":
            if final:  # only the top-level agent's answer is the run's final response
                original = tool.forward

                def capture_final(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                    result = _original(*args, **kwargs)
                    recorder.final_answer(result)
                    return result

                tool.forward = capture_final
        else:
            # Credit calls to the tool's owner: smolagents runs parallel calls in threads,
            # so "whoever is active" can't tell a manager's call from a sub-agent's
            tool.forward = recorder.wrap(tool.forward, name=name, agent=owner)
            wrapped += 1
        tool._regshield_recorder = recorder
    logger.debug("Instrumented %d tool(s) of %s", wrapped, owner or getattr(agent, "name", None) or "agent")


def _attach_step_callback(agent: Any, recorder: TraceRecorder, owner: str | None) -> None:
    """After each of the agent's steps, give the steps it recorded the model's output as
    their thought, and group them as parallel when the model requested several calls."""
    seen_list, seen_count = recorder.steps, len(recorder.steps)

    def on_step(memory_step: Any, **kwargs: Any) -> None:
        nonlocal seen_list, seen_count
        if seen_list is not recorder.steps:  # a new run reset the recorder (reset() starts a new list)
            seen_list, seen_count = recorder.steps, 0
        new_steps = [step for step in recorder.steps[seen_count:] if step.get("agent") == owner]
        seen_count = len(recorder.steps)
        thought = str(getattr(memory_step, "model_output", None) or "").strip()
        requested = [call for call in getattr(memory_step, "tool_calls", None) or []
                     if getattr(call, "name", "") != "final_answer"]
        group = f"{owner or 'agent'}:{getattr(memory_step, 'step_number', '')}" if len(requested) > 1 else None
        for step in new_steps:
            if thought:
                step.setdefault("thought", thought)
            if group and len(new_steps) > 1:
                step.setdefault("parallel_group", group)

    callbacks: Any = getattr(agent, "step_callbacks", None)
    if hasattr(callbacks, "register"):  # smolagents >= 1.20
        from smolagents.memory import ActionStep
        callbacks.register(ActionStep, on_step)
    elif isinstance(callbacks, list):
        callbacks.append(on_step)


def _instrument_managed(sub_agent: Any, name: str, recorder: TraceRecorder, parent: str | None) -> None:
    """Calling a managed agent is a handoff from its manager."""
    _wrap_tools(sub_agent, recorder, name, final=False)
    _attach_step_callback(sub_agent, recorder, name)
    original_run = sub_agent.run

    def run(*args: Any, **kwargs: Any) -> Any:
        recorder._add({"type": "handoff", "to": name}, agent=parent)
        return original_run(*args, **kwargs)

    sub_agent.run = run
    for inner_name, inner in (getattr(sub_agent, "managed_agents", None) or {}).items():
        _instrument_managed(inner, inner_name, recorder, parent=name)


def _step_tool_calls(step: Any) -> list[tuple[str, Any]]:
    """(name, arguments) for each tool call in a memory step, including failed ones.

    smolagents leaves ``step.tool_calls`` empty when a call raises; the
    attempted calls are then only on the model's message.
    """
    if getattr(step, "tool_calls", None):
        return [(getattr(tc, "name", ""), getattr(tc, "arguments", {})) for tc in step.tool_calls]
    if getattr(step, "error", None) is None:
        return []
    message = getattr(step, "model_output_message", None)
    return [(getattr(tc.function, "name", ""), getattr(tc.function, "arguments", {}))
            for tc in (getattr(message, "tool_calls", None) or [])]


def extract_smolagents_trace(agent: Any) -> list[dict[str, Any]]:
    """Rebuild a trace from a finished ``ToolCallingAgent``'s memory.

    Failed tool calls are kept, with ``ERROR: ...`` as their observation. For a
    ``CodeAgent`` use ``instrument_smolagents``: its memory only shows code.
    """
    steps_list = getattr(getattr(agent, "memory", None), "steps", []) or []
    trace: list[dict[str, Any]] = []
    for step in steps_list:
        for name, args in _step_tool_calls(step):
            if name == "final_answer":
                continue
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    pass
            observation = getattr(step, "observations", None)
            if observation is None:
                error = getattr(step, "error", None)
                observation = f"ERROR: {error}" if error is not None else ""
            trace.append({
                "step_index": len(trace) + 1,
                "thought": str(getattr(step, "model_output", "") or ""),
                "action": {"type": "tool_call", "name": name, "args": args},
                "observation": str(observation),
            })
    logger.debug("Extracted %d tool call(s) from %d memory step(s)", len(trace), len(steps_list))
    return trace
