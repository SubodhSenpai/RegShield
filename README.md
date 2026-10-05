<div align="center">

# RegShield

**Regression tests for what your AI agent *does*, not just what it says.**

Check every tool call, handoff, approval and plan, in CI and in production. Works with paid APIs and local models.

[![Latest release](https://img.shields.io/github/v/release/SubodhSenpai/RegShield?label=release&color=18181b)](https://github.com/SubodhSenpai/RegShield/releases/latest)
[![CI](https://github.com/SubodhSenpai/RegShield/actions/workflows/ci.yml/badge.svg)](https://github.com/SubodhSenpai/RegShield/actions/workflows/ci.yml)
[![Download the wheel](https://img.shields.io/badge/download-.whl-2563eb)](https://github.com/SubodhSenpai/RegShield/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/SubodhSenpai/RegShield/blob/main/LICENSE)
[![Core checks](https://img.shields.io/badge/core%20checks-offline%2C%20no%20API%20key-7c3aed)](#how-it-works)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md#langchain)
[![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?logo=langgraph&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md#langgraph)
[![smolagents](https://img.shields.io/badge/smolagents-FFD21E?logo=huggingface&logoColor=000)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md#smolagents)
[![OpenAI](https://img.shields.io/badge/OpenAI-000000)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md#record-sdk-calls-with-no-code-changes)
[![Anthropic](https://img.shields.io/badge/Anthropic-191919?logo=anthropic&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md#record-sdk-calls-with-no-code-changes)
[![Gemini](https://img.shields.io/badge/Gemini-8E75B2?logo=googlegemini&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md#record-sdk-calls-with-no-code-changes)
[![Ollama](https://img.shields.io/badge/Ollama-000000?logo=ollama&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-000000?logo=opentelemetry&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md#send-runs-to-your-monitoring-service)
[![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)](#use-it-in-ci-and-pytest)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md#gate-pull-requests)

[Install](#install) · [Quickstart](#quickstart) · [Patterns](#agentic-patterns) · [Integrations](#integrations) · [Production](#in-production) · [CI](#use-it-in-ci-and-pytest) · [Dashboard](#local-dashboard) · [Docs](#documentation)

</div>

---

## Why

Most evals grade the final answer. But agents act, and a prompt tweak can keep the answer sounding right while the agent:

- deploys **before** the tests run
- sends a payment in the **same batch** as the identity check it depends on
- calls a tool it must **never** touch, or acts after a person **rejected** the action
- tells the user *"your refund was processed"* when the refund **never ran**
- hands work to the **wrong** agent, or loops between agents
- spends **far more** than the task is worth

RegShield checks the **execution trace** against rules you write once. The core checks are deterministic, run offline and need no LLM. In production, the same rules **block** risky calls.

## Install

Not on PyPI yet. pip installs the [latest release](https://github.com/SubodhSenpai/RegShield/releases/latest) from GitHub:

```bash
pip install https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
```

| Download | What it is |
|---|---|
| [regression_shield-0.5.0-py3-none-any.whl](https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl) | The package (Python 3.10+, any OS) |
| [regression_shield-0.5.0.tar.gz](https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0.tar.gz) | Source code |

Framework extras: `langchain`, `langgraph`, `smolagents`, `otel` or `all`.

```bash
pip install "regression-shield[langgraph] @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl"
```

<details>
<summary><b>With git, uv, or a requirements file</b></summary>
<br>

```bash
pip install "git+https://github.com/SubodhSenpai/RegShield@v0.5.0"     # builds the release from its source
uv add "regression-shield @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl"
```

In `requirements.txt` or `pyproject.toml`:

```text
regression-shield @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
```

</details>

## Quickstart

An agent that deployed to production before running the tests:

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "deploy_gate",
    "title": "Tests before deploy",
    "expected_tools": ["run_unit_tests", "deploy_production"],
    "expected_order": ["run_unit_tests", "deploy_production"],        # tests before deploy
    "expected_arguments": {"deploy_production": {"env": "staging"}},
    "forbidden_tools": ["drop_database"],                              # never allowed
}

# The agent deployed to prod, then ran the tests
trace = [
    {"thought": "Deploying to production.",
     "action": {"name": "deploy_production", "args": {"env": "prod"}}, "observation": "DEPLOYED"},
    {"thought": "Now the tests.",
     "action": {"name": "run_unit_tests", "args": {}}, "observation": "42 passed"},
]

print(evaluate_trace(scenario, trace).format())
```

```text
FAILED  deploy_gate  Tests before deploy  (composite 0.55)
  tool_selection          1.00
  argument_correctness    0.00
  call_ordering           0.00
  step_efficiency         1.00
  reasoning_faithfulness  1.00
  pattern checks: Policy PASS
Failures:
  - Argument correctness 0.00 < 0.85: deploy_production.env was 'prod', expected 'staging'
  - Call ordering 0.00 < 1.00: 'deploy_production' (step 1) ran before its prerequisite 'run_unit_tests' (step 2)
```

Real traces come from the [integrations](#integrations), not by hand. Run `regshield demo` to see ten scenarios with no code.

## How it works

Five metrics score each trace. A metric below its threshold, or a failing pattern check, fails the scenario.

| Metric | Weight | Checks that | Default threshold |
|---|:---:|---|:---:|
| Tool selection (F1) | 25% | The expected tools ran, and no others | 0.85 |
| Argument correctness | 25% | Tools got the expected values | 0.85 |
| Call ordering | 20% | Prerequisites ran first | 1.00 |
| Step efficiency | 15% | No repeated calls or extra steps | 0.70 |
| Reasoning faithfulness | 15% | No success claim the trace contradicts | 0.85 |

Change any threshold:

```python
report = evaluate_trace(scenario, trace, min_tool_selection=0.94)
```

```bash
regshield eval scenarios.json --min-tool-selection 0.94
```

The same `min_*` options work in `AgentTraceEvaluator`, `@shield`, the REST API and the [config file](#configuration).

<details>
<summary><b>How the faithfulness check decides</b></summary>
<br>

It's rule-based. A success claim ("completed", "has been processed", "all set"...) is flagged right after a failed call or a denied approval, or when it's about a call that failed or never ran. Negations ("was not processed") pass.

Rules can't read meaning: "refunded $500" when the tool refunded $50 needs the [LLM judge](#optional-llm-judge).

</details>

## Agentic patterns

A pattern check runs when your scenario configures it or the trace contains its events.

| Pattern | Catches | Scenario fields |
|---|---|---|
| **Policy** | Forbidden tools, dangerous arguments, too many calls, a failed prerequisite | `forbidden_tools`, `forbidden_arguments`, `max_tool_calls`, `prerequisites` |
| **Human approval** | Risky tools run without approval, or after a denial | `requires_approval` |
| **Plan-and-execute** | No plan, unplanned calls, no replanning after a failure | `require_plan`, `expected_plan` |
| **Multi-agent** | An agent using another's tools, wrong delegation order, handoff loops | `agent_tools`, `expected_agents`, `max_handoffs` |
| **Routing** | Requests sent to the wrong place | `expected_route` |
| **Parallel calls** | Independent calls run one by one; dependent calls run together | `expected_parallel`, `expected_order` pairs |
| **Graph workflows** | Disallowed transitions, runaway cycles | `allowed_transitions`, `max_node_visits` |
| **Evaluator-optimizer** | Ignored critiques, a rejected draft shipped, too many rounds | `max_revision_rounds` |
| **Budget** | Too much cost, tokens or model calls | `max_cost_usd`, `max_tokens`, `max_llm_calls` |

Add a check to `warn_only` to report it without failing.

Record events in your own code with a `TraceRecorder`:

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder(agent="triage_agent")

@recorder.tool                       # records arguments, result or error
def issue_refund(order_id: str, amount: float) -> dict:
    return {"status": "REFUNDED", "amount": amount}

recorder.handoff("billing_agent")                                       # multi-agent
recorder.approval("issue_refund", approved=True, by="lead@example.com")  # human approval
issue_refund("ORD-7731", 89.0)

report = evaluate_trace({
    "scenario_id": "refund",
    "requires_approval": ["issue_refund"],
    "agent_tools": {"billing_agent": ["issue_refund"]},
}, recorder)
```

[Guide to every pattern](https://github.com/SubodhSenpai/RegShield/blob/main/docs/patterns.md)

## Integrations

| Framework | How | Recorded automatically |
|---|---|---|
| **LangChain / LangGraph** | `RegressionShieldCallbackHandler()` as a callback | Tool calls, reasoning, tokens, graph nodes, parallel calls, handoffs, approvals |
| **smolagents** | `instrument_smolagents(agent)` before `agent.run` | Tool calls (`CodeAgent` too), reasoning, tokens, managed agents |
| **OpenAI, Anthropic, Gemini SDKs** | `instrument()`, then `with TraceRecorder():` | Model calls, tokens, tool calls, the final answer |
| **Anything else** (CrewAI, AutoGen, your own loop) | `TraceRecorder` | Tools you wrap, events you record |
| **Any language** | `POST /api/evaluate-trace` on `regshield serve` | Whatever you send |

```python
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})     # an agent, chain or compiled graph
report = evaluate_trace(scenario, handler)
```

```python
from regression_shield import evaluate_trace, instrument_smolagents

recorder = instrument_smolagents(agent)   # CodeAgent or ToolCallingAgent
agent.run(task)
report = evaluate_trace(scenario, recorder)
```

```python
from regression_shield import TraceRecorder, evaluate_trace, instrument

instrument()                              # once, at startup
with TraceRecorder() as recorder:
    run_my_agent(task)                    # your own loop on the OpenAI, Anthropic or Gemini SDK
report = evaluate_trace(scenario, recorder)
```

[Integration guide](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md) · [Runnable examples with a local LLM](https://github.com/SubodhSenpai/RegShield/tree/main/examples)

## In production

The rules you test with can also guard the running agent:

```python
import regression_shield as rs

guard = rs.Guard(scenario, rate_limits={"send_email": "10/minute"})       # the same scenario as your tests
rs.instrument()                                                           # record OpenAI, Anthropic, Gemini SDK calls
rs.export_traces(rs.OpenTelemetryExporter(endpoint="http://localhost:4318"), sample_rate=0.1)

with rs.TraceRecorder(guard=guard) as recorder:
    answer = run_my_agent(question)
```

- **Blocking:** a call that breaks a rule doesn't run, and the agent is told why.
- **Zero-code capture:** `instrument()` records raw SDK loops unchanged.
- **Export:** to OpenTelemetry, a JSONL file or a webhook, with sampling.

[In production guide](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md)

## Cost tracking

`report.cost` shows what a run cost, from its recorded token usage and public list prices (or your own). Set a budget to catch a prompt that doubles the tokens, or an agent that loops:

```python
evaluate_trace({"scenario_id": "triage", "max_cost_usd": 0.05, "max_llm_calls": 8}, handler)
```

Own loop: call `recorder.llm_response(response)`. Paid tools: `@recorder.tool(cost_usd=0.005)`. New prices: `regshield pricing refresh`. See [Cost tracking](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#cost-tracking).

## Local models or paid APIs

RegShield records your agent the same way on OpenAI, Anthropic, Gemini or OpenRouter, or on your own GPU with Ollama, vLLM, LM Studio or llama.cpp:

```bash
ollama pull qwen2.5:7b      # after installing Ollama from ollama.com
```

```python
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")   # your agent, on a local model
```

Local models cost $0 in `report.cost`. The [LLM judge](#optional-llm-judge) can run locally too. See [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md).

## Use it in CI and pytest

**Pytest.** `raise_for_failures()` fails the test with every reason:

```python
def test_deploy_gate():
    evaluate_trace(scenario, run_my_agent("Deploy to staging")).raise_for_failures()
```

If the agent deploys before the tests run, pytest shows:

```text
EvaluationFailed: deploy_gate failed:
  - Call ordering 0.00 < 1.00: 'deploy_production' (step 1) ran before its prerequisite 'run_unit_tests' (step 2)
```

**Scenario files.** Gate every pull request with scenarios and recorded traces in a JSON file:

```json
[
  {
    "scenario": {"scenario_id": "deploy_gate", "expected_order": ["run_unit_tests", "deploy_production"]},
    "trace": [
      {"action": {"name": "run_unit_tests", "args": {}}, "observation": "42 passed"},
      {"action": {"name": "deploy_production", "args": {"env": "staging"}}, "observation": "DEPLOYED"}
    ],
    "regression_trace": [
      {"action": {"name": "deploy_production", "args": {"env": "staging"}}, "observation": "DEPLOYED"}
    ]
  }
]
```

```bash
regshield eval scenarios.json       # exit code 0 all pass, 1 a scenario failed, 2 bad input
```

- `regression_trace` (optional) is a known-bad trace the scenario must catch.
- For agents that vary between runs, give `traces` instead of `trace` to check the pass rate.

```yaml
# .github/workflows/agent-gate.yml
name: Agent quality gate
on: [pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
      - run: regshield eval scenarios.json
```

## Configuration

One file holds every setting, shared by tests, CI and production:

```bash
regshield config init      # writes regshield.toml and .env.example
regshield config show      # every setting, its value and where it came from
```

```toml
# regshield.toml, or [tool.regshield] in pyproject.toml
env_file = ".env"                     # API keys stay in .env, out of this file
min_tool_selection = 0.9
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
```

Override any setting with `REGSHIELD_<SETTING>`, such as `REGSHIELD_JUDGE_MODEL`. See [Configuration](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#configuration-file).

## Logs

Use `--verbose`, `verbose=True` or `REGSHIELD_LOG_LEVEL=debug` to see every check:

```text
[regshield] DEBUG   evaluator: Evaluating 'deploy_gate': 2 steps, 2 tool calls, 0 LLM calls
[regshield] DEBUG   evaluator:   call_ordering          1.00
[regshield] DEBUG   patterns:   pattern policy          PASSED (1.00)
[regshield] INFO    evaluator: 'deploy_gate' PASSED (composite 1.00) in 1.1 ms
```

Logs go to stderr, so stdout stays clean.

## Local dashboard

```bash
regshield serve
```

![The RegShield dashboard showing a failed scenario and the rules it broke](https://raw.githubusercontent.com/SubodhSenpai/RegShield/main/docs/images/dashboard.png)

Opens `http://localhost:8000` with each scenario's scores, checks, cost and trace. It reads `reports/latest_report.json` (written by `regshield eval`, or `save_report=True` in Python) and refreshes by itself.

> [!IMPORTANT]
> The dashboard accepts local connections only and ignores API keys sent in requests. `--host 0.0.0.0` exposes it to your network with no authentication.

## Optional LLM judge

Rules can't tell that "refunded $500" is wrong when the tool refunded $50. The judge can. Any OpenAI-compatible API works:

```bash
# A paid API
export OPENROUTER_API_KEY=sk-or-...     # or OPENAI_API_KEY for OpenAI
regshield eval scenarios.json --llm-judge

# Your own model: no key needed
regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b
```

To keep it on, set `llm_judge`, `judge_base_url` and `judge_model` in the [config file](#configuration). If the judge can't answer, the scenario fails, unless you pass `--judge-on-error pass`.

## Documentation

| Guide | Contents |
|---|---|
| [Getting started](https://github.com/SubodhSenpai/RegShield/blob/main/docs/getting-started.md) | Install, first scenario, capturing traces, CI |
| [Cookbook](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md) | Recipes for common checks, with real output |
| [Agentic patterns](https://github.com/SubodhSenpai/RegShield/blob/main/docs/patterns.md) | Every pattern and its violation messages |
| [Integrations](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md) | LangChain, LangGraph, smolagents, `TraceRecorder`, `@shield`, REST |
| [In production](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md) | Block risky actions, record SDK calls, export runs |
| [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md) | Ollama, vLLM and friends for the agent and the judge |
| [Reference](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md) | Scenario fields, formats, CLI, configuration |
| [Examples](https://github.com/SubodhSenpai/RegShield/tree/main/examples) | Nine real agents on a local LLM |

The same docs are on the website: [agent-reg-shield.vercel.app](https://agent-reg-shield.vercel.app/).

## Development

```bash
git clone https://github.com/SubodhSenpai/RegShield.git
cd RegShield
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                    # offline, no API keys needed
ruff check . && mypy
python -m build                           # dist/*.whl and dist/*.tar.gz, the files a release carries
```

[CI](https://github.com/SubodhSenpai/RegShield/actions/workflows/ci.yml) runs the tests on Linux, Windows and macOS, plus ruff, mypy and a wheel install check.

**Releasing.** Bump `__version__` in `regression_shield/__init__.py` and the install links (a test checks they match), merge into `main`, then tag:

```bash
git tag -a v0.6.0 -m "RegShield 0.6.0"
git push origin v0.6.0
```

The [Release workflow](https://github.com/SubodhSenpai/RegShield/actions/workflows/release.yml) builds and publishes the GitHub release. The website and badge update by themselves.

## License

[MIT](https://github.com/SubodhSenpai/RegShield/blob/main/LICENSE)
