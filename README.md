<div align="center">

# RegShield

**Regression tests for what your AI agent *does*, not just what it says.**

Check every tool call, handoff, approval and plan your agent makes, in CI, before a prompt or model change reaches production.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.4.0-18181b)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](LICENSE)
[![Core checks](https://img.shields.io/badge/core%20checks-offline%2C%20no%20API%20key-2563eb)](#how-it-works)
[![Works with](https://img.shields.io/badge/works%20with-LangChain%20%C2%B7%20LangGraph%20%C2%B7%20smolagents%20%C2%B7%20any%20loop-7c3aed)](docs/integrations.md)

[Quickstart](#quickstart) · [Patterns](#agentic-patterns) · [Integrations](#integrations) · [CI](#use-it-in-ci-and-pytest) · [Dashboard](#local-dashboard) · [Examples](examples/README.md) · [Docs](docs/README.md)

</div>

---

## Why

Most evals grade an agent's final answer. But agents act: they move money, change records, deploy code. A prompt tweak can keep the answer sounding right while the agent:

- deploys **before** the tests run
- sends a payment in the **same batch** as the identity check it depends on
- calls a tool it must **never** touch, or acts after a person **rejected** the action
- tells the user *"your refund was processed"* when the refund **never ran**
- hands work to the **wrong** agent, or loops between agents

RegShield checks the **execution trace** (each thought, tool call and result) against rules you write once. The core checks are deterministic, run offline in milliseconds and need no LLM.

## Quickstart

```bash
pip install regression-shield
```

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

trace = [
    {"thought": "Run the tests first.",
     "action": {"name": "run_unit_tests", "args": {}}, "observation": "42 passed"},
    {"thought": "Tests pass, deploying to staging.",
     "action": {"name": "deploy_production", "args": {"env": "staging"}}, "observation": "DEPLOYED"},
]

report = evaluate_trace(scenario, trace)
print(report.passed, report.composite_score)   # True 1.0
```

When the agent regresses (deploying to `prod` before testing), `print(report.format())` says exactly what went wrong:

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

You rarely write traces by hand: the [integrations](#integrations) record them from a real run. To see ten scenarios with no code at all, run `regshield demo`.

## How it works

Each trace is scored on five metrics. A metric below its threshold, or any failing pattern check, fails the scenario.

| Metric | Weight | Checks that | Default threshold |
|---|:---:|---|:---:|
| Tool selection (F1) | 25% | The expected tools ran, and no others (scored when `expected_tools` is set) | 0.85 |
| Argument correctness | 25% | Tools got the expected values (numbers compare numerically; text ignores case, `_` and `-`) | 0.85 |
| Call ordering | 20% | Prerequisites finished before the tools that depend on them | 1.00 |
| Step efficiency | 15% | No repeated calls or extra steps | 0.70 |
| Reasoning faithfulness | 15% | No claim of success right after a failed call or a denied approval | 0.85 |

Every threshold can be changed. For example, to require a tool selection F1 of 0.94 instead of 0.85:

```python
report = evaluate_trace(scenario, trace, min_tool_selection=0.94)
```

```bash
regshield eval scenarios.json --min-tool-selection 0.94
```

The options are `min_tool_selection`, `min_argument_correctness`, `min_call_ordering`, `min_step_efficiency` and `min_reasoning_faithfulness`. They work the same way in `AgentTraceEvaluator(...)`, `@shield(...)` and the REST API. The CLI flags use dashes instead of underscores.

<details>
<summary><b>How the faithfulness check decides, and when to add the LLM judge</b></summary>
<br>

The check is rule-based. A thought or final answer that claims success ("succeeded", "completed", "has been processed", "all set"...) right after a tool result reporting an error, or right after a person denied an action, is flagged. Negations ("was not processed") and wording that acknowledges the failure ("the refund was rejected") are not.

Rules can't read meaning: an answer saying "refunded $500" when the tool refunded $50 passes them. For that, add the [LLM judge](#optional-llm-judge).

</details>

## Agentic patterns

Beyond one agent calling tools, RegShield checks the patterns production agents are built from. A pattern check runs when your scenario configures it or the trace contains its events, and appears in the report only if it checked something.

| Pattern | Catches | Scenario fields |
|---|---|---|
| **Policy** | Forbidden tools, too many calls to a tool | `forbidden_tools`, `max_tool_calls` |
| **Human approval** | Risky tools run without approval, or after a denial | `requires_approval` |
| **Plan-and-execute** | No plan, calls outside the plan, pushing on after a failure without replanning | `require_plan`, `expected_plan` |
| **Multi-agent** | An agent using another agent's tools, wrong delegation order, handoff loops | `agent_tools`, `expected_agents`, `max_handoffs` |
| **Routing** | Requests sent to the wrong place, with accuracy across a test set | `expected_route` |
| **Parallel calls** | Independent calls run one by one; dependent calls run at the same time | `expected_parallel`, `expected_order` pairs |
| **Graph workflows** | Transitions the graph shouldn't take, runaway cycles | `allowed_transitions`, `max_node_visits` |
| **Evaluator-optimizer** | Ignored critiques, shipping a rejected draft, too many rounds | `max_revision_rounds` |

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

[Guide to every pattern](docs/patterns.md)

## Integrations

| Framework | How | Recorded automatically |
|---|---|---|
| **LangChain / LangGraph** | `RegressionShieldCallbackHandler()` as a callback | Tool calls, errors, reasoning, final answer, graph nodes, parallel calls and fan-out, agents and `transfer_to_*` handoffs (supervisor, swarm), `HumanInTheLoopMiddleware` approvals |
| **smolagents** | `instrument_smolagents(agent)` before `agent.run` | Tool calls from `CodeAgent` code and `ToolCallingAgent`, errors, reasoning, final answer, parallel calls, managed agents as handoffs |
| **Anything else** (OpenAI SDK, CrewAI, AutoGen, your own loop) | `TraceRecorder`: wrap tools, call one method per event | Tool calls you wrap, plus the events you record |
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

[Integration guide](docs/integrations.md) · [Runnable examples with a local LLM](examples/README.md)

## Use it in CI and pytest

**Pytest.** `raise_for_failures()` fails the test with every reason:

```python
def test_deploy_gate():
    evaluate_trace(scenario, run_my_agent("Deploy to staging")).raise_for_failures()
```

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

`regression_trace` is optional: a known-bad trace the scenario must catch. If it passes, the run fails too, because the scenario is too weak to catch that regression.

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
      - run: pip install regression-shield
      - run: regshield eval scenarios.json
```

## Logs

Add `--verbose` (CLI), `verbose=True` (Python) or `REGSHIELD_LOG=debug` (anywhere) to see every metric, pattern check and judge call:

```text
[regshield] DEBUG   evaluator: Evaluating 'deploy_gate': 2 steps, 2 tool calls
[regshield] DEBUG   evaluator:   call_ordering          1.00
[regshield] DEBUG   patterns:   pattern policy          PASSED (1.00)
[regshield] INFO    evaluator: 'deploy_gate' PASSED (composite 1.00) in 0.4 ms
```

Logs go to stderr, so stdout stays clean for scripts and CI.

## Local dashboard

```bash
regshield serve
```

Opens `http://localhost:8000` with each scenario's metrics, pattern checks and step-by-step trace, read from `reports/latest_report.json`. `regshield eval` writes that file; in Python, pass `save_report=True`. **Run demo** evaluates the bundled samples, and **Baseline vs. Regression** shows which known-bad traces were caught.

> [!IMPORTANT]
> The dashboard accepts connections from your own machine only and never serves files from disk. It ignores API keys or endpoints sent in requests. `--host 0.0.0.0` exposes it to your network with no authentication, so use it only on networks you trust.

## Optional LLM judge

An LLM reads the whole trace to catch what rules can't, like reporting the wrong amount. It works with any OpenAI-compatible API, including a local Ollama server.

```bash
export OPENROUTER_API_KEY=sk-or-...     # sent to OpenRouter
# or: export OPENAI_API_KEY=sk-...      # sent to OpenAI (default model gpt-4.1-mini)
regshield eval scenarios.json --llm-judge
```

Set `JUDGE_MODEL` and `OPENROUTER_BASE_URL` / `OPENAI_BASE_URL` (or `--model`, `--base-url`) to choose another model or endpoint. Once enabled, the judge must return a verdict: a rate limit or unusable reply fails the scenario, unless you pass `--judge-on-error pass`. RegShield reads keys from the environment and does not load `.env` files.

## Documentation

| Guide | Contents |
|---|---|
| [Getting started](docs/getting-started.md) | Install, first scenario, capturing traces, CI |
| [Agentic patterns](docs/patterns.md) | Every pattern, how to record it, and its violation messages |
| [Integrations](docs/integrations.md) | LangChain, LangGraph, smolagents, `TraceRecorder`, `@shield`, REST |
| [Reference](docs/reference.md) | Scenario fields, trace and report formats, CLI, environment variables, logging |
| [Examples](examples/README.md) | Nine real agents, run against a local LLM |

## Development

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                    # offline, no API keys needed
ruff check .
python -m build                           # dist/*.whl and dist/*.tar.gz
```

The `test` extra (included in `dev`) installs LangChain, LangGraph, langgraph-supervisor and smolagents, so the integration tests run real agents offline with scripted models.

## License

[MIT](LICENSE)
