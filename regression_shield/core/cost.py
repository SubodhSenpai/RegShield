"""Token usage and cost of a run: the LLM calls an agent made and the paid tools it called.

A trace can carry ``llm_calls`` next to its steps, one record per model call::

    {"model": "gpt-4o-mini", "input_tokens": 1200, "output_tokens": 85,
     "cached_input_tokens": 1024, "cost_usd": 0.0002, "agent": "billing"}

``input_tokens`` counts every input token, including the cached ones
(``cached_input_tokens``) and those written to the cache (``cache_write_tokens``).
A recorded ``cost_usd`` (some providers, like OpenRouter, report the real cost)
is used as is. Otherwise the call is priced from, in order: your pricing
(``pricing=`` or ``[tool.regshield.pricing]``), then the bundled snapshot of public
list prices in ``data/pricing.json``. Tool steps can carry a ``cost_usd`` too, or
get one from ``pricing["tools"]`` (USD per call).

The estimates use base list prices: batch discounts, long-context tiers and
negotiated rates aren't modelled.
"""

from __future__ import annotations

import fnmatch
import functools
import json
import os
import re
from dataclasses import dataclass
from typing import Any

PRICING_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pricing.json")
# Version and date suffixes that don't change the price: -2024-08-06, -20241022, @20250929, -latest
_VERSION_SUFFIX = re.compile(r"(?:[-@](?:20\d{2}-?\d{2}-?\d{2}|latest)|-v\d+(?::\d+)?)$")
_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens")
_SYNONYMS = {
    "prompt_tokens": "input_tokens",
    "completion_tokens": "output_tokens",
    "cache_read_tokens": "cached_input_tokens",
    "cache_read_input_tokens": "cached_input_tokens",
    "cached_tokens": "cached_input_tokens",
    "cache_creation_tokens": "cache_write_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
    "cost": "cost_usd",
}


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens. A missing cache price falls back to the input price."""

    input: float
    output: float
    cached_input: float | None = None
    cache_write: float | None = None
    key: str = ""             # the pricing entry that matched
    source: str = "snapshot"  # "pricing" (yours) or "snapshot" (bundled list prices)

    def cost(self, input_tokens: int = 0, output_tokens: int = 0,
             cached_input_tokens: int = 0, cache_write_tokens: int = 0) -> float:
        cached = min(cached_input_tokens, input_tokens)
        written = min(cache_write_tokens, input_tokens - cached)
        uncached = input_tokens - cached - written
        total = (uncached * self.input + output_tokens * self.output
                 + cached * (self.input if self.cached_input is None else self.cached_input)
                 + written * (self.input if self.cache_write is None else self.cache_write))
        return total / 1_000_000


# -- the bundled snapshot ---------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _snapshot() -> tuple[dict[str, ModelPrice], dict[str, ModelPrice], dict[str, ModelPrice], str]:
    """(exact, lowercase, by model name without provider prefix, snapshot date)."""
    try:
        with open(PRICING_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, {}, {}, "unavailable"
    exact: dict[str, ModelPrice] = {}
    for key, prices in data.get("models", {}).items():
        cached = prices[2] if len(prices) > 2 else None
        written = prices[3] if len(prices) > 3 else None
        exact[key] = ModelPrice(input=prices[0], output=prices[1], cached_input=cached, cache_write=written,
                                key=key, source="snapshot")
    lower = {key.lower(): price for key, price in exact.items()}
    # A bare model name ("mistral-large-latest") maps to its first-party entry when there is
    # one, then to its maker's entry ("mistral/..." rather than "azure_ai/..."), then to the
    # entry with the fewest path segments
    def preference(key: str) -> tuple[int, int, str]:
        tail = key.lower().rsplit("/", 1)[-1]
        provider = key.lower().split("/", 1)[0] if "/" in key else ""
        own = provider == "" or tail.startswith(provider)
        return (0 if own else 1, key.count("/"), key)

    tails: dict[str, ModelPrice] = {}
    for key in sorted(exact, key=preference):
        tails.setdefault(key.lower().rsplit("/", 1)[-1], exact[key])
    return exact, lower, tails, str(data.get("prices_as_of", "unknown"))


def snapshot_date() -> str:
    """The date of the bundled list prices."""
    return _snapshot()[3]


# -- your pricing -----------------------------------------------------------------------

def validate_pricing(pricing: Any) -> dict[str, dict[str, Any]]:
    """Check a pricing table: ``{"models": {name: {"input", "output", ...}}, "tools": {name: usd}}``.

    Model prices are USD per million tokens (``cached_input`` and ``cache_write``
    are optional); model names may use ``*`` wildcards. Tool prices are USD per call.
    """
    if pricing is None:
        return {"models": {}, "tools": {}}
    if not isinstance(pricing, dict) or set(pricing) - {"models", "tools"}:
        raise ValueError('pricing must be {"models": {...}, "tools": {...}}; '
                         f"got keys {sorted(pricing) if isinstance(pricing, dict) else type(pricing).__name__}")
    models = pricing.get("models") or {}
    tools = pricing.get("tools") or {}
    if not isinstance(models, dict) or not isinstance(tools, dict):
        raise ValueError("pricing 'models' and 'tools' must be tables (dicts)")
    for name, price in models.items():
        if not isinstance(price, dict) or not {"input", "output"} <= set(price):
            raise ValueError(f"pricing for model '{name}' needs 'input' and 'output' (USD per 1M tokens)")
        unknown = set(price) - {"input", "output", "cached_input", "cache_write"}
        if unknown:
            raise ValueError(f"pricing for model '{name}' has unknown field(s) {sorted(unknown)}; "
                             "use input, output, cached_input, cache_write (USD per 1M tokens)")
        for field_name, value in price.items():
            if not _is_number(value) or value < 0:
                raise ValueError(f"pricing for model '{name}': {field_name} must be a number >= 0")
    for name, value in tools.items():
        if not _is_number(value) or value < 0:
            raise ValueError(f"pricing for tool '{name}' must be a number >= 0 (USD per call)")
    return {"models": dict(models), "tools": dict(tools)}


def merge_pricing(*tables: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Combine pricing tables; later tables win entry by entry."""
    merged: dict[str, dict[str, Any]] = {"models": {}, "tools": {}}
    for table in tables:
        checked = validate_pricing(table)
        merged["models"].update(checked["models"])
        merged["tools"].update(checked["tools"])
    return merged


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _model_names(model: str) -> list[str]:
    """Spellings to try, most specific first: as given, without provider prefix, without version suffix."""
    names = [model.strip()]
    tail = names[0].rsplit("/", 1)[-1]
    for name in (tail, _VERSION_SUFFIX.sub("", tail)):
        if name and name not in names:
            names.append(name)
    return names


