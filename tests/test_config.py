"""Project settings ([tool.regshield] / regshield.toml) and the CLI features that use them."""

import json
import os

import httpx
import pytest

from regression_shield import AgentTraceEvaluator, LLMJudge, evaluate_trace
from regression_shield.cli import main
from regression_shield.config import find_config_file, load_config, load_env_file

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


# -- every setting from the environment ---------------------------------------------------

@pytest.mark.parametrize("variable, value, name, expected", [
    ("REGSHIELD_MIN_TOOL_SELECTION", "0.9", "min_tool_selection", 0.9),
    ("REGSHIELD_LLM_JUDGE", "yes", "llm_judge", True),
    ("REGSHIELD_JUDGE_ON_ERROR", "pass", "judge_on_error", "pass"),
    ("REGSHIELD_JUDGE_MODEL", "qwen2.5:7b", "judge_model", "qwen2.5:7b"),
    ("JUDGE_MODEL", "qwen2.5:7b", "judge_model", "qwen2.5:7b"),        # the older name still works
    ("REGSHIELD_EXPORT_MAX_RUNS_PER_MINUTE", "600", "export_max_runs_per_minute", 600),
    ("REGSHIELD_EXPORT_CAPTURE_CONTENT", "false", "export_capture_content", False),
    ("REGSHIELD_LOG", "1", "log_level", "debug"),                      # REGSHIELD_LOG=1 has meant debug
])
def test_every_setting_has_an_environment_variable(monkeypatch, variable, value, name, expected):
    from regression_shield.config import setting

    monkeypatch.setenv(variable, value)
    assert setting(name) == expected


@pytest.mark.parametrize("variable, value, message", [
    ("REGSHIELD_MIN_TOOL_SELECTION", "high", "must be a number"),
    ("REGSHIELD_MIN_TOOL_SELECTION", "1.5", "from 0 to 1"),
    ("REGSHIELD_LLM_JUDGE", "maybe", "use true or false"),
    ("REGSHIELD_JUDGE_ON_ERROR", "retry", '"fail" or "pass"'),
    ("REGSHIELD_PRICING", "{}", "only be set in the config file"),
])
def test_bad_environment_values_name_the_variable(monkeypatch, variable, value, message):
    from regression_shield.config import setting

    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=message) as error:
        setting(variable.removeprefix("REGSHIELD_").lower())
    assert variable in str(error.value)


def test_arguments_beat_the_environment_which_beats_the_file(tmp_path, monkeypatch):
    from regression_shield.config import setting

    write(tmp_path / "regshield.toml", "min_tool_selection = 0.5\n")
    assert setting("min_tool_selection") == 0.5
    monkeypatch.setenv("REGSHIELD_MIN_TOOL_SELECTION", "0.7")
    assert setting("min_tool_selection") == 0.7
    assert setting("min_tool_selection", 0.9) == 0.9
    assert AgentTraceEvaluator().thresholds["tool_selection"] == 0.7


# -- keys in a .env file the config names ---------------------------------------------------

def test_env_file_holds_the_keys(tmp_path, monkeypatch):
    write(tmp_path / ".env", "# keys\nexport OPENROUTER_API_KEY=sk-or-from-file\nOPENAI_API_KEY='sk-oa'\n"
                             'REGSHIELD_JUDGE_MODEL="qwen2.5:7b"  \nEMPTY=\nWITH_COMMENT=value # note\n')
    write(tmp_path / "regshield.toml", 'env_file = ".env"\n')
    monkeypatch.setenv("OPENAI_API_KEY", "sk-already-set")  # the real environment wins
    judge = LLMJudge()
    assert (judge.api_key, judge.model) == ("sk-or-from-file", "qwen2.5:7b")
    assert os.environ["OPENAI_API_KEY"] == "sk-already-set"
    assert os.environ["WITH_COMMENT"] == "value" and "EMPTY" not in os.environ


def test_editing_the_env_file_takes_effect(tmp_path):
    from regression_shield.config import setting

    env = tmp_path / ".env"
    write(env, "REGSHIELD_JUDGE_MODEL=first\n")
    write(tmp_path / "regshield.toml", 'env_file = ".env"\n')
    assert setting("judge_model") == "first"
    write(env, "REGSHIELD_JUDGE_MODEL=second\n")
    os.utime(env, (os.path.getatime(env), os.path.getmtime(env) + 5))
    assert setting("judge_model") == "second"


def test_env_file_without_a_config_file(tmp_path, monkeypatch):
    write(tmp_path / "secrets.env", "OPENROUTER_API_KEY=sk-or-x\n")
    monkeypatch.setenv("REGSHIELD_ENV_FILE", str(tmp_path / "secrets.env"))
    assert LLMJudge().api_key == "sk-or-x"


def test_a_broken_env_file_is_reported(tmp_path):
    write(tmp_path / ".env", "this is not a variable\n")
    write(tmp_path / "regshield.toml", 'env_file = ".env"\n')
    with pytest.raises(ValueError, match=r"\.env, line 1: expected NAME=value"):
        load_config()


@pytest.mark.parametrize("text", ['openrouter_api_key = "sk-or-123"\n', 'export_http_headers = "Authorization=x"\n'])
def test_secrets_are_refused_in_the_config_file(tmp_path, text):
    write(tmp_path / "regshield.toml", text)
    with pytest.raises(ValueError, match="Keep API keys in environment variables or an env_file"):
        load_config()


