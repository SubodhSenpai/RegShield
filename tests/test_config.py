"""Project settings ([tool.regshield] / regshield.toml) and the CLI features that use them."""

import json
import os

import httpx
import pytest

from regression_shield import AgentTraceEvaluator, LLMJudge, evaluate_trace
from regression_shield.cli import main
from regression_shield.config import find_config_file, load_config

DEPLOY = {"scenario_id": "deploy_gate", "expected_tools": ["run_tests", "deploy"], "optimal_step_count": 1}
GOOD = [{"action": {"name": "run_tests", "args": {}}, "observation": "42 passed"},
        {"action": {"name": "deploy", "args": {"env": "staging"}}, "observation": "DEPLOYED"}]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for var in ("REGSHIELD_CONFIG", "JUDGE_TIMEOUT", "JUDGE_MODEL", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                "OPENROUTER_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


# -- finding the file -------------------------------------------------------------------

def test_pyproject_table_is_found_from_a_subdirectory(tmp_path):
    write(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n\n[tool.regshield]\nmin_step_efficiency = 0.4\n")
    (tmp_path / "tests").mkdir()
    os.chdir(tmp_path / "tests")
    assert find_config_file() == str(tmp_path / "pyproject.toml")
    assert load_config() == {"min_step_efficiency": 0.4}


def test_the_project_root_without_settings_stops_the_search(tmp_path):
    write(tmp_path / "regshield.toml", "min_step_efficiency = 0.4\n")
    project = tmp_path / "project"
    project.mkdir()
    write(project / "pyproject.toml", "[project]\nname = 'x'\n")
    os.chdir(project)
    assert find_config_file() is None and load_config() == {}


def test_regshield_config_env_var_picks_or_disables_the_file(tmp_path, monkeypatch):
    other = write(tmp_path / "ci.toml", "min_tool_selection = 0.95\n")
    write(tmp_path / "regshield.toml", "min_tool_selection = 0.5\n")
    monkeypatch.setenv("REGSHIELD_CONFIG", other)
    assert load_config() == {"min_tool_selection": 0.95}
    monkeypatch.setenv("REGSHIELD_CONFIG", "")
    assert load_config() == {}


# -- precedence -------------------------------------------------------------------------

def test_arguments_beat_the_file_and_the_file_beats_defaults(tmp_path):
    write(tmp_path / "regshield.toml", "min_step_efficiency = 0.4\nmin_tool_selection = 0.99\n")
    looping = GOOD + [GOOD[1]]  # efficiency 0.08: fails 0.70 (default) and 0.4 (file), not 0.0 (argument)
    evaluator = AgentTraceEvaluator()
    assert evaluator.thresholds["step_efficiency"] == 0.4 and evaluator.thresholds["tool_selection"] == 0.99
    assert evaluator.thresholds["call_ordering"] == 1.0  # not in the file: the default
    assert not evaluate_trace(DEPLOY, looping).passed
    assert evaluate_trace(DEPLOY, looping, min_step_efficiency=0.0).passed


def test_judge_settings_from_the_file_and_the_environment(tmp_path, monkeypatch):
    write(tmp_path / "regshield.toml",
          'judge_model = "file-model"\njudge_base_url = "http://127.0.0.1:11434/v1"\njudge_timeout = 90\n')
    judge = LLMJudge(api_key="sk-test")
    assert (judge.model, judge.base_url, judge.timeout) == ("file-model", "http://127.0.0.1:11434/v1", 90.0)
    monkeypatch.setenv("JUDGE_MODEL", "env-model")
    monkeypatch.setenv("JUDGE_TIMEOUT", "120")
    judge = LLMJudge(api_key="sk-test")
    assert (judge.model, judge.timeout) == ("env-model", 120.0)
    assert LLMJudge(api_key="sk-test", model="arg-model", timeout=5).model == "arg-model"
    assert LLMJudge(api_key="sk-test", timeout=5).timeout == 5.0


def test_judge_timeout_reaches_the_http_client(monkeypatch):
    seen = []

    class Client:
        def __init__(self, timeout):
            seen.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "Client", Client)
    evaluate_trace(DEPLOY, GOOD, use_llm_judge=True, api_key="sk-test", judge_timeout=75, judge_on_error="pass")
    assert seen == [75.0]


def test_pricing_from_the_file(tmp_path):
    write(tmp_path / "regshield.toml", '[pricing.models]\n"qwen*" = { input = 0, output = 0 }\n'
                                       '[pricing.tools]\nweb_search = 0.005\n')
    trace = {"steps": [{"action": {"name": "web_search", "args": {}}, "observation": "ok"}],
             "llm_calls": [{"model": "qwen2.5-16k:3b", "input_tokens": 900, "output_tokens": 40}]}
    report = evaluate_trace({"scenario_id": "s", "max_cost_usd": 0.01}, trace)
    assert report.passed and report.cost["total_usd"] == 0.005 and report.cost["complete"]


@pytest.mark.parametrize("text, message", [
    ("min_tool_selecton = 0.9\n", "unknown setting"),
    ("api_key = 'sk-...'\n", "Keep API keys in environment variables"),
    ("min_tool_selection = 2\n", "from 0 to 1"),
    ("judge_timeout = 0\n", "judge_timeout must be"),
    ("judge_on_error = 'ignore'\n", "judge_on_error must be"),
    ("llm_judge = 'yes'\n", "llm_judge must be"),
    ("[pricing.models]\nx = { input = 1 }\n", "needs 'input' and 'output'"),
    ("min_tool_selection = \n", "not valid TOML"),
])
def test_bad_settings_are_rejected(tmp_path, text, message):
    write(tmp_path / "regshield.toml", text)
    with pytest.raises(ValueError, match=message):
        evaluate_trace(DEPLOY, GOOD)


# -- the CLI ----------------------------------------------------------------------------

def scenario_file(tmp_path, items):
    return write(tmp_path / "scenarios.json", json.dumps(items))


def test_cli_uses_the_config_file_and_flags_override_it(tmp_path, capsys):
    path = scenario_file(tmp_path, [{"scenario": DEPLOY, "trace": GOOD + [GOOD[1]]}])
    write(tmp_path / "regshield.toml", "min_step_efficiency = 0.0\n")
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 0
    assert main(["eval", path, "--report", str(tmp_path / "r.json"), "--min-step-efficiency", "0.7"]) == 1


def test_cli_bad_config_exits_with_code_2(tmp_path, capsys):
    path = scenario_file(tmp_path, [{"scenario": DEPLOY, "trace": GOOD}])
    write(tmp_path / "regshield.toml", "min_tool_selecton = 0.9\n")
    assert main(["eval", path]) == 2
    assert "unknown setting" in capsys.readouterr().err


def test_cli_repeated_runs_and_pass_rate(tmp_path, capsys):
    bad = [GOOD[0]]  # never deployed
    scenario = {**DEPLOY, "optimal_step_count": 2}
    path = scenario_file(tmp_path, [{"scenario": scenario, "traces": [GOOD, GOOD, bad, GOOD]}])
    report = str(tmp_path / "r.json")
    assert main(["eval", path, "--report", report]) == 1
    out = capsys.readouterr().out
    assert "FAIL  deploy_gate  (3/4 runs passed, required 100%)" in out
    assert "      - Tool selection in 1/4 runs" in out
    saved = [r["scenario_id"] for r in json.loads(open(report).read())["results"]]
    assert saved == [f"deploy_gate [run {n}/4]" for n in range(1, 5)]
    assert main(["eval", path, "--report", report, "--min-pass-rate", "0.75"]) == 0
    assert "PASS  deploy_gate  (3/4 runs passed)" in capsys.readouterr().out


def test_cli_rejects_both_trace_and_traces(tmp_path, capsys):
    path = scenario_file(tmp_path, [{"scenario": DEPLOY, "trace": GOOD, "traces": [GOOD]}])
    assert main(["eval", path]) == 2
    assert "both 'trace' and 'traces'" in capsys.readouterr().err


def test_cli_prints_the_cost_of_recorded_runs(tmp_path, capsys):
    trace = {"steps": GOOD, "llm_calls": [{"model": "gpt-4o", "input_tokens": 12_000, "output_tokens": 800},
                                          {"model": "my-local-model", "input_tokens": 100, "output_tokens": 10}]}
    path = scenario_file(tmp_path, [{"scenario": {**DEPLOY, "optimal_step_count": 2}, "trace": trace}])
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 0
    assert ("Cost of the recorded runs: $0.0380 (2 LLM calls, 12,910 tokens); no price for 'my-local-model'"
            in capsys.readouterr().out)


def test_cli_no_llm_judge_overrides_the_config_file(tmp_path, capsys):
    path = scenario_file(tmp_path, [{"scenario": DEPLOY, "trace": GOOD}])
    write(tmp_path / "regshield.toml", "llm_judge = true\nmin_step_efficiency = 0\n")
    assert main(["eval", path]) == 2  # the file turns the judge on, and there's no key
    assert "needs an API key" in capsys.readouterr().err
    assert main(["eval", path, "--no-llm-judge", "--report", str(tmp_path / "r.json")]) == 0
