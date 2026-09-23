"""The five core trace metrics. Each ``evaluate`` returns a dict with a 0-1 ``score``."""

from __future__ import annotations

import json
import re
from typing import Any

# Phrases asserting that an action worked. Word boundaries keep "unsuccessful"
# from matching; the lookbehinds skip simple negations like "not successful".
_SUCCESS_CLAIM_RE = re.compile(
    r"(?<!not )(?<!n't )(?<!never )(?<!no )(?<!without )\b("
    r"success(ful(ly)?)?|succeed(ed|s)?|confirmed|completed|processed|executed|"
    r"went through|worked|carried out|taken care of|all set|(is|are|was|were|been|all) done"
    r")\b",
    re.IGNORECASE,
)
# Wording that acknowledges a failure, e.g. "Error confirmed, escalating".
_FAILURE_ACK_RE = re.compile(
    r"\b(errors?|fail(ed|s|ure)?|denied|unable|could(n't| not)|can(not|'t)|blocked|rejected|timed out)\b",
    re.IGNORECASE,
)
# Mentions of an error that report its absence: '"error": null', "errors=[]",
# "0 errors", "no errors", "error-free". Stripped before looking for errors.
_NO_ERROR_RE = re.compile(
    r"""["']?(errors?|exceptions?|policy_violations?)(_?count)?["']?\s*[:=]\s*"""
    r"""(null|none|false|0|""|''|\[\]|\{\})(?![\w.])"""
    r"|\b(no|zero|0|without( any)?)\s+(errors?|exceptions?)\b"
    r"|\berror[- ]free\b",
    re.IGNORECASE,
)
_ERROR_OBS_MARKERS = ("error", "policy_violation", "exception", "permission denied", "access denied")

WEIGHTS = {
    "tool_selection": 0.25,
    "argument_correctness": 0.25,
    "call_ordering": 0.20,
    "step_efficiency": 0.15,
    "reasoning_faithfulness": 0.15,
}


def claims_success(text: str) -> bool:
    """True if text asserts success without acknowledging a failure."""
    if _FAILURE_ACK_RE.search(_NO_ERROR_RE.sub(" ", text)):
        return False
    return bool(_SUCCESS_CLAIM_RE.search(text))


def is_error_observation(obs: str) -> bool:
    """True if a tool result reports a failure (``"error": null`` and "0 errors" don't count)."""
    obs_lower = _NO_ERROR_RE.sub(" ", obs).lower()
    return any(marker in obs_lower for marker in _ERROR_OBS_MARKERS)


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


def _args_match(actual: Any, expected: Any) -> bool:
    """Numbers compare numerically; text ignores case, surrounding spaces, '_' and '-'."""
    if actual is None:
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

        calls: dict[str, list[dict[str, Any]]] = {}
        for step in trace:
            action = step.get("action") or {}
            if action.get("type", "tool_call") == "tool_call" and action.get("name"):
                args = action.get("args")
                calls.setdefault(action["name"], []).append(args if args is not None else action.get("arguments", {}))

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
            action = step.get("action") or {}
            if action.get("type", "tool_call") == "tool_call":
                signature = f"{action.get('name')}:{json.dumps(action.get('args', {}), sort_keys=True, default=str)}"
                redundant += signature in seen
                seen.add(signature)

        score = max(0.0, optimal_steps / max(optimal_steps, total) - min(0.6, redundant * 0.25))
        return {"score": round(score, 2), "total_steps": total, "optimal_steps": optimal_steps,
                "redundant_calls": redundant}


class ReasoningFaithfulnessMetric:
    """Flags thoughts or a final answer that claim success right after a failure:
    a tool call that returned an error, or an action a person denied.

    A thought is checked against the outcome *before* it, so a failure on the
    last step is checked against ``final_response``.
    """

    @staticmethod
    def evaluate(trace: list[dict[str, Any]], final_response: str = "") -> dict[str, Any]:
        checked = 0
        anomalies: list[str] = []
        last_failure: str | None = None  # the most recent outcome, if it was a failure
        for position, step in enumerate(trace, start=1):
            thought = (step.get("thought") or "").strip()
            if thought:
                checked += 1
                if last_failure and claims_success(thought):
                    anomalies.append(f"Step {step.get('step_index') or position}: claims success right after {last_failure}")
            action = step.get("action")
            if isinstance(action, dict) and action.get("type") == "approval":
                if not action.get("approved", True):
                    last_failure = "a denied approval"
            # Other pattern events (plans, handoffs...) have no outcome; keep the last one
            elif "observation" in step:
                last_failure = "an error" if is_error_observation(str(step.get("observation", ""))) else None

        final_response = (final_response or "").strip()
        if final_response:
            checked += 1
            if last_failure and claims_success(final_response):
                anomalies.append(f"Final response claims success right after {last_failure}")

        return {
            "score": round((checked - len(anomalies)) / checked, 2) if checked else 1.0,
            "anomalies": anomalies,
            "checked": checked,
        }
