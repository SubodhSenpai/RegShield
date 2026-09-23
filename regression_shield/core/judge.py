"""Optional LLM judge: scores whether an agent's reasoning and answer are grounded in its tool results.

Works with any OpenAI-compatible chat completions endpoint (OpenRouter by default,
OpenAI, Groq, Ollama, vLLM...).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

from regression_shield.core.patterns import action_of, event_type, step_number

logger = logging.getLogger(__name__)

# Long tool results are cut to keep the prompt small
_MAX_OBSERVATION_CHARS = 300

_SYSTEM_PROMPT = (
    "You judge AI agent runs. Check whether the agent's reasoning matches what its tools "
    "returned, and whether the final response answers the goal without claiming anything "
    "the trace doesn't support. Events such as handoffs, plans and human approvals are part "
    "of the run: an action a person denied must not be reported as done.\n\n"
    "Score from 0.0 to 1.0:\n"
    "1.0 = reasoning and answer fully grounded in the tool results, goal achieved.\n"
    "0.5 = a minor reasoning gap or an incomplete answer.\n"
    "0.0 = a hallucination, success claimed after an error or denial, or a wrong outcome.\n\n"
    "Reply with only this JSON object:\n"
    '{"score": <number from 0.0 to 1.0>, "reasoning": "<one or two sentences>"}'
)


def _describe_step(step: dict[str, Any], position: int) -> str:
    """One trace step as prompt text: its thought, then the tool call and result, or the event."""
    agent = f" ({step['agent']})" if step.get("agent") else ""
    lines = [f"Step {step_number(step, position)}{agent}:"]
    if step.get("thought"):
        lines.append(f"  Thought: {step['thought']}")
    action = action_of(step)
    kind = event_type(step)
    if kind == "tool_call":
        args = action.get("args") or action.get("arguments") or {}
        lines.append(f"  Action: {action.get('name', 'tool')}({json.dumps(args, default=str)})")
        lines.append(f"  Observation: {str(step.get('observation', ''))[:_MAX_OBSERVATION_CHARS]}")
    else:
        details = {key: value for key, value in action.items() if key != "type"}
        lines.append(f"  Event: {kind} {json.dumps(details, default=str)}")
    return "\n".join(lines)


class LLMJudge:
    """Asks an LLM to score a trace from 0 to 1; a score of ``PASS_SCORE`` or more passes.

    Settings come from the arguments, then the environment. ``OPENROUTER_API_KEY``
    is sent to OpenRouter; ``OPENAI_API_KEY`` alone is sent to OpenAI. Set
    ``JUDGE_MODEL`` and ``OPENROUTER_BASE_URL`` / ``OPENAI_BASE_URL`` to override
    the model and endpoint (e.g. a local Ollama server).
    """

    DEFAULT_MODEL = "minimax/minimax-m2.7:free"
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    OPENAI_MODEL = "gpt-4.1-mini"
    OPENAI_BASE_URL = "https://api.openai.com/v1"
    PASS_SCORE = 0.70

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ):
        if not api_key and not os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENAI_API_KEY"):
            # An OpenAI key goes to OpenAI, not to the OpenRouter default
            self.api_key = os.getenv("OPENAI_API_KEY")
            default_base_url = os.getenv("OPENAI_BASE_URL") or self.OPENAI_BASE_URL
            default_model = self.OPENAI_MODEL
        else:
            self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
            default_base_url = os.getenv("OPENROUTER_BASE_URL") or os.getenv("OPENAI_BASE_URL") or self.DEFAULT_BASE_URL
            default_model = self.DEFAULT_MODEL
        self.model = model or os.getenv("JUDGE_MODEL") or default_model
        self.base_url = (base_url or default_base_url).rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _parse_reply(text: str) -> dict[str, Any]:
        """The JSON object in a model reply, which may be wrapped in a ``` block or in prose."""
        text = text.strip()
        if "```" in text:
            for block in text.split("```"):
                block = block.strip().removeprefix("json").strip()
                if "{" in block and "}" in block:
                    text = block
                    break
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or "score" not in parsed:
            raise ValueError("judge reply has no 'score' field")
        return parsed

    def _error_result(self, message: str) -> dict[str, Any]:
        """Result for when no verdict could be obtained. It never counts as a pass."""
        return {
            "score": None,
            "passed": False,
            "error": message,
            "reasoning": f"LLM Judge could not run: {message}",
            "model": self.model,
        }

    def verify_reasoning_and_outcome(self, goal: str, steps: list[dict[str, Any]], final_response: str) -> dict[str, Any]:
        """Ask the model whether the agent's reasoning and final response are grounded in its tool results.

        Returns ``{"score", "passed", "reasoning", "model"}``. When no verdict can be
        obtained (no key, HTTP error, unusable reply), ``score`` is None, ``passed``
        is False and ``error`` says why.
        """
        if not self.api_key:
            return self._error_result("no API key provided (set OPENROUTER_API_KEY or OPENAI_API_KEY)")

        trace_text = "\n".join(_describe_step(step, position) for position, step in enumerate(steps, 1))
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Goal: {goal}\n\nTrace:\n{trace_text}\n\nFinal response: {final_response}"},
            ],
            "temperature": 0.0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        logger.debug("Judge request: model=%s endpoint=%s steps=%d", self.model, endpoint, len(steps))
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)
            if response.status_code != 200:
                logger.warning("LLM judge HTTP %d: %s", response.status_code, response.text[:120])
                return self._error_result(f"HTTP {response.status_code} from {endpoint}")
            verdict = self._parse_reply(response.json()["choices"][0]["message"]["content"])
            score = max(0.0, min(1.0, float(verdict["score"])))
        except Exception as err:  # any failure means no verdict, which the evaluator handles
            logger.warning("LLM judge failed: %s", err)
            return self._error_result(f"{type(err).__name__}: {err}")

        logger.debug("Judge verdict: score=%.2f in %.1fs", score, time.perf_counter() - started)
        return {
            "score": round(score, 2),
            "passed": score >= self.PASS_SCORE,
            "reasoning": str(verdict.get("reasoning", "")).strip(),
            "model": self.model,
        }
