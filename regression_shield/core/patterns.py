"""Checks for agentic patterns beyond a single ReAct loop.

Besides tool calls, a trace step can be one of these events (``action.type``):

    plan      {"type": "plan", "steps": ["search", "book"]}
    handoff   {"type": "handoff", "to": "billing_agent"}
    approval  {"type": "approval", "tool": "issue_refund", "approved": true}
    route     {"type": "route", "to": "billing"}
    draft     {"type": "draft", "content": "..."}
    critique  {"type": "critique", "approved": false, "feedback": "..."}
    node      {"type": "node", "name": "review"}

Steps may also carry ``agent`` (who acted), ``node`` (graph node) and
``parallel_group`` (steps sharing a group ran concurrently).

Each check runs only when the scenario configures it or the trace contains its
events, and is reported only if it had something to check, so plain ReAct
traces are unaffected. A check returns
``{"label", "passed", "score", "violations", "details"}``; the score is the
fraction of individual checks that passed.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from typing import Any

from regression_shield.core.metrics import is_error_observation

logger = logging.getLogger(__name__)

PATTERN_EVENT_TYPES = frozenset({"plan", "handoff", "approval", "route", "draft", "critique", "node"})

# How many handoffs between the same two agents count as a ping-pong loop
PING_PONG_HANDOFFS = 4


def action_of(step: dict[str, Any]) -> dict[str, Any]:
    action = step.get("action")
    return action if isinstance(action, dict) else {}


def event_type(step: dict[str, Any]) -> str:
    return action_of(step).get("type", "tool_call")


def is_tool_call(step: dict[str, Any]) -> bool:
    return event_type(step) == "tool_call" and bool(action_of(step).get("name"))


def is_pattern_event(step: dict[str, Any]) -> bool:
    """Pattern events aren't agent actions, so they don't count as steps for efficiency."""
    return event_type(step) in PATTERN_EVENT_TYPES or ("action" not in step and "node" in step)


def step_number(step: dict[str, Any], position: int) -> int:
    return step.get("step_index") or position


def batch_indices(steps: list[dict[str, Any]]) -> list[int]:
    """Batch number per step. Steps sharing a parallel_group form one batch, even when
    other steps were recorded between them (e.g. a sub-agent running alongside)."""
    batches: list[int] = []
    group_batch: dict[Any, int] = {}
    count = 0
    for step in steps:
        group = step.get("parallel_group")
        if group is not None and group in group_batch:
            batches.append(group_batch[group])
            continue
        if group is not None:
            group_batch[group] = count
        batches.append(count)
        count += 1
    return batches


def _missing_in_order(expected: list[str], actual: list[str]) -> list[str]:
    """Items of ``expected`` that can't be matched, in order, within ``actual``."""
    missing, position = [], 0
    for item in expected:
        try:
            position = actual.index(item, position) + 1
        except ValueError:
            missing.append(item)
    return missing


class _Tally:
    """Counts individual checks and collects violation messages."""

    def __init__(self) -> None:
        self.checks = 0
        self.violations: list[str] = []

    def check(self, ok: bool, message: str = "") -> None:
        self.checks += 1
        if not ok:
            self.violations.append(message)

    def result(self, label: str, details: dict[str, Any]) -> dict[str, Any] | None:
        """The check result, or None when nothing was checked."""
        if not self.checks:
            return None
        failed = len(self.violations)
        return {
            "label": label,
            "passed": failed == 0,
            "score": round((self.checks - failed) / self.checks, 2),
            "violations": self.violations,
            "details": details,
        }


