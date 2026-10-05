<div align="center">

# RegShield

**Regression tests for what your AI agent *does*, not just what it says.**

Check every tool call, handoff, approval and plan your agent makes: in CI, before a prompt or model change ships, and in production, before a risky call runs. Works with paid APIs and with models you host yourself.

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

Most evals grade an agent's final answer. But agents act: they move money, change records, deploy code. A prompt tweak can keep the answer sounding right while the agent:

- deploys **before** the tests run
- sends a payment in the **same batch** as the identity check it depends on
- calls a tool it must **never** touch, or acts after a person **rejected** the action
- tells the user *"your refund was processed"* when the refund **never ran**
- hands work to the **wrong** agent, or loops between agents
- loops until it has spent **far more** than the task is worth

RegShield checks the **execution trace** (each thought, tool call and result) against rules you write once. The core checks are deterministic, run offline in milliseconds and need no LLM. In production, the same rules **block** a risky call before it runs.

## Install

RegShield isn't on PyPI yet. Every [GitHub release](https://github.com/SubodhSenpai/RegShield/releases/latest) carries the built package, and pip installs it straight from GitHub:

```bash
pip install https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
```

| Download | What it is |
|---|---|
| [regression_shield-0.5.0-py3-none-any.whl](https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl) | The package, for Windows, macOS and Linux with Python 3.10 or newer. You can also download it and `pip install` the file. |
| [regression_shield-0.5.0.tar.gz](https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0.tar.gz) | The release's source code |

A framework integration needs its extra, in square brackets: `langchain`, `langgraph`, `smolagents`, `otel` (OpenTelemetry export) or `all`.

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

In `requirements.txt`, or under `dependencies` in your `pyproject.toml`:

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