def test_a_missing_env_file_is_skipped(tmp_path, monkeypatch):
    """The same config works in CI, where keys come from the environment and there's no .env."""
    write(tmp_path / "regshield.toml", 'env_file = ".env"\njudge_model = "qwen2.5:7b"\n')
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-ci")
    assert LLMJudge().api_key == "sk-or-from-ci"


def test_paths_in_the_config_file_are_relative_to_it(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    write(project / "regshield.toml", 'price_list = "prices.json"\nexport_jsonl_path = "runs/out.jsonl"\n')
    monkeypatch.chdir(project / "src")
    settings = load_config()
    assert settings["price_list"] == str(project / "prices.json")
    assert settings["export_jsonl_path"] == str(project / "runs" / "out.jsonl")


# -- export and logs from the settings ------------------------------------------------------

def test_export_traces_without_arguments_uses_the_settings(tmp_path):
    from regression_shield import TraceRecorder, export_traces, stop_exporting

    write(tmp_path / "regshield.toml", 'export_jsonl_path = "runs.jsonl"\nexport_capture_content = true\n')
    export_traces()
    recorder = TraceRecorder()
    recorder.tool_call("lookup", {"id": 1}, "found")
    recorder.end_run()
    stop_exporting()
    events = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["run_start", "tool_call", "run_end"]
    assert events[1]["content"]["args"] == {"id": 1}


def test_log_level_from_the_settings(tmp_path):
    import logging

    write(tmp_path / "regshield.toml", 'log_level = "info"\n')
    AgentTraceEvaluator()
    logger = logging.getLogger("regression_shield")
    assert logger.level == logging.INFO
    logger.setLevel(logging.NOTSET)
    logger.handlers = [h for h in logger.handlers if not getattr(h, "_regshield", False)]


# -- regshield config init / show -----------------------------------------------------------

def test_config_init_writes_every_setting_and_an_env_example(tmp_path, capsys):
    from regression_shield.config import SETTINGS

    assert main(["config", "init"]) == 0
    template = (tmp_path / "regshield.toml").read_text(encoding="utf-8")
    assert all(f"# {name} = " in template or f"[{name}." in template for name in SETTINGS)
    assert "OPENROUTER_API_KEY=" in (tmp_path / ".env.example").read_text(encoding="utf-8")
    assert "Add .env to .gitignore" in capsys.readouterr().out
    assert load_config() == {}  # everything is commented out: the defaults apply
    # Uncommenting every setting gives a valid file
    uncommented = "\n".join(line[2:] if line.startswith("# ") and " = " in line and not line.startswith("# --")
                            else line for line in template.splitlines())
    write(tmp_path / "regshield.toml", uncommented.replace("# [pricing", "[pricing"))
    assert set(load_config()) == set(SETTINGS)
    assert main(["config", "init"]) == 0  # existing files are kept
    assert "already exists" in capsys.readouterr().out


def rewrite_within_the_same_tick(path, text):
    """Rewrite a file keeping its modification time, as two quick writes can on Linux,
    where the timestamp only moves every few milliseconds."""
    before = os.stat(path)
    write(path, text)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_a_quick_rewrite_of_the_same_size_is_still_seen(tmp_path):
    config_file = write(tmp_path / "regshield.toml", "min_tool_selection = 0.91\n")
    assert load_config(config_file)["min_tool_selection"] == 0.91
    rewrite_within_the_same_tick(tmp_path / "regshield.toml", "min_tool_selection = 0.92\n")
    assert load_config(config_file)["min_tool_selection"] == 0.92

    env_file = write(tmp_path / ".env", "REGSHIELD_JUDGE_TIMEOUT=91\n")
    load_env_file(env_file)
    assert os.environ["REGSHIELD_JUDGE_TIMEOUT"] == "91"
    rewrite_within_the_same_tick(tmp_path / ".env", "REGSHIELD_JUDGE_TIMEOUT=92\n")
    assert load_env_file(env_file) == {"REGSHIELD_JUDGE_TIMEOUT": "92"}


def test_config_show_says_where_each_setting_comes_from(tmp_path, monkeypatch, capsys):
    write(tmp_path / ".env", "OPENROUTER_API_KEY=sk-or-x\nREGSHIELD_JUDGE_TIMEOUT=90\n")
    write(tmp_path / "regshield.toml", 'env_file = ".env"\njudge_model = "qwen2.5:7b"\n'
                                       'judge_base_url = "http://localhost:11434/v1"\n')
    monkeypatch.setenv("REGSHIELD_MIN_TOOL_SELECTION", "0.95")
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  ")}
    assert lines["judge_model"].split()[1:] == ["qwen2.5:7b", "regshield.toml"]
    assert lines["min_tool_selection"].split()[1:] == ["0.95", "REGSHIELD_MIN_TOOL_SELECTION"]
    assert lines["judge_timeout"].split()[1:] == ["90.0", "REGSHIELD_JUDGE_TIMEOUT", "(from", ".env)"]
    assert lines["min_call_ordering"].split()[1:] == ["1.0", "default"]
    assert lines["OPENROUTER_API_KEY"].split()[1:] == ["set", "(from", ".env)"]
    assert "sk-or-x" not in out  # key values are never printed
    assert "LLM judge would use: qwen2.5:7b at http://localhost:11434/v1 (your own server, no key needed)" in out