def check_policy(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """forbidden_tools: never call these. max_tool_calls: per-tool call caps."""
    forbidden = set(scenario.get("forbidden_tools") or [])
    caps = scenario.get("max_tool_calls") or {}
    if not forbidden and not caps:
        return None

    tally = _Tally()
    counts: Counter = Counter()
    for position, step in enumerate(steps, 1):
        if not is_tool_call(step):
            continue
        name = action_of(step)["name"]
        counts[name] += 1
        if name in forbidden:
            tally.check(False, f"Step {step_number(step, position)}: called forbidden tool '{name}'")
    for tool in forbidden:
        if not counts[tool]:
            tally.check(True)
    for tool, cap in caps.items():
        tally.check(counts[tool] <= cap, f"'{tool}' was called {counts[tool]} times (max {cap})")
    return tally.result("Policy", {"tool_call_counts": dict(counts)})


def check_human_approval(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """requires_approval: each call to these tools needs its own approved approval step.

    Tools named in approval events are also checked for running after a denial.
    """
    required = set(scenario.get("requires_approval") or [])
    approvals = [step for step in steps if event_type(step) == "approval"]
    if not required and not approvals:
        return None

    guarded = required | {action_of(s).get("tool") for s in approvals if action_of(s).get("tool")}
    decisions: dict[str | None, bool] = {}  # tool (None = any tool) -> approved?
    tally = _Tally()
    guarded_calls = 0
    for position, step in enumerate(steps, 1):
        action = action_of(step)
        if event_type(step) == "approval":
            decisions[action.get("tool")] = bool(action.get("approved", True))
            continue
        if not is_tool_call(step) or action["name"] not in guarded:
            continue
        name = action["name"]
        guarded_calls += 1
        label = f"Step {step_number(step, position)}"
        # Each approval authorizes one call
        decision = decisions.pop(name) if name in decisions else decisions.pop(None, None)
        if decision is False:
            tally.check(False, f"{label}: '{name}' ran after its approval was denied")
        elif decision is None and name in required:
            tally.check(False, f"{label}: '{name}' ran without approval")
        elif decision is True:
            tally.check(True)
    for approved in decisions.values():
        if approved is False:  # denied and never run, as it should be
            tally.check(True)
    called = {action_of(step)["name"] for step in steps if is_tool_call(step)}
    for _tool in required - called:  # never ran, so never ran unapproved
        tally.check(True)
    return tally.result("Human Approval", {
        "guarded_tools": sorted(guarded),
        "guarded_calls": guarded_calls,
        "approval_steps": len(approvals),
    })


def _plan_tools(action: dict[str, Any]) -> list[str]:
    tools = []
    for item in action.get("steps") or []:
        name = item.get("tool") or item.get("name") if isinstance(item, dict) else item
        if name:
            tools.append(str(name))
    return tools


def check_plan_execute(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """require_plan / expected_plan, plus adherence to the plan and replanning after failures."""
    expected_plan = scenario.get("expected_plan") or []
    require = bool(scenario.get("require_plan")) or bool(expected_plan)
    plan_positions = [i for i, step in enumerate(steps) if event_type(step) == "plan"]
    if not require and not plan_positions:
        return None

    tally = _Tally()
    tool_positions = [i for i, step in enumerate(steps) if is_tool_call(step)]
    plans = [_plan_tools(action_of(steps[i])) for i in plan_positions]

    if require:
        if not plan_positions:
            tally.check(False, "No plan was made")
        elif tool_positions and tool_positions[0] < plan_positions[0]:
            first = tool_positions[0]
            tally.check(False, f"Step {step_number(steps[first], first + 1)}: "
                               f"'{action_of(steps[first])['name']}' ran before any plan was made")
        else:
            tally.check(True)
    if expected_plan and plans:
        missing = _missing_in_order(expected_plan, plans[0])
        tally.check(not missing, f"Plan is missing or misorders expected steps: {missing}")

    # Adherence: calls under each plan should be in that plan; the final plan should be completed in order
    for index, start in enumerate(plan_positions):
        plan = plans[index]
        end = plan_positions[index + 1] if index + 1 < len(plan_positions) else len(steps)
        calls = [(i, action_of(steps[i])["name"]) for i in range(start + 1, end) if is_tool_call(steps[i])]
        if not plan:
            continue
        for i, name in calls:
            tally.check(name in plan, f"Step {step_number(steps[i], i + 1)}: '{name}' is not in the plan")
        if index == len(plan_positions) - 1:
            executed = [name for _, name in calls if name in plan]
            for tool in plan:
                tally.check(tool in executed, f"Planned step '{tool}' never ran")
            first_runs = list(dict.fromkeys(executed))
            in_plan_order = [tool for tool in plan if tool in first_runs]
            tally.check(first_runs == in_plan_order, f"Plan steps ran out of order: {first_runs} (plan: {plan})")

    # After a failed call, the executor should retry or replan, not push on with the next step
    if plan_positions:
        for i in tool_positions:
            if not is_error_observation(str(steps[i].get("observation", ""))):
                continue
            failed_tool = action_of(steps[i])["name"]
            for j in range(i + 1, len(steps)):
                if event_type(steps[j]) == "plan":
                    break
                if is_tool_call(steps[j]):
                    next_tool = action_of(steps[j])["name"]
                    tally.check(
                        next_tool == failed_tool,
                        f"Step {step_number(steps[j], j + 1)}: continued with '{next_tool}' after "
                        f"'{failed_tool}' failed (step {step_number(steps[i], i + 1)}) without replanning",
                    )
                    break

    return tally.result("Plan & Execute", {"plans": plans, "replans": max(0, len(plans) - 1)})


def check_multi_agent(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """agent_tools (per-agent allowlists), expected_agents (order), max_handoffs, ping-pong loops."""
    agent_tools = {agent: set(tools) for agent, tools in (scenario.get("agent_tools") or {}).items()}
    expected_agents = scenario.get("expected_agents") or []
    max_handoffs = scenario.get("max_handoffs")
    has_events = any(event_type(s) == "handoff" or s.get("agent") for s in steps)
    if not agent_tools and not expected_agents and max_handoffs is None and not has_events:
        return None

    tally = _Tally()
    chain: list[str] = []  # agents in the order they acted
    handoffs: list[dict[str, Any]] = []
    current: str | None = None
    pending: str | None = None  # handoff target that hasn't acted yet

    def take_control(agent: str | None) -> None:
        if agent and (not chain or chain[-1] != agent):
            chain.append(agent)

    for position, step in enumerate(steps, 1):
        # A handoff only asks for a transfer: the target joins the chain once it acts
        # (or when the trace ends), not if another agent acts first
        agent = step.get("agent")
        if not agent and pending and (is_tool_call(step) or event_type(step) == "handoff"):
            agent = pending  # an untagged action after a handoff belongs to its target
        if agent:
            current, pending = agent, None
            take_control(agent)
        if event_type(step) == "handoff":
            target = action_of(step).get("to")
            handoffs.append({"from": current, "to": target, "step": step_number(step, position)})
            current = pending = target
        elif is_tool_call(step) and current in agent_tools:
            name = action_of(step)["name"]
            tally.check(
                name in agent_tools[current],
                f"Step {step_number(step, position)}: agent '{current}' called '{name}', which isn't in its allowed tools",
            )
    take_control(pending)

    if expected_agents:
        missing = _missing_in_order(expected_agents, chain)
        tally.check(not missing, f"Expected agents {' -> '.join(expected_agents)}, got {' -> '.join(chain) or 'none'}")
    if max_handoffs is not None:
        tally.check(len(handoffs) <= max_handoffs, f"{len(handoffs)} handoffs (max {max_handoffs})")
    pairs = Counter(frozenset((h["from"], h["to"])) for h in handoffs if h["from"] and h["to"] and h["from"] != h["to"])
    loops = [sorted(pair) for pair, count in pairs.items() if count >= PING_PONG_HANDOFFS]
    tally.check(
        not loops,
        "; ".join(f"Agents '{a}' and '{b}' handed off to each other {pairs[frozenset((a, b))]} times" for a, b in loops),
    )
    return tally.result("Multi-Agent", {"agents": chain, "handoffs": handoffs})


def check_routing(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """expected_route: the first routing decision must match (a string or a list of acceptable routes)."""
    expected = scenario.get("expected_route")
    routes = [action_of(step).get("to") for step in steps if event_type(step) == "route"]
    if expected is None and not routes:
        return None

    tally = _Tally()
    actual = routes[0] if routes else None
    if expected is not None:
        acceptable = expected if isinstance(expected, list) else [expected]
        normalized = {str(route).strip().lower() for route in acceptable}
        if actual is None:
            tally.check(False, "No routing decision was recorded")
        else:
            tally.check(str(actual).strip().lower() in normalized, f"Routed to '{actual}', expected '{expected}'")
    return tally.result("Routing", {"route": actual, "expected_route": expected, "routes": routes})


def check_parallel(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """expected_parallel: groups of tools that should run concurrently (same parallel_group)."""
    expected = scenario.get("expected_parallel") or []
    if not expected and not any(step.get("parallel_group") is not None for step in steps):
        return None

    tally = _Tally()
    batches = batch_indices(steps)
    tool_batches: dict[str, set] = {}
    batch_tools: dict[int, list[str]] = {}
    for step, batch in zip(steps, batches, strict=True):
        if is_tool_call(step):
            name = action_of(step)["name"]
            tool_batches.setdefault(name, set()).add(batch)
            batch_tools.setdefault(batch, []).append(name)

    for group in expected:
        missing = [tool for tool in group if tool not in tool_batches]
        if missing:
            tally.check(False, f"Expected parallel tools never ran: {missing}")
            continue
        shared = set.intersection(*(tool_batches[tool] for tool in group))
        tally.check(bool(shared), f"{', '.join(group)} should run in parallel but ran one after another")
    concurrent = [tools for tools in batch_tools.values() if len(tools) > 1]
    return tally.result("Parallel Calls", {"parallel_batches": concurrent})


def _node_layers(steps: list[dict[str, Any]]) -> list[tuple[list[str], int]]:
    """The nodes the run went through, as (nodes, step number) layers.

    Nodes sharing a parallel group ran in the same graph step (fan-out) and form
    one layer. The path comes from node events when the trace has any, otherwise
    from the ``node`` field of steps. A node repeated back to back counts once.
    """
    use_events = any(event_type(step) == "node" for step in steps)
    layers: list[tuple[list[str], int]] = []
    open_group: Any = None
    for position, step in enumerate(steps, 1):
        if use_events:
            node = action_of(step).get("name") if event_type(step) == "node" else None
        else:
            node = step.get("node")
        if not node:
            continue
        group = step.get("parallel_group")
        if layers and group is not None and group == open_group:
            if node not in layers[-1][0]:
                layers[-1][0].append(node)
            continue
        open_group = group
        if not layers or layers[-1][0] != [node]:
            layers.append(([node], step_number(step, position)))
    return layers


def check_graph(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """allowed_transitions: node -> allowed next nodes. max_node_visits: int or per-node caps.

    The check runs only when one of them is set; otherwise graph nodes are just recorded.
    """
    allowed = scenario.get("allowed_transitions") or {}
    max_visits = scenario.get("max_node_visits")
    if not allowed and max_visits is None:
        return None

    tally = _Tally()
    layers = _node_layers(steps)
    if allowed:
        tally.check(bool(layers), "No graph nodes were recorded")
        allowed_next = {node: set(targets) for node, targets in allowed.items()}
        # A node in a layer may be reached from any node of the layer before it
        for (sources, _), (targets, number) in zip(layers, layers[1:], strict=False):
            for target in targets:
                tally.check(
                    any(target in allowed_next.get(source, set()) for source in sources),
                    f"Step {number}: {' / '.join(repr(s) for s in sources)} -> '{target}' is not an allowed transition",
                )
    if max_visits is not None:
        visits = Counter(node for nodes, _ in layers for node in nodes)
        caps = max_visits if isinstance(max_visits, dict) else {node: max_visits for node in visits}
        for node, cap in caps.items():
            tally.check(visits[node] <= cap, f"Node '{node}' was entered {visits[node]} times (max {cap})")
    # Each path entry is a node, or a list of nodes that ran in parallel
    path = [nodes[0] if len(nodes) == 1 else nodes for nodes, _ in layers]
    return tally.result("Graph Transitions", {"path": path})


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def check_reflection(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Evaluator-optimizer loops: critiques are acted on, the output ends approved, max_revision_rounds."""
    max_rounds = scenario.get("max_revision_rounds")
    events = [(position, step) for position, step in enumerate(steps, 1)
              if event_type(step) in ("draft", "critique")]
    if max_rounds is None and not events:
        return None

    tally = _Tally()
    last_draft: str | None = None
    rejected_at: int | None = None  # step number of a rejection awaiting a revision
    critiques = drafts = 0
    for position, step in events:
        action = action_of(step)
        number = step_number(step, position)
        if event_type(step) == "critique":
            critiques += 1
            rejected_at = None if action.get("approved", False) else number
            continue
        drafts += 1
        content = _normalize_text(action.get("content"))
        if rejected_at is not None and last_draft is not None:
            tally.check(content != last_draft, f"Step {number}: revision is unchanged after the critique at step {rejected_at}")
        last_draft, rejected_at = content, None

    if events and event_type(events[-1][1]) == "critique":
        final = events[-1]
        tally.check(
            bool(action_of(final[1]).get("approved", False)),
            f"Step {step_number(final[1], final[0])}: the final draft was rejected by the evaluator",
        )
    if max_rounds is not None:
        tally.check(critiques <= max_rounds, f"{critiques} review rounds (max {max_rounds})")
    return tally.result("Reflection Loop", {"drafts": drafts, "critiques": critiques})


PATTERN_CHECKS: tuple[tuple[str, Callable], ...] = (
    ("policy", check_policy),
    ("human_approval", check_human_approval),
    ("plan_execute", check_plan_execute),
    ("multi_agent", check_multi_agent),
    ("routing", check_routing),
    ("parallel", check_parallel),
    ("graph", check_graph),
    ("reflection", check_reflection),
)


def run_pattern_checks(scenario: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Run every pattern check that applies to this scenario and trace."""
    results: dict[str, dict[str, Any]] = {}
    for key, check in PATTERN_CHECKS:
        result = check(scenario, steps)
        if result is None:
            continue
        results[key] = result
        logger.debug(
            "  pattern %-15s %s (%.2f)%s", key, "PASSED" if result["passed"] else "FAILED", result["score"],
            f": {'; '.join(result['violations'])}" if result["violations"] else "",
        )
    return results