When the agent tests first and deploys to staging, `report.passed` is `True` and `report.composite_score` is `1.0`. You rarely write traces by hand: the [integrations](#integrations) record them from a real run. To see ten scenarios with no code at all, run `regshield demo`.

## How it works

Each trace is scored on five metrics. A metric below its threshold, or any failing pattern check, fails the scenario.

| Metric | Weight | Checks that | Default threshold |
|---|:---:|---|:---:|
| Tool selection (F1) | 25% | The expected tools ran, and no others (scored when `expected_tools` is set) | 0.85 |
| Argument correctness | 25% | Tools got the expected values (numbers compare numerically; text ignores case, `_` and `-`) | 0.85 |
| Call ordering | 20% | Prerequisites finished before the tools that depend on them | 1.00 |
| Step efficiency | 15% | No repeated calls or extra steps | 0.70 |
| Reasoning faithfulness | 15% | No claim of success that the trace contradicts | 0.85 |

Every threshold can be changed. For example, to require a tool selection F1 of 0.94 instead of 0.85:

```python
report = evaluate_trace(scenario, trace, min_tool_selection=0.94)
```

```bash
regshield eval scenarios.json --min-tool-selection 0.94
```

The options are `min_tool_selection`, `min_argument_correctness`, `min_call_ordering`, `min_step_efficiency` and `min_reasoning_faithfulness`. They work the same way in `AgentTraceEvaluator(...)`, `@shield(...)`, the REST API and the [config file](#configuration). The CLI flags use dashes instead of underscores.

<details>
<summary><b>How the faithfulness check decides, and when to add the LLM judge</b></summary>
<br>

The check is rule-based. A thought, a final answer or a message the agent sends that claims success ("succeeded", "completed", "has been processed", "all set"...) is flagged when the trace contradicts it: right after a failed call or a denied approval, or about a call that failed or never ran. Negations ("was not processed") and wording that acknowledges the failure ("the refund was rejected") are not.

Rules can't read meaning: an answer saying "refunded $500" when the tool refunded $50 passes them. For that, add the [LLM judge](#optional-llm-judge).

</details>

## Agentic patterns

Beyond one agent calling tools, RegShield checks the patterns production agents are built from. A pattern check runs when your scenario configures it or the trace contains its events, and appears in the report only if it checked something.

| Pattern | Catches | Scenario fields |
|---|---|---|
| **Policy** | Forbidden tools, dangerous arguments, too many calls to a tool, a step whose prerequisite didn't succeed | `forbidden_tools`, `forbidden_arguments`, `max_tool_calls`, `prerequisites` |
| **Human approval** | Risky tools run without approval, or after a denial | `requires_approval` |
| **Plan-and-execute** | No plan, calls outside the plan, pushing on after a failure without replanning | `require_plan`, `expected_plan` |
| **Multi-agent** | An agent using another agent's tools, wrong delegation order, handoff loops | `agent_tools`, `expected_agents`, `max_handoffs` |
| **Routing** | Requests sent to the wrong place, with accuracy across a test set | `expected_route` |
| **Parallel calls** | Independent calls run one by one; dependent calls run at the same time | `expected_parallel`, `expected_order` pairs |
| **Graph workflows** | Transitions the graph shouldn't take, runaway cycles | `allowed_transitions`, `max_node_visits` |
| **Evaluator-optimizer** | Ignored critiques, shipping a rejected draft, too many rounds | `max_revision_rounds` |
| **Budget** | A run that costs too much, uses too many tokens or makes too many model calls | `max_cost_usd`, `max_tokens`, `max_llm_calls` |

Add a check to `warn_only` to report it without failing, while you tune it.

In your own code, record events with a `TraceRecorder`:

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
| **LangChain / LangGraph** | `RegressionShieldCallbackHandler()` as a callback | Tool calls, errors, reasoning, final answer, model calls and tokens, graph nodes, parallel calls and fan-out, agents and `transfer_to_*` handoffs (supervisor, swarm), `HumanInTheLoopMiddleware` approvals |
| **smolagents** | `instrument_smolagents(agent)` before `agent.run` | Tool calls from `CodeAgent` code and `ToolCallingAgent`, errors, reasoning, final answer, model calls, parallel calls, managed agents as handoffs |
| **OpenAI, Anthropic, Gemini SDKs** | `instrument()` once, then `with TraceRecorder():` around your loop | Every model call with its tokens, tool calls rebuilt from the conversation, the final answer |
| **Anything else** (CrewAI, AutoGen, your own loop) | `TraceRecorder`: wrap tools, call one method per event | Tool calls you wrap, plus the events you record |
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

The rules you test with can also protect the running agent:

```python
import regression_shield as rs

guard = rs.Guard(scenario, rate_limits={"send_email": "10/minute"})       # the same scenario as your tests
rs.instrument()                                                           # record OpenAI, Anthropic, Gemini SDK calls
rs.export_traces(rs.OpenTelemetryExporter(endpoint="http://localhost:4318"), sample_rate=0.1)

with rs.TraceRecorder(guard=guard) as recorder:
    answer = run_my_agent(question)
```

- **Blocking:** a call that breaks a rule doesn't run. The agent is told why, the attempt is recorded, and a run that uses up its budget stops.
- **Zero-code capture:** `instrument()` records raw SDK loops without code changes. LangChain agents use `handler.middleware()`, and smolagents uses `instrument_smolagents`.
- **Export:** runs stream to any OpenTelemetry backend, a JSONL file or a webhook. Sampling and rate limits keep volumes down, and runs with problems are always kept.

[In production guide](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md)

## Cost tracking

The integrations record each model call's token usage with the trace, and `report.cost` shows what the run cost. Calls are priced from a bundled snapshot of public list prices, or the real cost when the provider reports it (OpenRouter), or your own prices. Set a budget per scenario to catch a prompt change that doubles the tokens, or an agent that loops:

```python
evaluate_trace({"scenario_id": "triage", "max_cost_usd": 0.05, "max_llm_calls": 8}, handler)
```

For your own loop, call `recorder.llm_response(response)` after each model call. Paid tools can carry a price too: `@recorder.tool(cost_usd=0.005)`. `regshield pricing refresh` downloads the latest list prices. See [Cost tracking](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#cost-tracking).

## Local models or paid APIs

Use whatever suits you. RegShield records your agent the same way whether it calls OpenAI, Anthropic, Gemini or OpenRouter, or a model on your own GPU through Ollama, vLLM, LM Studio or llama.cpp:

```bash
ollama pull qwen2.5:7b      # after installing Ollama from ollama.com
```

```python
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")   # your agent, on a local model
```

Local models cost nothing per token in `report.cost`, while paid models are priced from list prices. The optional [LLM judge](#optional-llm-judge) can run locally too, with no API key. See [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md) for the full setup.

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

**Scenario files.** Save scenarios with recorded traces in a JSON file and gate every pull request:

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

`regression_trace` is optional: a known-bad trace the scenario must catch. If it passes, the run fails too, because the scenario is too weak to catch that regression. Agents don't behave the same on every run: give an item `traces` instead of `trace`, or call `evaluate_runs(scenario, traces)`, to check several runs and report the pass rate.

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

Every setting can live in one file: thresholds, the LLM judge, prices, logs and export. Tests, CI and production then share it.

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

Any setting can be overridden with an environment variable named `REGSHIELD_<SETTING>`, such as `REGSHIELD_JUDGE_MODEL`. See [Configuration](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#configuration-file).

## Logs

Add `--verbose` (CLI), `verbose=True` (Python), `REGSHIELD_LOG_LEVEL=debug` (environment) or `log_level = "debug"` (config file) to see every metric, pattern check and judge call:

```text
[regshield] DEBUG   evaluator: Evaluating 'deploy_gate': 2 steps, 2 tool calls, 0 LLM calls
[regshield] DEBUG   evaluator:   call_ordering          1.00
[regshield] DEBUG   patterns:   pattern policy          PASSED (1.00)
[regshield] INFO    evaluator: 'deploy_gate' PASSED (composite 1.00) in 1.1 ms
```

Logs go to stderr, so stdout stays clean for scripts and CI.

## Local dashboard

```bash
regshield serve
```

![The RegShield dashboard showing a failed scenario and the rules it broke](https://raw.githubusercontent.com/SubodhSenpai/RegShield/main/docs/images/dashboard.png)

Opens `http://localhost:8000` with each scenario's metrics, pattern checks, judge verdict, cost and step-by-step trace, read from `reports/latest_report.json`. `regshield eval` writes that file; in Python, pass `save_report=True`. The page updates by itself when a new report is written. **Run demo** evaluates the bundled samples, and **Baseline vs. Regression** shows which known-bad traces were caught.

> [!IMPORTANT]
> The dashboard accepts connections from your own machine only and never serves files from disk. It ignores API keys or endpoints sent in requests. `--host 0.0.0.0` exposes it to your network with no authentication, so use it only on networks you trust.

## Optional LLM judge

Rules can't tell that "refunded $500" is wrong when the tool refunded $50. The LLM judge reads the whole trace and can. It works with any OpenAI-compatible API, paid or your own:

```bash
# A paid API
export OPENROUTER_API_KEY=sk-or-...     # or OPENAI_API_KEY for OpenAI
regshield eval scenarios.json --llm-judge

# Your own model: no key needed
regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b
```

To make it permanent, set `llm_judge`, `judge_base_url` and `judge_model` in your [config file](#configuration). Once enabled, the judge must return a verdict: a rate limit or an unusable reply fails the scenario, unless you pass `--judge-on-error pass`. RegShield reads keys from the environment, or from the `.env` file your config names with `env_file`.

## Documentation

| Guide | Contents |
|---|---|
| [Getting started](https://github.com/SubodhSenpai/RegShield/blob/main/docs/getting-started.md) | Install, first scenario, capturing traces, CI |
| [Cookbook](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md) | Recipes for common checks, each with its real output |
| [Agentic patterns](https://github.com/SubodhSenpai/RegShield/blob/main/docs/patterns.md) | Every pattern, how to record it, and its violation messages |
| [Integrations](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md) | LangChain, LangGraph, smolagents, `TraceRecorder`, `@shield`, REST |
| [In production](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md) | Block risky actions, record SDK calls, export runs, refresh prices |
| [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md) | Install Ollama, and run the agent and the judge on your own GPU or servers |
| [Reference](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md) | Scenario fields, trace and report formats, CLI, configuration, environment variables |
| [Examples](https://github.com/SubodhSenpai/RegShield/tree/main/examples) | Nine real agents, run against a local LLM |

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

The `test` extra (included in `dev`) installs LangChain, LangGraph, langgraph-supervisor, smolagents and the OpenAI, Anthropic and Gemini SDKs, so the integration tests run real agents offline with scripted models.

[CI](https://github.com/SubodhSenpai/RegShield/actions/workflows/ci.yml) runs the same checks on every push and pull request: the tests on Linux, Windows and macOS, ruff and mypy, and a check that the built wheel installs and runs.

**Releasing.** Bump `__version__` in `regression_shield/__init__.py` and the version in the install links (a test fails until they match), then merge into `main`. Tag that commit and push the tag:

```bash
git tag -a v0.6.0 -m "RegShield 0.6.0"
git push origin v0.6.0
```

The [Release workflow](https://github.com/SubodhSenpai/RegShield/actions/workflows/release.yml) tests the commit, builds the wheel and source archive, and publishes them as a GitHub release. The website and the release badge pick up the new release by themselves.

## License

[MIT](https://github.com/SubodhSenpai/RegShield/blob/main/LICENSE)
