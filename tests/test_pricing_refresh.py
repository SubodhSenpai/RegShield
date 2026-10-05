"""regshield pricing refresh / show: keeping the list prices RegShield uses up to date."""

import json

import pytest

from regression_shield.cli import main
from regression_shield.core import cost


def litellm_copy(path, gpt4o_input=2.0):
    """A small stand-in for LiteLLM's model_prices_and_context_window.json."""
    data = {"sample_spec": {"mode": "chat"}}  # no prices: skipped
    for number in range(120):
        data[f"house-model-{number}"] = {"mode": "chat", "input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}
    data["gpt-4o"] = {"mode": "chat", "input_cost_per_token": gpt4o_input / 1e6, "output_cost_per_token": 10e-6,
                      "cache_read_input_token_cost": 1.25e-6}
    data["text-embedding-3-small"] = {"mode": "embedding", "input_cost_per_token": 2e-8, "output_cost_per_token": 0}
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    monkeypatch.setenv("REGSHIELD_CACHE_DIR", str(directory))
    return directory


def test_refresh_saves_a_list_that_regshield_then_uses(tmp_path, cache):
    assert cost.price_list_path() == cost.PRICING_FILE
    result = cost.refresh_prices(litellm_copy(tmp_path / "prices.json"))
    saved = str(cache / "pricing.json")
    assert (result["path"], result["in_use"], result["models"]) == (saved, True, 121)  # embeddings are skipped
    assert cost.price_list_path() == saved
    price = cost.price_for("gpt-4o")
    assert (price.input, price.output, price.cached_input, price.key) == (2.0, 10.0, 1.25, "gpt-4o")
    assert result["changed"]["gpt-4o"][1] == [2.0, 10.0, 1.25, None]
    assert "house-model-0" in result["added"] and len(result["removed"]) > 1000
    assert cost.snapshot_date() == result["prices_as_of"]


def test_the_saved_file_keeps_the_bundled_format(tmp_path, cache):
    cost.refresh_prices(litellm_copy(tmp_path / "prices.json"))
    lines = (cache / "pricing.json").read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith('  "prices_as_of": ') and lines[4] == '  "models": {'
    assert '    "gpt-4o": [2.0, 10.0, 1.25, null],' in lines


def test_an_older_list_never_replaces_a_newer_bundled_one(tmp_path, cache):
    models = cost.build_price_list(json.loads(open(litellm_copy(tmp_path / "p.json"), encoding="utf-8").read()))
    cost.write_price_list(models, str(cache / "pricing.json"), prices_as_of="2020-01-01")
    assert cost.price_list_path() == cost.PRICING_FILE


def test_a_price_list_named_in_the_environment_wins(tmp_path, cache, monkeypatch):
    team_list = tmp_path / "team-prices.json"
    cost.write_price_list({"gpt-4o": [1.0, 2.0, None, None]}, str(team_list), prices_as_of="2026-01-01")
    monkeypatch.setenv("REGSHIELD_PRICE_LIST", str(team_list))
    assert cost.price_list_path() == str(team_list)
    assert cost.price_for("gpt-4o").input == 1.0 and cost.snapshot_date() == "2026-01-01"


def test_something_else_is_rejected_and_nothing_is_written(tmp_path, cache):
    other = tmp_path / "other.json"
    other.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ValueError, match="only 0 priced models"):
        cost.refresh_prices(str(other))
    assert not (cache / "pricing.json").exists()


def test_cli_refresh_and_show(tmp_path, cache, capsys):
    assert main(["pricing", "refresh", "--from", litellm_copy(tmp_path / "prices.json")]) == 0
    out = capsys.readouterr().out
    assert "Saved prices for 121 models" in out
    assert "gpt-4o: $2.5 in / $10 out / $1.25 cached -> $2 in / $10 out / $1.25 cached per 1M tokens" in out
    assert out.rstrip().endswith("RegShield now prices calls with this list.")
    assert main(["pricing", "show", "gpt-4o", "no-such-model"]) == 1  # 1: a model has no price
    out = capsys.readouterr().out
    assert f"Price list: {cache / 'pricing.json'}" in out
    assert "  gpt-4o: $2 in / $10 out / $1.25 cached per 1M tokens (price list: gpt-4o)" in out
    assert "  no-such-model: no price; add it under [tool.regshield.pricing.models]" in out


def test_cli_refresh_to_another_file_says_how_to_use_it(tmp_path, cache, capsys):
    target = tmp_path / "team" / "prices.json"
    assert main(["pricing", "refresh", "--from", litellm_copy(tmp_path / "prices.json"), "--output", str(target)]) == 0
    assert f"To use it, set REGSHIELD_PRICE_LIST={target}" in capsys.readouterr().out
    assert cost.price_list_path() == cost.PRICING_FILE


def test_cli_show_includes_your_own_prices(tmp_path, cache, capsys, monkeypatch):
    config = tmp_path / "regshield.toml"
    config.write_text('[pricing.models]\n"my-finetune*" = { input = 1.0, output = 4.0 }\n', encoding="utf-8")
    monkeypatch.setenv("REGSHIELD_CONFIG", str(config))
    assert main(["pricing", "show", "my-finetune-v2"]) == 0
    assert "  my-finetune-v2: $1 in / $4 out per 1M tokens (your pricing: my-finetune*)" in capsys.readouterr().out


def test_cli_reports_a_missing_source(tmp_path, cache, capsys):
    assert main(["pricing", "refresh", "--from", str(tmp_path / "missing.json")]) == 2
    assert capsys.readouterr().err.startswith("error: ")
