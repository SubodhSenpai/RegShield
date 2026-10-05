"""The five core trace metrics. Each ``evaluate`` returns a dict with a 0-1 ``score``."""

from __future__ import annotations

import json
import re
from typing import Any

from regression_shield.core.faithfulness import (
    Claim,
    ToolIndex,
    acknowledges_failure,
    claims_success,
    failure_signal,
    find_claims,
    is_error_observation,
)

__all__ = [
    "WEIGHTS",
    "ArgumentCorrectnessMetric",
    "ReasoningFaithfulnessMetric",
    "StepEfficiencyMetric",
    "ToolCallOrderMetric",
    "ToolSelectionMetric",
    "claims_success",
    "composite_score",
    "is_error_observation",
]

WEIGHTS = {
    "tool_selection": 0.25,
    "argument_correctness": 0.25,
    "call_ordering": 0.20,
    "step_efficiency": 0.15,
    "reasoning_faithfulness": 0.15,
}


def composite_score(metrics: dict[str, float]) -> float:
    """Weighted average of the core metrics (see ``WEIGHTS``)."""
    return round(sum(metrics.get(name, 0.0) * weight for name, weight in WEIGHTS.items()), 2)


class ToolSelectionMetric:
    """F1 of the tools that ran against the expected tools."""

    @staticmethod
    def evaluate(expected_tools: list[str], invoked_tools: list[str]) -> dict[str, Any]:
        expected, invoked = set(expected_tools), set(invoked_tools)
        if not expected and not invoked:
            return {"score": 1.0, "precision": 1.0, "recall": 1.0, "missing": [], "unexpected": []}

        hits = len(expected & invoked)
        precision = hits / len(invoked) if invoked else 0.0
        recall = hits / len(expected) if expected else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "score": round(f1, 2),
            "precision": round(precision, 2),
            "recall": round(recall, 2),
            "missing": sorted(expected - invoked),
            "unexpected": sorted(invoked - expected),
        }


def _as_json(value: Any) -> Any:
    """A JSON string decoded (some models pass objects as JSON text); anything else as is."""
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _args_match(actual: Any, expected: Any) -> bool:
    """Numbers compare numerically; text ignores case, surrounding spaces, '_' and '-'.

    Objects and lists compare item by item with the same rules (key order doesn't
    matter, 2 equals 2.0), and booleans only match booleans or "true"/"false".
    """
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return _as_bool(actual) is not None and _as_bool(actual) == _as_bool(expected)
    if isinstance(expected, dict):
        actual = _as_json(actual)
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(_args_match(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, (list, tuple)):
        actual = _as_json(actual)
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expected)
                and all(_args_match(a, e) for a, e in zip(actual, expected, strict=True)))
    if isinstance(actual, (dict, list, tuple)):
        return False
    try:
        if abs(float(actual) - float(expected)) < 1e-4:
            return True
    except (TypeError, ValueError):
        pass

    def normalize(value: Any) -> str:
        return str(value).strip().lower().replace("_", " ").replace("-", " ")

    return normalize(actual) == normalize(expected)


