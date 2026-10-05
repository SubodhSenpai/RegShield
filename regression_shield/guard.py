"""Block risky actions while an agent runs: the rules you test with, enforced live.

A ``Guard`` takes a scenario's rules and checks each action before it runs.
Attach it to a recorder (``TraceRecorder(guard=guard)``, the LangChain handler,
or the recorder you give ``instrument_smolagents``). A call that breaks a rule
doesn't run: the attempt is recorded (``"blocked": true`` on the step) and
``ActionBlocked`` is raised. Frameworks turn that into an error message the
agent reads, and the LangChain middleware returns one directly.

Rules enforced before each tool call:

    forbidden_tools        never run these tools
    agent_tools            each agent may run only its own tools
    forbidden_arguments    argument values a tool must never get (regular expressions)
    prerequisites          a tool runs only after these tools succeeded in the run
    requires_approval      a tool runs only after an approval (recorder.approval, or approver=)
    max_tool_calls         how often a tool may run in one run
    max_cost_usd           stop spending once the run's budget is used up
    rate_limits            calls per time window across all runs: {"send_email": "10/minute"}

``max_cost_usd``, ``max_tokens`` and ``max_llm_calls`` also stop further model
calls (with ``instrument()``, the LangChain middleware, or ``instrument_smolagents``).
Rules in ``warn_only`` (or every rule, with ``warn_only=True``) log a warning and
let the call run. Other scenario fields (expected tools, order...) can only be
judged after a run, so the guard ignores them.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import weakref
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from regression_shield.config import apply_log_level, load_config
from regression_shield.core.cost import RunSpend, format_usd, merge_pricing
from regression_shield.core.faithfulness import is_error_observation
from regression_shield.core.patterns import action_of, event_type, forbidden_argument_hit, is_tool_call
from regression_shield.models import CHECK_KEYS, ScenarioSpec

if TYPE_CHECKING:
    from regression_shield.recorder import TraceRecorder

logger = logging.getLogger(__name__)

# The warn_only name that covers each rule: the same names as the checks in a report
RULE_CHECKS = {
    "forbidden_tools": "policy", "forbidden_arguments": "policy", "prerequisites": "policy",
    "max_tool_calls": "policy", "rate_limits": "policy", "requires_approval": "human_approval",
    "agent_tools": "multi_agent", "max_cost_usd": "budget", "max_tokens": "budget", "max_llm_calls": "budget",
}
_UNIT_SECONDS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60,
                 "h": 3600, "hr": 3600, "hour": 3600, "d": 86400, "day": 86400}
_RATE = re.compile(r"^\s*(\d+)\s*(?:/|per\s)\s*(\d*)\s*([a-z]+)\s*$", re.IGNORECASE)


class ActionBlocked(Exception):
    """A guard stopped an action before it ran: ``tool`` (None for a model call), the
    ``rule`` it broke, the ``reason`` and the call's ``arguments``. Its message is what
    frameworks show the agent."""

    def __init__(self, reason: str, *, tool: str | None = None, rule: str = "",
                 arguments: dict[str, Any] | None = None):
        super().__init__(f"Blocked by policy: {reason}. "
                         + ("This action did not run." if tool else "The model was not called."))
        self.reason = reason
        self.tool = tool
        self.rule = rule
        self.arguments = arguments or {}


def blocked_observation(reason: str) -> str:
    """What the agent is told, and what the trace records, when a tool call is blocked."""
    return f"ERROR: Blocked by policy: {reason}. This action did not run."


@dataclass(frozen=True)
class Verdict:
    """A guard's decision. ``rule`` names the broken rule; an allowed call with a rule
    set broke a ``warn_only`` rule (a warning)."""

    allowed: bool
    rule: str = ""
    reason: str = ""

    @property
    def warning(self) -> bool:
        return self.allowed and bool(self.rule)


def parse_rate(spec: Any) -> tuple[int, float]:
    """``"10/minute"``, ``"5 per hour"``, ``"3/5min"`` or ``(10, 60)`` -> (calls, window in seconds)."""
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        calls, seconds = spec
        if isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0 and \
                isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
            return calls, float(seconds)
    elif isinstance(spec, str) and (match := _RATE.match(spec)):
        unit = match.group(3).lower()
        if unit not in _UNIT_SECONDS and len(unit) > 2 and unit.endswith("s"):
            unit = unit[:-1]  # minutes -> minute (but "ms" isn't minutes)
        if unit in _UNIT_SECONDS:
            return int(match.group(1)), int(match.group(2) or 1) * float(_UNIT_SECONDS[unit])
    raise ValueError(f"rate limit {spec!r}: use 'N/second', 'N/minute', 'N/hour', 'N/day' "
                     "(e.g. '10/minute', '3/5min') or (calls, seconds)")


def _window_text(seconds: float) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        if seconds % size == 0:
            count = int(seconds // size)
            return unit if count == 1 else f"{count} {unit}s"
    return f"{seconds:g} seconds"


class Guard:
    """Checks actions against a scenario's rules before they run.

    Example:
        guard = Guard({"forbidden_arguments": {"run_sql": {"query": r"\\b(drop|truncate)\\b"}},
                       "max_cost_usd": 0.50},
                      rate_limits={"send_email": "10/minute"})
        recorder = TraceRecorder(guard=guard)

    ``rules`` is a scenario (dict or ``ScenarioSpec``), so the rules your tests check can
    be enforced in production unchanged. ``approver(tool, args) -> bool`` is asked when a
    ``requires_approval`` tool has no approval yet; without it such calls are blocked.
    ``pricing`` adds to the config file's prices for the budget. One guard can serve many
    runs and threads: rate limits count calls across all of them.
    """

    def __init__(self, rules: ScenarioSpec | dict[str, Any] | None = None, *,
                 rate_limits: dict[str, Any] | None = None,
                 warn_only: bool | Iterable[str] | None = None,
                 approver: Callable[[str, dict[str, Any]], bool] | None = None,
                 pricing: dict[str, Any] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if isinstance(rules, ScenarioSpec):
            spec = rules
        else:
            data = dict(rules or {})
            rate_limits = {**(data.pop("rate_limits", None) or {}), **(rate_limits or {})}
            spec = ScenarioSpec.from_dict(data)
        self.spec = spec
        self.rate_limits = {str(tool): parse_rate(rule) for tool, rule in (rate_limits or {}).items()}
        if warn_only is True:
            warn = set(CHECK_KEYS)
        elif warn_only is None or warn_only is False:
            warn = set(spec.warn_only)
        else:
            warn = {str(key) for key in warn_only}
            unknown = sorted(warn - CHECK_KEYS)
            if unknown:
                raise ValueError(f"warn_only has unknown check(s) {unknown}. Valid: {', '.join(sorted(CHECK_KEYS))}")
        self.warn_only = frozenset(warn)
        self.approver = approver
        config = load_config()
        apply_log_level(config)
        self.pricing = merge_pricing(config.get("pricing"), pricing)
        self._clock = clock
        self._windows: dict[str, deque[float]] = {}
        self._spend: weakref.WeakKeyDictionary[Any, RunSpend] = weakref.WeakKeyDictionary()  # per recorder
        self._lock = threading.Lock()

    # -- tool calls ----------------------------------------------------------------

    def check_tool(self, recorder: TraceRecorder, name: str, args: Any = None, *,
                   agent: str | None = None) -> Verdict:
        """Decide whether ``name(**args)`` may run now. An allowed call is counted against
        rate limits and ``max_tool_calls`` until the recorder records its result."""
        args = args if isinstance(args, dict) else {} if args is None else {"input": args}
        agent = agent or recorder.current_agent
        for _attempt in range(2):  # a second pass after asking the approver
            with recorder._lock:
                verdict, needs_approval = self._decide(recorder, name, args, agent)
                if verdict.allowed and not needs_approval:
                    return verdict
            if not needs_approval or self.approver is None:
                return verdict
            try:
                approved = bool(self.approver(name, dict(args)))
            except Exception as err:  # an approver that fails mustn't let the call through
                logger.warning("Approver failed for %s: %s", name, err)
                return Verdict(False, "requires_approval", f"asking for approval of '{name}' failed: {err}")
            recorder.approval(name, approved=approved, by="approver")
            if not approved:
                return Verdict(False, "requires_approval", f"approval for '{name}' was denied")
        return Verdict(False, "requires_approval", f"'{name}' needs approval")

    def _decide(self, recorder: TraceRecorder, name: str, args: dict[str, Any],
                agent: str | None) -> tuple[Verdict, bool]:
        """(verdict, approval still needed). Runs under the recorder's lock."""
        in_flight = recorder._in_flight
        warning: Verdict | None = None
        needs_approval = False
        for rule, reason in self._tool_violations(recorder, name, args, agent):
            if rule == "requires_approval" and reason is None:
                needs_approval = True
                continue
            if RULE_CHECKS[rule] in self.warn_only:
                warning = warning or Verdict(True, rule, reason or "")
                continue
            return Verdict(False, rule, reason or ""), False
        if needs_approval:
            if "human_approval" in self.warn_only:
                warning = warning or Verdict(True, "requires_approval", f"'{name}' ran without approval")
            elif self.approver is None:
                return Verdict(False, "requires_approval", f"'{name}' needs approval"), False
            elif not self._rate_limited(name, count=False) or "policy" in self.warn_only:
                return Verdict(True), True  # ask the approver, then decide again
        limited = self._rate_limited(name, count=True)
        if limited:
            if "policy" not in self.warn_only:
                return Verdict(False, "rate_limits", limited), False
            warning = warning or Verdict(True, "rate_limits", limited)
        in_flight[name] += 1
        return warning or Verdict(True), False

    def _run_spend(self, recorder: TraceRecorder) -> RunSpend:
        """The recorder's spend so far (under its lock), priced only for what's new."""
        with self._lock:
            spend = self._spend.get(recorder)
            if spend is None:
                spend = self._spend[recorder] = RunSpend(self.pricing)
        return spend.update(recorder.steps, recorder.llm_calls)

    def _tool_violations(self, recorder: TraceRecorder, name: str, args: dict[str, Any],
                         agent: str | None) -> Iterable[tuple[str, str | None]]:
        """(rule, reason) for each rule the call breaks, cheapest checks first.
        ``("requires_approval", None)`` means it may run once approved."""
        spec = self.spec
        steps, in_flight = recorder.steps, recorder._in_flight
        if name in spec.forbidden_tools:
            yield "forbidden_tools", f"'{name}' is a forbidden tool"
        if agent and agent in spec.agent_tools and name not in spec.agent_tools[agent]:
            allowed = ", ".join(spec.agent_tools[agent]) or "none"
            yield "agent_tools", f"agent '{agent}' may not call '{name}' (its tools: {allowed})"
        if spec.forbidden_arguments:
            hit = forbidden_argument_hit(spec.forbidden_arguments, name, args)
            if hit:
                yield "forbidden_arguments", f"{name}.{hit[0]} matches forbidden pattern /{hit[1]}/: {hit[2]!r}"
        needs = spec.prerequisites.get(name, [])
        cap = spec.max_tool_calls.get(name)
        ran = [step for step in steps if is_tool_call(step) and not step.get("blocked")] if needs or cap is not None else []
        for needed in needs:
            earlier = [step for step in ran if action_of(step)["name"] == needed]
            if not earlier:
                yield "prerequisites", f"'{name}' needs '{needed}' to succeed first"
            elif is_error_observation(earlier[-1].get("observation"), needed):
                yield "prerequisites", (f"'{name}' needs '{needed}' to succeed first; it failed at step "
                                        f"{earlier[-1].get('step_index', '?')}")
        if cap is not None:
            count = sum(action_of(step)["name"] == name for step in ran) + in_flight[name]
            if count >= cap:
                yield "max_tool_calls", f"'{name}' already ran {count} time{'s' if count != 1 else ''} (max {cap})"
        if spec.max_cost_usd is not None:
            spent = self._run_spend(recorder).usd
            price = float(self.pricing["tools"].get(name, 0.0))
            if spent + price > spec.max_cost_usd + 1e-12:
                extra = f"; '{name}' costs {format_usd(price)}" if price else ""
                yield "max_cost_usd", f"the run has spent {format_usd(spent)} of its {format_usd(spec.max_cost_usd)} budget{extra}"
        if name in spec.requires_approval:
            decision = self._approval(steps, name, in_flight)
            if decision is False:
                yield "requires_approval", f"approval for '{name}' was denied"
            elif decision is None:
                yield "requires_approval", None

    def _approval(self, steps: list[dict[str, Any]], name: str, in_flight: Counter) -> bool | None:
        """The unused approval decision for the next call to ``name`` (each approval allows one call)."""
        guarded = set(self.spec.requires_approval)
        decisions: dict[str | None, bool] = {}
        for step in steps:
            action = action_of(step)
            if event_type(step) == "approval":
                tool = str(action["tool"]) if action.get("tool") else None
                decisions[tool] = bool(action.get("approved", True))
                if tool:
                    guarded.add(tool)
            elif is_tool_call(step) and not step.get("blocked") and action["name"] in guarded:
                if action["name"] in decisions:
                    del decisions[action["name"]]
                else:
                    decisions.pop(None, None)
        decision = decisions.get(name, decisions.get(None))
        if decision is True and in_flight[name]:
            return None  # a call already running took this approval
        return decision

    def _rate_limited(self, name: str, *, count: bool) -> str:
        """The reason if a call to ``name`` now would go over a rate limit, else "". With
        ``count``, an allowed call is counted against its limits."""
        keys = [key for key in (name, "*") if key in self.rate_limits]
        if not keys:
            return ""
        now = self._clock()
        with self._lock:
            for key in keys:
                limit, seconds = self.rate_limits[key]
                window = self._windows.setdefault(key, deque())
                while window and window[0] <= now - seconds:
                    window.popleft()
                if len(window) >= limit:
                    what = f"'{name}'" if key == name else "tool calls"
                    return f"{what} hit the rate limit of {limit} per {_window_text(seconds)}"
            if count:
                for key in keys:
                    self._windows[key].append(now)
        return ""

    # -- model calls ---------------------------------------------------------------

    def check_llm(self, recorder: TraceRecorder) -> Verdict:
        """Decide whether the run may make another model call (its budget)."""
        spec = self.spec
        if spec.max_cost_usd is None and spec.max_tokens is None and spec.max_llm_calls is None:
            return Verdict(True)
        with recorder._lock:
            spend = self._run_spend(recorder)
            calls, tokens, spent = spend.llm_calls, spend.tokens, spend.usd
        reason, rule = "", ""
        if spec.max_llm_calls is not None and calls >= spec.max_llm_calls:
            rule, reason = "max_llm_calls", f"the run has made {calls} of its {spec.max_llm_calls} model calls"
        elif spec.max_tokens is not None and tokens >= spec.max_tokens:
            rule, reason = "max_tokens", f"the run has used {tokens:,} of its {spec.max_tokens:,} tokens"
        elif spec.max_cost_usd is not None and spent >= spec.max_cost_usd - 1e-12:
            rule, reason = "max_cost_usd", f"the run has spent {format_usd(spent)} of its {format_usd(spec.max_cost_usd)} budget"
        if not rule:
            return Verdict(True)
        if "budget" in self.warn_only:
            return Verdict(True, rule, reason)
        return Verdict(False, rule, reason)