def price_for(model: str, pricing: dict[str, Any] | None = None) -> ModelPrice | None:
    """The price of ``model``: your pricing first (exact name, then ``*`` patterns, most
    specific first), then the bundled snapshot. None when it has no known price."""
    if not model:
        return None
    names = _model_names(model)
    yours = (pricing or {}).get("models") or {}
    if yours:
        lowered = {name.lower(): (name, price) for name, price in yours.items()}
        for name in names:
            if name.lower() in lowered:
                key, price = lowered[name.lower()]
                return ModelPrice(key=key, source="pricing", **price)
        patterns = sorted((name for name in yours if any(c in name for c in "*?[")), key=len, reverse=True)
        for pattern in patterns:
            if any(fnmatch.fnmatchcase(name.lower(), pattern.lower()) for name in names):
                return ModelPrice(key=pattern, source="pricing", **yours[pattern])
    return _snapshot_price(model.strip())


# Who makes a model family: their own listings price it best ("anthropic.claude-..." on Bedrock,
# "gemini/gemini-...", "mistral/..."), then OpenRouter, which passes the maker's prices through
_MAKERS = {"claude": "anthropic", "gpt": "openai", "chatgpt": "openai", "o1": "openai", "o3": "openai",
           "o4": "openai", "gemini": "gemini", "gemma": "gemini", "grok": "xai", "mistral": "mistral",
           "codestral": "mistral", "pixtral": "mistral", "magistral": "mistral", "ministral": "mistral",
           "devstral": "mistral", "deepseek": "deepseek", "command": "cohere", "llama": "meta"}
