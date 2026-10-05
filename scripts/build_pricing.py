"""Regenerate regression_shield/data/pricing.json, the bundled model price snapshot.

Run before a release to refresh list prices:

    python scripts/build_pricing.py            # fetch LiteLLM's public price list
    python scripts/build_pricing.py prices.json  # or use a local copy of it

Prices come from LiteLLM's model_prices_and_context_window.json (MIT licensed),
the price list most LLM tooling uses. Only chat and completion models with an
input and an output price are kept. Prices are stored in USD per million tokens
as [input, output, cached_input, cache_write]; a null cache price means "same as
input" when the cost is computed.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
OUTPUT = Path(__file__).resolve().parent.parent / "regression_shield" / "data" / "pricing.json"
MODES = {"chat", "completion", "responses"}


def per_million(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return None
    return round(float(value) * 1_000_000, 6)


def build(raw: dict) -> dict[str, list[float | None]]:
    models: dict[str, list[float | None]] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict) or entry.get("mode") not in MODES:
            continue
        input_price = per_million(entry.get("input_cost_per_token"))
        output_price = per_million(entry.get("output_cost_per_token"))
        if input_price is None or output_price is None:
            continue
        models[name] = [input_price, output_price,
                        per_million(entry.get("cache_read_input_token_cost")),
                        per_million(entry.get("cache_creation_input_token_cost"))]
    return dict(sorted(models.items()))


def main(argv: list[str]) -> None:
    if argv:
        raw = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    else:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "regshield-build"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read())
    models = build(raw)
    header = {
        "prices_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "LiteLLM model price list (MIT license), https://github.com/BerriAI/litellm",
        "units": "USD per 1M tokens: [input, output, cached_input, cache_write]",
    }
    # One model per line keeps diffs readable when prices change
    lines = [f"  {json.dumps(key)}: {json.dumps(value)}" for key, value in header.items()]
    lines.append('  "models": {\n' + ",\n".join(f"    {json.dumps(name)}: {json.dumps(prices)}"
                                                for name, prices in models.items()) + "\n  }")
    OUTPUT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    print(f"Wrote {len(models)} models to {OUTPUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
