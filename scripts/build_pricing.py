"""Regenerate regression_shield/data/pricing.json, the bundled model price snapshot.

Run before a release to refresh list prices:

    python scripts/build_pricing.py            # fetch LiteLLM's public price list
    python scripts/build_pricing.py prices.json  # or use a local copy of it

Prices come from LiteLLM's model_prices_and_context_window.json (MIT licensed),
the price list most LLM tooling uses. Only chat and completion models with an
input and an output price are kept. Prices are stored in USD per million tokens
as [input, output, cached_input, cache_write]; a null cache price means "same as
input" when the cost is computed. Users refresh their own copy with
``regshield pricing refresh``, which writes the same format.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # use this checkout's package

from regression_shield.core.cost import PRICING_FILE, refresh_prices  # noqa: E402


def main(argv: list[str]) -> None:
    result = refresh_prices(argv[0] if argv else None, PRICING_FILE)
    print(f"Wrote {result['models']} models to {result['path']}")


if __name__ == "__main__":
    main(sys.argv[1:])
