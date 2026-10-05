# RegShield

RegShield tests AI agents by what they do. Give it a trace of your agent's run (tool calls, arguments, results, handoffs, approvals) and the rules the run should follow. It tells you which rule broke and at which step. The checks are deterministic, run offline in milliseconds, and fit into pytest or CI. In production, the same rules block risky actions while the agent runs. It works with paid APIs and with models you host yourself.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/SubodhSenpai/RegShield/blob/main/LICENSE)

```bash
pip install regression-shield
```

## Example

An agent deployed to production before running the tests:

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "deploy_gate",
    "expected_order": ["run_tests", "deploy"],
    "expected_arguments": {"deploy": {"env": "staging"}},
}
trace = [
    {"action": {"name": "deploy", "args": {"env": "prod"}}, "observation": "DEPLOYED"},
    {"action": {"name": "run_tests", "args": {}}, "observation": "42 passed"},
]
print(evaluate_trace(scenario, trace).format())
```

```text
FAILED  deploy_gate  (composite 0.55)
  tool_selection          1.00
  argument_correctness    0.00
  call_ordering           0.00
  step_efficiency         1.00
  reasoning_faithfulness  1.00
Failures:
  - Argument correctness 0.00 < 0.85: deploy.env was 'prod', expected 'staging'
  - Call ordering 0.00 < 1.00: 'deploy' (step 1) ran before its prerequisite 'run_tests' (step 2)
```

In practice you don't write traces by hand: the [integrations](#record-your-agent) record them from a real run.

## What it checks

Each trace gets five scores. A score below its threshold fails the scenario.

| Score | Fails when | Default threshold |
|---|---|:---:|
| Tool selection | expected tools didn't run, or unexpected ones did (F1) | 0.85 |
| Argument correctness | a tool got the wrong values | 0.85 |
| Call ordering | a tool ran before its prerequisite | 1.00 |
| Step efficiency | the agent repeated calls or took extra steps | 0.70 |
| Reasoning faithfulness | it claimed success the trace contradicts: right after an error or a denied approval, about a call that failed, or about a call that never ran (in its answer, its reasoning, or a message it sent) | 0.85 |

You can change every threshold: `evaluate_trace(scenario, trace, min_tool_selection=0.94)`, or `--min-tool-selection 0.94` on the command line. The others are `min_argument_correctness`, `min_call_ordering`, `min_step_efficiency` and `min_reasoning_faithfulness`.

Pattern checks cover how agents are built. Each one runs when the scenario sets its fields or the trace contains its events:

| Pattern | Scenario fields |
|---|---|
| Policy: forbidden tools, call limits, dangerous arguments, prerequisites that must succeed | `forbidden_tools`, `max_tool_calls`, `forbidden_arguments`, `prerequisites` |
| Human approval | `requires_approval` |
| Plan-and-execute | `require_plan`, `expected_plan` |
| Multi-agent handoffs | `agent_tools`, `expected_agents`, `max_handoffs` |
| Routing | `expected_route` |
| Parallel calls | `expected_parallel` |
| Graph workflows | `allowed_transitions`, `max_node_visits` |
| Writer and critic loops | `max_revision_rounds` |
| Budget: cost, tokens, model calls | `max_cost_usd`, `max_tokens`, `max_llm_calls` |

Add a check to `warn_only` to report it without failing, while you tune it.

## Cost tracking

The integrations record each model call's token usage with the trace, and `report.cost` shows what the run cost. Calls are priced from a bundled snapshot of public list prices, or the real cost when the provider reports it (OpenRouter), or your own prices. Set a budget per scenario to catch a prompt change that doubles the tokens, or an agent that loops:

```python
evaluate_trace({"scenario_id": "triage", "max_cost_usd": 0.05, "max_llm_calls": 8}, handler)
```

For your own loop, call `recorder.llm_response(response)` after each model call. Paid tools can carry a price too: `@recorder.tool(cost_usd=0.005)`. `regshield pricing refresh` downloads the latest list prices. See [Cost tracking](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#cost-tracking).

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

What this setup gives you:

- **Blocking:** a call that breaks a rule doesn't run. The agent is told why, the attempt is recorded, and a run that uses up its budget stops.
- **Zero-code capture:** `instrument()` records raw SDK loops without code changes. LangChain agents use `handler.middleware()`, and smolagents uses `instrument_smolagents`.
- **Export:** runs stream to any OpenTelemetry backend, a JSONL file or a webhook. Sampling and rate limits keep volumes down, and runs with problems are always kept.

See [In production](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md).

## Record your agent

```python
from regression_shield import (RegressionShieldCallbackHandler, TraceRecorder, evaluate_trace, instrument,
                               instrument_smolagents)

# LangChain agents and LangGraph graphs: one callback
handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})
report = evaluate_trace(scenario, handler)