# Bedrock-style ids put the maker before a dot: "anthropic.claude-...", "us.anthropic.claude-..."
_DOTTED_MAKER = re.compile(r"^(?:[a-z]{2}\.)?([a-z][a-z_]*)\.(?=[a-z])")
# A version of the same model: a date or a vN, not a different size ("llama3-70b" isn't "llama3")
_DATED = re.compile(r"[-@](?:20\d{6}|20\d{2}-\d{2}-\d{2}|v\d+)(?:[-:@]|$)")


def _base(tail: str) -> tuple[str, str]:
    """(model name without a Bedrock-style maker prefix, that maker or "")."""
    match = _DOTTED_MAKER.match(tail)
    return (tail[match.end():], match.group(1)) if match else (tail, "")


def _rank(key: str, family: str) -> int:
    """0: first-party listing, 1: the maker's own, 2: OpenRouter, 3: another reseller."""
    lowered = key.lower()
    path = lowered.rsplit("/", 1)[0] if "/" in lowered else ""
    _, dotted = _base(lowered.rsplit("/", 1)[-1])
    if not path and not dotted:
        return 0
    maker = _MAKERS.get(family, "")
    if maker and (path.split("/")[0].startswith(maker) or dotted == maker or f"/{maker}" in path):
        return 1
    return 2 if path.startswith("openrouter") else 3


@functools.lru_cache(maxsize=8192)
def _snapshot_price(model: str) -> ModelPrice | None:
    exact, lower, _, _ = _snapshot()
    names = _model_names(model)
    for name in names:
        if name in exact:
            return exact[name]
        if name.lower() in lower:
            return lower[name.lower()]
    family = re.split(r"[-_.:@ ]", names[-1].lower(), maxsplit=1)[0]
    family = re.sub(r"\d.*$", "", family) or family  # "llama3" -> "llama", but keep "o3"
    if family not in _MAKERS and re.split(r"[-_.:@ ]", names[-1].lower(), maxsplit=1)[0] in _MAKERS:
        family = re.split(r"[-_.:@ ]", names[-1].lower(), maxsplit=1)[0]
    lowered = [name.lower() for name in names]
    full = model.lower()
    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    for key in exact:
        key_lower = key.lower()
        base, _ = _base(key_lower.rsplit("/", 1)[-1])
        if "/" in full and key_lower.endswith("/" + full):
            closeness = 0  # "meta-llama/llama-3.1-70b-instruct" -> "openrouter/meta-llama/llama-3.1-70b-instruct"
        elif base in lowered:
            closeness = 1  # same model name at another provider
        elif any(base.startswith(name) and _DATED.match(base, len(name)) for name in lowered):
            closeness = 2  # a dated version: "claude-3-5-haiku" -> "...claude-3-5-haiku-20241022-v1:0"
        else:
            continue
        candidates.append(((closeness if closeness == 0 else 1, _rank(key, family), closeness, key), key))
    if not candidates:
        # The longest listed name the model name extends: "gpt-4o-mini-ft" -> "gpt-4o-mini"
        tail = lowered[-1]
        for key in exact:
            base, _ = _base(key.lower().rsplit("/", 1)[-1])
            if len(base) >= 4 and tail.startswith(base) and tail[len(base):len(base) + 1] in ("-", ":", "@", "."):
                candidates.append(((2, _rank(key, family), -len(base), key), key))
    if not candidates:
        return None
    return exact[min(candidates)[1]]


# -- usage records ----------------------------------------------------------------------

def normalize_llm_call(record: Any) -> dict[str, Any] | None:
    """A usage record with RegShield's field names, or None if it isn't one."""
    if not isinstance(record, dict):
        return None
    call: dict[str, Any] = {}
    for raw_key, value in record.items():
        key = _SYNONYMS.get(str(raw_key), str(raw_key))
        if key in call and key in _TOKEN_FIELDS:  # e.g. both prompt_tokens and input_tokens
            continue
        call[key] = value
    for field_name in _TOKEN_FIELDS:
        value = call.get(field_name, 0)
        call[field_name] = max(0, int(value)) if _is_number(value) else 0
    cost = call.get("cost_usd")
    if cost is not None and (not _is_number(cost) or cost < 0):
        call.pop("cost_usd")
    call["model"] = str(call.get("model") or "unknown")
    return call


