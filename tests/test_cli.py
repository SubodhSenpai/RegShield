"""The regshield command line and logging."""

import json
import logging
import subprocess
import sys

import pytest

from regression_shield import enable_logging, evaluate_trace
from regression_shield.cli import main

GOOD = [{"action": {"name": "test", "args": {}}, "observation": "ok"},
        {"action": {"name": "deploy", "args": {}}, "observation": "ok"}]
SCENARIO = {"scenario_id": "gate", "expected_tools": ["test", "deploy"], "expected_order": ["test", "deploy"]}


def write(tmp_path, items, name="scenarios.json"):
    path = tmp_path / name
    path.write_text(json.dumps(items), encoding="utf-8")
    return str(path)


def test_eval_passes_with_exit_code_0(tmp_path, capsys):
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": GOOD}])
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "PASS  gate" in out and "1/1 scenario(s) passed." in out
    assert json.loads((tmp_path / "r.json").read_text())["results"][0]["status"] == "PASSED"


def test_eval_fails_with_exit_code_1(tmp_path, capsys):
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": list(reversed(GOOD))}])
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 1
    assert "- Call ordering 0.00 < 1.00: 'deploy' (step 1) ran before its prerequisite 'test' (step 2)" in \
        capsys.readouterr().out


@pytest.mark.parametrize("items, message", [
    ([{"scenario": SCENARIO}], "item 1 is missing ['trace']"),
    ([{"scenario": {**SCENARIO, "expected_tool": ["x"]}, "trace": GOOD}], "Unknown scenario field(s) ['expected_tool']"),
])
def test_bad_files_exit_with_code_2_and_a_clear_error(tmp_path, capsys, items, message):
    assert main(["eval", write(tmp_path, items), "--report", str(tmp_path / "r.json")]) == 2
    assert message in capsys.readouterr().err


def test_missing_file_exits_with_code_2(tmp_path, capsys):
    assert main(["eval", str(tmp_path / "nope.json")]) == 2
    assert "error:" in capsys.readouterr().err


def test_thresholds_are_flags(tmp_path):
    looping = GOOD + GOOD[1:] * 2
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": looping}])
    report = str(tmp_path / "r.json")
    assert main(["eval", path, "--report", report]) == 1
    assert main(["eval", path, "--report", report, "--min-step-efficiency", "0"]) == 0


def test_regression_traces_are_saved_for_the_dashboard(tmp_path, capsys):
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": GOOD, "regression_trace": list(reversed(GOOD))}])
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 0
    assert "Regressed traces caught: 1/1." in capsys.readouterr().out
    saved = json.loads((tmp_path / "r.json").read_text())
    assert [r["status"] for r in saved["regression_results"]] == ["FAILED"]


def test_a_regression_trace_that_passes_fails_the_run(tmp_path, capsys):
    # The "regressed" trace only swaps an argument the scenario doesn't check
    regressed = [GOOD[0], {"action": {"name": "deploy", "args": {"env": "prod"}}, "observation": "ok"}]
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": GOOD, "regression_trace": regressed}])
    assert main(["eval", path, "--report", str(tmp_path / "r.json")]) == 1
    out = capsys.readouterr().out
    assert "MISS  gate  its regression_trace passed" in out and "Regressed traces caught: 0/1." in out


def test_routing_accuracy_is_reported(tmp_path, capsys):
    items = [{"scenario": {"scenario_id": f"R{i}", "expected_route": "billing"},
              "trace": [{"action": {"type": "route", "to": to}}]} for i, to in enumerate(["billing", "billing", "tech"])]
    main(["eval", write(tmp_path, items), "--report", str(tmp_path / "r.json")])
    assert "Routing accuracy: 2/3 (67%)." in capsys.readouterr().out


def test_demo_evaluates_the_bundled_samples(tmp_path, capsys):
    assert main(["demo", "--report", str(tmp_path / "r.json")]) == 0
    assert "10/10 scenario(s) passed. Regressed traces caught: 10/10." in capsys.readouterr().out
    saved = json.loads((tmp_path / "r.json").read_text())
    assert len(saved["results"]) == len(saved["regression_results"]) == 10


def test_llm_judge_without_a_key_exits_with_code_2(tmp_path, capsys, monkeypatch):
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert main(["eval", write(tmp_path, [{"scenario": SCENARIO, "trace": GOOD}]), "--llm-judge"]) == 2
    assert "needs an API key" in capsys.readouterr().err


@pytest.mark.parametrize("flag, expect_logs", [("--verbose", True), ("-v", True), (None, False)])
def test_verbose_flag(tmp_path, flag, expect_logs):
    path = write(tmp_path, [{"scenario": SCENARIO, "trace": GOOD}])
    command = [sys.executable, "-m", "regression_shield.cli", "eval", path, "--report", str(tmp_path / "r.json")]
    result = subprocess.run(command + ([flag] if flag else []), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert ("[regshield] DEBUG" in result.stderr) is expect_logs
    assert "1/1 scenario(s) passed." in result.stdout  # logs never mix into stdout


def test_version_flag(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "regshield 0.4.0" in capsys.readouterr().out


@pytest.fixture
def restore_logging():
    logger = logging.getLogger("regression_shield")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


def test_verbose_evaluate_trace_logs_metrics_and_patterns(restore_logging, capsys):
    evaluate_trace({**SCENARIO, "forbidden_tools": ["drop"]}, GOOD, verbose=True)
    err = capsys.readouterr().err
    assert "[regshield] DEBUG   evaluator: Evaluating 'gate'" in err
    assert "pattern policy" in err and "'gate' PASSED" in err


def test_quiet_by_default(restore_logging, capsys):
    logging.getLogger("regression_shield").setLevel(logging.WARNING)
    evaluate_trace(SCENARIO, GOOD)
    assert "[regshield]" not in capsys.readouterr().err


def test_enable_logging_is_idempotent(restore_logging):
    enable_logging("INFO")
    enable_logging("DEBUG")
    ours = [h for h in logging.getLogger("regression_shield").handlers if getattr(h, "_regshield", False)]
    assert len(ours) == 1