class ArgumentCorrectnessMetric:
    """Share of expected argument values that the best-matching call to each tool used."""

    @staticmethod
    def evaluate(expected_args: dict[str, dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        if not expected_args:
            return {"score": 1.0, "total_checks": 0, "passed_checks": 0, "mismatches": []}

        calls: dict[str, list[dict[str, Any] | None]] = {}
        for step in trace:
            action = step.get("action")
            if isinstance(action, dict) and action.get("type", "tool_call") == "tool_call" and action.get("name"):
                args: Any = action.get("args")
                if args is None:
                    args = action.get("arguments", {})
                # Arguments that aren't an object (a list, a bare string) are matched as {"input": ...}
                calls.setdefault(action["name"], []).append(args if isinstance(args, dict) or args is None
                                                            else {"input": args})

        total = passed = 0
        mismatches: list[dict[str, Any]] = []
        for tool, expected in expected_args.items():
            total += len(expected)
            if tool not in calls:
                mismatches += [{"tool": tool, "param": k, "expected": v, "actual": "<never called>"}
                               for k, v in expected.items()]
                continue
            # Score against the call that got the most arguments right
            best_misses: list[dict[str, Any]] = []
            best_hits = -1
            for args in calls[tool]:
                misses = [{"tool": tool, "param": k, "expected": v, "actual": (args or {}).get(k)}
                          for k, v in expected.items() if not _args_match((args or {}).get(k), v)]
                hits = len(expected) - len(misses)
                if hits > best_hits:
                    best_hits, best_misses = hits, misses
            passed += best_hits
            mismatches += best_misses

        return {
            "score": round(passed / total, 2) if total else 1.0,
            "total_checks": total,
            "passed_checks": passed,
            "mismatches": mismatches,
        }


class ToolCallOrderMetric:
    """Share of ordering constraints the trace respected.

    ``expected_order`` is a list (each tool before the next) or a list of
    ``[before, after]`` pairs for a partial order. ``batches`` gives each call's
    parallel batch: a tool in the same batch as its prerequisite ran concurrently
    with it, which is a violation. ``step_numbers`` are used in messages.
    """

    @staticmethod
    def evaluate(
        expected_order: list[Any],
        invoked_tools: list[str],
        batches: list[int] | None = None,
        step_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        is_pairs = bool(expected_order) and isinstance(expected_order[0], (list, tuple))
        if not expected_order or (len(expected_order) <= 1 and not is_pairs):  # one pair is still a constraint
            return {"score": 1.0, "violations": [], "constraints": 0}

        if is_pairs:
            pairs = [(pair[0], pair[1]) for pair in expected_order if len(pair) >= 2]
        else:
            pairs = [(a, b) for i, a in enumerate(expected_order) for b in expected_order[i + 1:]]

        first_call: dict[str, int] = {}
        first_batch: dict[str, int] = {}
        for index, tool in enumerate(invoked_tools):
            if tool not in first_call:
                first_call[tool] = index
                first_batch[tool] = batches[index] if batches is not None else index

        def step(tool: str) -> int:
            index = first_call[tool]
            return step_numbers[index] if step_numbers is not None else index + 1

        violations: list[str] = []
        for before, after in pairs:
            never_ran = [tool for tool in (before, after) if tool not in first_call]
            if never_ran:
                violations.append(f"{' and '.join(map(repr, never_ran))} never ran ('{before}' must come before '{after}')")
            elif first_batch[before] > first_batch[after]:
                violations.append(f"'{after}' (step {step(after)}) ran before its prerequisite '{before}' (step {step(before)})")
            elif first_batch[before] == first_batch[after] and before != after:
                violations.append(f"'{after}' (step {step(after)}) ran in parallel with its prerequisite '{before}' (step {step(before)})")

        return {
            "score": round((len(pairs) - len(violations)) / len(pairs), 2) if pairs else 1.0,
            "violations": violations,
            "constraints": len(pairs),
        }


class StepEfficiencyMetric:
    """Penalizes steps beyond ``optimal_steps`` and repeated identical calls (loops)."""

    @staticmethod
    def evaluate(trace: list[dict[str, Any]], optimal_steps: int = 3) -> dict[str, Any]:
        total = len(trace)
        if total == 0:
            return {"score": 1.0, "total_steps": 0, "optimal_steps": optimal_steps, "redundant_calls": 0}

        seen: set[str] = set()
        redundant = 0
        for step in trace:
            action = step.get("action")
            if not isinstance(action, dict):
                action = {}
            if action.get("type", "tool_call") == "tool_call":
                signature = f"{action.get('name')}:{json.dumps(action.get('args', {}), sort_keys=True, default=str)}"
                redundant += signature in seen
                seen.add(signature)

        score = max(0.0, optimal_steps / max(optimal_steps, total) - min(0.6, redundant * 0.25))
        return {"score": round(score, 2), "total_steps": total, "optimal_steps": optimal_steps,
                "redundant_calls": redundant}


# Tools that send a message to someone; the claims in their text are checked too
_MESSAGE_TOOL_WORDS = {"email", "mail", "message", "messages", "msg", "reply", "respond", "notify", "notification",
                       "sms", "slack", "chat", "comment", "letter", "tweet", "whatsapp", "telegram", "teams",
                       "discord", "confirmation", "notice"}
_MESSAGE_ARGS = {"body", "message", "text", "content", "subject", "reply", "comment", "msg", "html", "note",
                 "summary", "response", "description"}
_DESCRIBE = {"error": "an error", "denied": "a denied approval"}


def is_message_tool(name: str) -> bool:
    """True for tools that send a message (email, reply, notify, sms, slack...)."""
    words = set(re.split(r"[^a-z]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()))
    return bool(words & _MESSAGE_TOOL_WORDS)


def _verdict(claim: Claim, index: ToolIndex,
             status: dict[str, tuple[str, int]]) -> tuple[str, str, set[str]] | None:
    """What the trace says about the tools a claim is about, and which tools those are.

    None: about a tool that succeeded, so the claim stands. ("failed", tool, ...): that
    tool's last call failed or was denied. ("never", tool, ...): it never ran.
    ("unlinked", "", ...): not about a particular tool, or about tools that both
    succeeded and failed (then the claim is judged like generic wording).
    """
    linked = index.link(claim)
    outcomes = {tool: status.get(tool) for tool in linked}
    failed = sorted(tool for tool, outcome in outcomes.items() if outcome and outcome[0] in ("error", "denied"))
    succeeded = [tool for tool, outcome in outcomes.items() if outcome and outcome[0] == "ok"]
    if failed and succeeded:
        # "booked" fits book_hotel (ok) and book_flight (failed): the clause's other words decide.
        # "Your hotel and flight are booked" names the flight, so it claims the failed booking too.
        named = sorted(tool for tool in index.named_in_clause(claim) if tool in failed)
        return ("failed", named[0], linked) if named else ("unlinked", "", linked)
    if not linked:
        return ("unlinked", "", linked)
    if failed:
        return ("failed", failed[0], linked)
    if succeeded:
        return None
    return ("never", sorted(linked)[0], linked)


_WORDS_RE = re.compile(r"\w+")


def _argument_values(action: dict[str, Any]) -> set[str]:
    """Distinctive text arguments of a call (ids, names): "a-1" from {"order_id": "A-1"}."""
    args = action.get("args") or action.get("arguments") or {}
    if not isinstance(args, dict):
        return set()
    return {value.strip().lower() for value in args.values()
            if isinstance(value, str) and 3 <= len(value.strip()) <= 60}


def _names_a_successful_call(clause: str, calls: list[tuple[bool, set[str]]]) -> bool:
    """The clause names an argument of a call that succeeded, and none of a call that failed."""
    good = set().union(*(values for ok, values in calls if ok)) if calls else set()
    bad = set().union(*(values for ok, values in calls if not ok)) if calls else set()
    lowered = clause.lower()

    def named(values: set[str]) -> bool:
        return any(re.search(rf"(?<![\w-]){re.escape(value)}(?![\w-])", lowered) for value in values)

    return named(good - bad) and not named(bad - good)


def _grounded(claim: Claim, successful_words: dict[str, set[str]], about: set[str]) -> bool:
    """Another tool's successful result contains the claimed word, e.g. a lookup that returned
    "SHIPPED". Results of the tools the claim is about don't count: a booked hotel doesn't
    back "your hotel and flight are booked" when the flight failed."""
    if claim.tool:
        return False
    words = _WORDS_RE.findall(claim.verb.lower())
    if not words:
        return False
    word = max(words, key=len)
    return any(word in seen for tool, seen in successful_words.items() if tool not in about)


class ReasoningFaithfulnessMetric:
    """Flags success claims that the trace contradicts.

    It checks each step's thought (against the outcomes before that step), the
    final response, and the text of messages the agent sent (email, reply,
    notify... tools). A claim is contradicted when:

    - it comes right after a failure, a tool error or an action a person denied
      (unless the claim is about another tool, one that succeeded);
    - it's about a tool whose last call failed or was denied, even when other
      calls came after it ("your refund has been processed" after a failed refund
      and a successful confirmation email);
    - it says an action was done ("refunded", "I called export_data") by a tool
      that never ran.

    The last two need the claim to be about a specific tool (see
    ``core/faithfulness.py``), and are dropped when a successful tool result
    contains the claimed word (a lookup that returned "SHIPPED").
    """

    @staticmethod
    def evaluate(trace: list[dict[str, Any]], final_response: str = "", known_tools: Any = None,
                 batches: list[int] | None = None) -> dict[str, Any]:
        tools = {str(tool) for tool in known_tools or ()}
        for step in trace:
            action = step.get("action")
            if isinstance(action, dict) and action.get("type", "tool_call") == "tool_call" and action.get("name"):
                tools.add(str(action["name"]))
            elif isinstance(action, dict) and action.get("type") == "approval" and action.get("tool"):
                tools.add(str(action["tool"]))
        index = ToolIndex(tools)
        if batches is None or len(batches) != len(trace):
            batches = list(range(len(trace)))

        status: dict[str, tuple[str, int]] = {}      # tool -> ("ok" | "error" | "denied", step number)
        last_failure: tuple[str, int] | None = None  # the most recent outcome, if it was a failure
        successful_words: dict[str, set[str]] = {}   # tool -> words of its successful results
        call_values: dict[str, list[tuple[bool, set[str]]]] = {}  # tool -> (succeeded, argument values) per call
        failed_calls: list[dict[str, Any]] = []
        tool_names = frozenset(tools)

        def judge(text: str, prefix: str, mode: str) -> str | None:
            """The contradiction in a statement, if any. ``mode`` is "thought", "final" or "message"."""
            for claim in find_claims(text, tool_names):
                verdict = _verdict(claim, index, status)
                if verdict is None:
                    continue
                kind, tool, about = verdict
                if kind == "failed" and _names_a_successful_call(claim.clause, call_values.get(tool, [])):
                    continue  # "Order A-1 was cancelled" when the A-1 call worked and the A-2 call failed
                if kind == "failed":
                    outcome = status[tool]
                    if mode != "message" and last_failure == outcome:
                        return f"{prefix} claims success right after {_DESCRIBE[outcome[0]]}"
                    if not _grounded(claim, successful_words, about):
                        what = "a person denied it" if outcome[0] == "denied" else "it failed"
                        return f"{prefix} claims '{tool}' succeeded, but {what} (step {outcome[1]})"
                    continue
                if kind == "never":
                    if mode == "thought":
                        continue  # a thought narrating the call it's about to make
                    if (claim.action or claim.tool) and not _grounded(claim, successful_words, about):
                        return f"{prefix} claims '{tool}' was done, but it never ran"
                if mode != "message" and last_failure and not acknowledges_failure(text):
                    return f"{prefix} claims success right after {_DESCRIBE[last_failure[0]]}"
            return None

        def record(step: dict[str, Any], number: int) -> None:
            nonlocal last_failure
            action = step.get("action")
            if isinstance(action, dict) and action.get("type") == "approval":
                if not action.get("approved", True):
                    last_failure = ("denied", number)
                    if action.get("tool"):
                        status[str(action["tool"])] = last_failure
                return
            if not isinstance(action, dict) or action.get("type", "tool_call") != "tool_call":
                return  # other events (plans, handoffs...) have no outcome; the last one stands
            name = str(action.get("name") or "")
            if "observation" not in step:
                if name:
                    status.setdefault(name, ("ok", number))
                return
            signal = failure_signal(step.get("observation"), name)
            if signal:
                last_failure = ("error", number)
                failed_calls.append({"step": number, "tool": name, "signal": signal})
            else:
                last_failure = None
                successful_words.setdefault(name, set()).update(
                    _WORDS_RE.findall(str(step.get("observation", "")).lower()))
            if name:
                status[name] = ("error" if signal else "ok", number)
                call_values.setdefault(name, []).append((not signal, _argument_values(action)))

        checked = 0
        anomalies: list[str] = []
        numbers = [step.get("step_index") or position for position, step in enumerate(trace, start=1)]
        batch_end = {batch: position for position, batch in enumerate(batches)}
        pending: dict[int, list[int]] = {}  # position ending a batch -> positions of its messages
        for position, step in enumerate(trace):
            raw_thought = step.get("thought") or ""
            thought = (raw_thought if isinstance(raw_thought, str) else str(raw_thought)).strip()
            if thought:
                checked += 1
                anomaly = judge(thought, f"Step {numbers[position]}:", "thought")
                if anomaly:
                    anomalies.append(anomaly)
            record(step, numbers[position])
            action = step.get("action")
            if (isinstance(action, dict) and action.get("type", "tool_call") == "tool_call"
                    and is_message_tool(str(action.get("name") or ""))):
                pending.setdefault(batch_end[batches[position]], []).append(position)
            # A message is judged when its batch is done, so calls running alongside it count
            for message_position in pending.pop(position, []):
                message_action = trace[message_position]["action"]
                args = message_action.get("args") or message_action.get("arguments") or {}
                texts = [value for key, value in args.items()
                         if str(key).lower() in _MESSAGE_ARGS and isinstance(value, str)] if isinstance(args, dict) else []
                prefix = f"Step {numbers[message_position]}: message sent with '{message_action['name']}'"
                anomaly = judge(" ".join(texts), prefix, "message") if texts else None
                if anomaly:  # a message only counts as checked when it contradicts the trace
                    checked += 1
                    anomalies.append(anomaly)

        final_response = (final_response or "").strip()
        if final_response:
            checked += 1
            anomaly = judge(final_response, "Final response", "final")
            if anomaly:
                anomalies.append(anomaly)

        return {
            "score": round((checked - len(anomalies)) / checked, 2) if checked else 1.0,
            "anomalies": anomalies,
            "checked": checked,
            "failed_calls": failed_calls,
        }