def format_usd(amount: float) -> str:
    return f"${amount:,.4f}" if amount < 100 else f"${amount:,.2f}"


def summarize_cost(steps: list[dict[str, Any]], llm_calls: list[Any] | None,
                   pricing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Tokens and cost of a run, or None when the trace records no usage and no paid tool."""
    calls = [call for call in (normalize_llm_call(c) for c in llm_calls or []) if call]
    tool_prices = (pricing or {}).get("tools") or {}
    paid_steps = []
    for step in steps:
        raw_action = step.get("action")
        action: dict[str, Any] = raw_action if isinstance(raw_action, dict) else {}
        if action.get("type", "tool_call") != "tool_call" or not action.get("name"):
            continue
        cost = step.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            paid_steps.append((action["name"], float(cost)))
        elif action["name"] in tool_prices:
            paid_steps.append((action["name"], float(tool_prices[action["name"]])))
    if not calls and not paid_steps:
        return None

    models: dict[str, dict[str, Any]] = {}
    unpriced: list[str] = []
    llm_usd = 0.0
    for call in calls:
        entry = models.setdefault(call["model"], {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                  "cached_input_tokens": 0, "usd": 0.0, "priced_calls": 0})
        entry["calls"] += 1
        for field_name in ("input_tokens", "output_tokens", "cached_input_tokens"):
            entry[field_name] += call[field_name]
        if "cost_usd" in call:
            usd, source = float(call["cost_usd"]), "trace"
        else:
            price = price_for(call["model"], pricing)
            if price is None:
                if call["model"] not in unpriced:
                    unpriced.append(call["model"])
                continue
            usd = price.cost(call["input_tokens"], call["output_tokens"],
                             call["cached_input_tokens"], call["cache_write_tokens"])
            source = price.source
            entry["priced_as"] = price.key
        entry["usd"] += usd
        entry["priced_calls"] += 1
        entry["price_source"] = source if entry.get("price_source") in (None, source) else "mixed"
        llm_usd += usd

    tools: dict[str, dict[str, Any]] = {}
    for name, usd in paid_steps:
        entry = tools.setdefault(name, {"calls": 0, "usd": 0.0})
        entry["calls"] += 1
        entry["usd"] += usd
    tool_usd = sum(entry["usd"] for entry in tools.values())
    for entry in (*models.values(), *tools.values()):
        entry["usd"] = round(entry["usd"], 6)

    input_tokens = sum(call["input_tokens"] for call in calls)
    output_tokens = sum(call["output_tokens"] for call in calls)
    return {
        "total_usd": round(llm_usd + tool_usd, 6),
        "complete": not unpriced,  # False: some calls had no price, so total_usd is a lower bound
        "llm_usd": round(llm_usd, 6),
        "tool_usd": round(tool_usd, 6),
        "llm_calls": len(calls),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": sum(call["cached_input_tokens"] for call in calls),
        "total_tokens": input_tokens + output_tokens,
        "models": models,
        "tools": tools,
        "unpriced_models": unpriced,
        "prices_as_of": snapshot_date(),
    }


def describe_cost(cost: dict[str, Any]) -> str:
    """One line, e.g. ``$0.0123 (3 LLM calls, 1,801 tokens; 2 paid tool calls)``."""
    parts = []
    if cost["llm_calls"]:
        parts.append(f"{cost['llm_calls']} LLM call{'s' if cost['llm_calls'] != 1 else ''}, "
                     f"{cost['total_tokens']:,} tokens")
    paid = sum(entry["calls"] for entry in cost["tools"].values())
    if paid:
        parts.append(f"{paid} paid tool call{'s' if paid != 1 else ''}")
    text = f"{format_usd(cost['total_usd'])} ({'; '.join(parts)})"
    if cost["unpriced_models"]:
        text += f"; no price for {', '.join(repr(m) for m in cost['unpriced_models'])}"
    return text