# smolagents (CodeAgent or ToolCallingAgent): instrument before the run
recorder = instrument_smolagents(agent)
agent.run(task)
report = evaluate_trace(scenario, recorder)

# Your own loop on the OpenAI, Anthropic or Gemini SDK: no changes to it
instrument()
with TraceRecorder() as recorder:
    run_my_agent(task)
report = evaluate_trace(scenario, recorder)

# Anything else: wrap your tools, then evaluate the recorder the same way
recorder = TraceRecorder()
search = recorder.wrap(search)
```

The LangChain handler also records graph nodes, parallel calls, sub-agents, `transfer_to_*` handoffs and `HumanInTheLoopMiddleware` approvals. Install the extra you need: `pip install "regression-shield[langgraph]"` (or `[langchain]`, `[smolagents]`, `[otel]`, `[all]`).

## Local models or paid APIs

Use whatever suits you. RegShield records your agent the same way whether it calls OpenAI, Anthropic, Gemini or OpenRouter, or a model on your own GPU through Ollama, vLLM, LM Studio or llama.cpp:

```bash
ollama pull qwen2.5:7b      # after installing Ollama from ollama.com
```

```python
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")   # your agent, on a local model
```

Local models cost nothing per token in `report.cost`, while paid models are priced from list prices. The optional LLM judge can run locally too, with no API key (below). See [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md) for the full setup.

## Run it in tests and CI

```python
def test_deploy_gate():
    evaluate_trace(SCENARIO, run_my_agent("Deploy to staging")).raise_for_failures()
```

Or keep scenarios and recorded traces in a JSON file and run `regshield eval scenarios.json` in CI. It exits with 1 when a scenario fails, and also when a known-bad `regression_trace` passes, since that scenario can't catch the regression. See [Gate pull requests](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md#gate-pull-requests) for a GitHub Actions workflow. Add `--verbose` to see every check as it runs.

Agents don't behave the same on every run. `evaluate_runs(scenario, traces)` checks several runs of the same task and reports the pass rate; in a scenario file, give an item `traces` instead of `trace`.

Every setting can live in one file (thresholds, the judge, prices, logs, export), so tests, CI and production share it. Start one with `regshield config init`, then check what's in effect with `regshield config show`. API keys stay out of that file, in the environment or a `.env` it loads (`env_file = ".env"`). Any setting can be overridden with `REGSHIELD_<SETTING>`. See [Configuration](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md#configuration-file).

## Dashboard

```bash
regshield serve
```

![The RegShield dashboard showing a failed scenario and the rules it broke](https://raw.githubusercontent.com/SubodhSenpai/RegShield/main/docs/images/dashboard.png)

`regshield serve` opens `http://localhost:8000`, with each scenario's scores, pattern checks and steps, and every known-bad trace next to the one that passed. It reads `reports/latest_report.json`, which `regshield eval` and `evaluate_trace(..., save_report=True)` write. It runs on your machine only and has no login; `--host 0.0.0.0` would expose it to your network.

## LLM judge (optional)

Rules can't tell that "refunded $500" is wrong when the tool refunded $50. The LLM judge reads the whole trace and can. It works with any OpenAI-compatible API, paid or your own:

```bash
# A paid API
export OPENROUTER_API_KEY=sk-or-...     # or OPENAI_API_KEY for OpenAI
regshield eval scenarios.json --llm-judge

# Your own model: no key needed
regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b
```

To make it permanent, set `llm_judge`, `judge_base_url` and `judge_model` in `[tool.regshield]` (see [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md)). RegShield reads keys from the environment, or from a `.env` file your config names with `env_file`.

## Documentation

- [Getting started](https://github.com/SubodhSenpai/RegShield/blob/main/docs/getting-started.md)
- [Cookbook](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md): recipes for common checks, each with its real output
- [Agentic patterns](https://github.com/SubodhSenpai/RegShield/blob/main/docs/patterns.md)
- [Integrations](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md)
- [In production](https://github.com/SubodhSenpai/RegShield/blob/main/docs/production.md): block risky actions, record SDK calls, export runs, refresh prices
- [Local and self-hosted models](https://github.com/SubodhSenpai/RegShield/blob/main/docs/local-models.md): install Ollama, run the agent and the judge on your own GPU or servers
- [Reference](https://github.com/SubodhSenpai/RegShield/blob/main/docs/reference.md): every scenario field, CLI flag and environment variable
- [Examples](https://github.com/SubodhSenpai/RegShield/tree/main/examples): nine agents run against a local LLM

## Development

```bash
pip install -e ".[dev]"
pytest              # offline, no API keys needed
ruff check . && mypy
```

## License

[MIT](https://github.com/SubodhSenpai/RegShield/blob/main/LICENSE)
