"""LLM judge: verdicts, and failing closed when no verdict can be obtained."""

import json

import httpx
import pytest

from regression_shield import LLMJudge, evaluate_trace
from regression_shield.cli import main

SCENARIO = {"scenario_id": "JUDGE_01", "expected_tools": ["lookup"]}
TRACE = [{"thought": "Looking it up.", "action": {"name": "lookup", "args": {}}, "observation": "found"}]


class FakeResponse:
    def __init__(self, status_code=200, content=None, text=""):
        self.status_code = status_code
        self._content = content
        self.text = text

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Never use a real key from the environment or reach a real endpoint."""
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_BASE_URL", "JUDGE_MODEL"):
        monkeypatch.delenv(var, raising=False)

    def no_network(self, *args, **kwargs):
        raise AssertionError("test attempted a real network call")

    monkeypatch.setattr(httpx.Client, "post", no_network)


def reply_with(monkeypatch, response=None, error=None):
    def fake_post(self, url, **kwargs):
        if error:
            raise error
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)


@pytest.mark.parametrize("response, error, expected", [
    (FakeResponse(429, text="rate limited"), None, "HTTP 429"),
    (FakeResponse(200, content="not json"), None, "JSONDecodeError"),
    (FakeResponse(200, content='{"reasoning": "fine"}'), None, "no 'score'"),
    (None, httpx.ConnectError("connection refused"), "ConnectError"),
])
def test_judge_without_verdict_never_passes(monkeypatch, response, error, expected):
    reply_with(monkeypatch, response, error)
    audit = LLMJudge(api_key="sk-test").verify_reasoning_and_outcome("goal", TRACE, "done")
    assert audit["passed"] is False
    assert audit["score"] is None
    assert expected in audit["error"]


def test_judge_without_key_never_passes():
    audit = LLMJudge().verify_reasoning_and_outcome("goal", TRACE, "done")
    assert audit["passed"] is False
    assert "no API key" in audit["error"]


def test_judge_error_fails_trace_by_default(monkeypatch):
    reply_with(monkeypatch, FakeResponse(429))
    report = evaluate_trace(scenario=SCENARIO, trace=TRACE, api_key="sk-test", use_llm_judge=True)
    assert report.passed is False
    assert any("could not run" in f for f in report.failures)


def test_judge_error_can_be_ignored(monkeypatch):
    reply_with(monkeypatch, FakeResponse(429))
    report = evaluate_trace(scenario=SCENARIO, trace=TRACE, api_key="sk-test", use_llm_judge=True,
                            judge_on_error="pass")
    assert report.passed is True
    assert "HTTP 429" in report.judge_audit["error"]


def test_low_judge_score_fails_trace(monkeypatch):
    reply_with(monkeypatch, FakeResponse(200, content='{"score": 0.1, "reasoning": "Claimed $500, tool refunded $50."}'))
    report = evaluate_trace(scenario=SCENARIO, trace=TRACE, api_key="sk-test", use_llm_judge=True)
    assert report.passed is False
    assert any("Claimed $500" in f for f in report.failures)


def test_judge_enabled_without_key_raises():
    with pytest.raises(ValueError, match="needs an API key"):
        evaluate_trace(scenario=SCENARIO, trace=TRACE, use_llm_judge=True)


def test_judge_uses_key_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    seen = []

    def fake_post(self, url, **kwargs):
        seen.append(kwargs["headers"]["Authorization"])
        return FakeResponse(200, content='{"score": 0.9, "reasoning": "Grounded."}')

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    report = evaluate_trace(scenario=SCENARIO, trace=TRACE, use_llm_judge=True)
    assert report.passed is True
    assert seen == ["Bearer sk-from-env"]


@pytest.mark.parametrize("env, expected", [
    ({"OPENROUTER_API_KEY": "sk-or"}, ("sk-or", LLMJudge.DEFAULT_BASE_URL, LLMJudge.DEFAULT_MODEL)),
    ({"OPENAI_API_KEY": "sk-oa"}, ("sk-oa", LLMJudge.OPENAI_BASE_URL, LLMJudge.OPENAI_MODEL)),
    ({"OPENROUTER_API_KEY": "sk-or", "OPENAI_API_KEY": "sk-oa"}, ("sk-or", LLMJudge.DEFAULT_BASE_URL, LLMJudge.DEFAULT_MODEL)),
    ({"OPENAI_API_KEY": "ollama", "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1/", "JUDGE_MODEL": "qwen2.5:3b"},
     ("ollama", "http://127.0.0.1:11434/v1", "qwen2.5:3b")),
])
def test_each_key_goes_to_its_own_provider(monkeypatch, env, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    judge = LLMJudge()
    assert (judge.api_key, judge.base_url, judge.model) == expected


@pytest.mark.parametrize("base_url", ["https://api.deepseek.com", "http://127.0.0.1:11434/v1/"])
def test_request_goes_to_base_url_chat_completions(monkeypatch, base_url):
    seen = []

    def fake_post(self, url, **kwargs):
        seen.append(url)
        return FakeResponse(200, content='{"score": 1.0, "reasoning": "ok"}')

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMJudge(api_key="sk-test", base_url=base_url).verify_reasoning_and_outcome("goal", TRACE, "done")
    assert seen == [base_url.rstrip("/") + "/chat/completions"]


def test_prompt_shows_pattern_events(monkeypatch):
    prompts = []

    def fake_post(self, url, **kwargs):
        prompts.append(kwargs["json"]["messages"][1]["content"])
        return FakeResponse(200, content='{"score": 0.0, "reasoning": "Refund was denied."}')

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    trace = [
        {"action": {"type": "handoff", "to": "billing"}, "agent": "triage"},
        {"action": {"type": "approval", "tool": "refund", "approved": False}},
    ]
    LLMJudge(api_key="sk-test").verify_reasoning_and_outcome("Refund A-1", trace, "Refund issued.")
    assert 'Step 1 (triage):\n  Event: handoff {"to": "billing"}' in prompts[0]
    assert 'Event: approval {"tool": "refund", "approved": false}' in prompts[0]


def test_invalid_judge_on_error_is_rejected():
    with pytest.raises(ValueError, match="judge_on_error"):
        evaluate_trace(scenario=SCENARIO, trace=TRACE, judge_on_error="maybe")


def test_diagnostics_show_judge_error(monkeypatch, capsys):
    reply_with(monkeypatch, FakeResponse(429))
    report = evaluate_trace(scenario=SCENARIO, trace=TRACE, api_key="sk-test", use_llm_judge=True,
                            judge_on_error="pass")
    print(report.format())
    assert "LLM judge (minimax/minimax-m2.7:free): n/a" in capsys.readouterr().out


def write_scenarios(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps([{"scenario": SCENARIO, "trace": TRACE}]), encoding="utf-8")
    return str(path)


def test_cli_judge_without_key_exits_with_error(tmp_path, capsys):
    assert main(["eval", write_scenarios(tmp_path), "--llm-judge"]) == 2
    assert "needs an API key" in capsys.readouterr().err


def test_cli_judge_error_fails_the_gate(tmp_path, monkeypatch, capsys):
    reply_with(monkeypatch, FakeResponse(429))
    code = main(["eval", write_scenarios(tmp_path), "--llm-judge", "--api-key", "sk-test",
                 "--report", str(tmp_path / "r.json")])
    assert code == 1
    out = capsys.readouterr().out
    assert "LLM judge (minimax/minimax-m2.7:free): n/a" in out
    assert "could not run" in out
