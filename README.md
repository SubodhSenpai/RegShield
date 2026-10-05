# RegShield

RegShield tests AI agents by what they do. Give it a trace of your agent's run (tool calls, arguments, results, handoffs, approvals) and the rules the run should follow. It tells you which rule broke and at which step. The checks are deterministic, run offline in milliseconds, and fit into pytest or CI.

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
| Reasoning faithfulness | it claimed success right after an error or a denied approval | 0.85 |

You can change every threshold: `evaluate_trace(scenario, trace, min_tool_selection=0.94)`, or `--min-tool-selection 0.94` on the command line. The others are `min_argument_correctness`, `min_call_ordering`, `min_step_efficiency` and `min_reasoning_faithfulness`.

Pattern checks cover how agents are built. Each one runs when the scenario sets its fields or the trace contains its events:

| Pattern | Scenario fields |
|---|---|
| Policy: forbidden tools, call limits | `forbidden_tools`, `max_tool_calls` |
| Human approval | `requires_approval` |
| Plan-and-execute | `require_plan`, `expected_plan` |
| Multi-agent handoffs | `agent_tools`, `expected_agents`, `max_handoffs` |
| Routing | `expected_route` |
| Parallel calls | `expected_parallel` |
| Graph workflows | `allowed_transitions`, `max_node_visits` |
| Writer and critic loops | `max_revision_rounds` |

## Record your agent

```python
from regression_shield import RegressionShieldCallbackHandler, TraceRecorder, evaluate_trace, instrument_smolagents

# LangChain agents and LangGraph graphs: one callback
handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})
report = evaluate_trace(scenario, handler)

# smolagents (CodeAgent or ToolCallingAgent): instrument before the run
recorder = instrument_smolagents(agent)
agent.run(task)
report = evaluate_trace(scenario, recorder)

# Anything else: wrap your tools, then evaluate the recorder the same way
recorder = TraceRecorder()
search = recorder.wrap(search)
```

The LangChain handler also records graph nodes, parallel calls, sub-agents, `transfer_to_*` handoffs and `HumanInTheLoopMiddleware` approvals. Install the extra you need: `pip install "regression-shield[langgraph]"` (or `[langchain]`, `[smolagents]`, `[all]`).

## Run it in tests and CI

```python
def test_deploy_gate():
    evaluate_trace(SCENARIO, run_my_agent("Deploy to staging")).raise_for_failures()
```

Or keep scenarios and recorded traces in a JSON file and run `regshield eval scenarios.json` in CI. It exits with 1 when a scenario fails, and also when a known-bad `regression_trace` passes, since that scenario can't catch the regression. See [Gate pull requests](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md#gate-pull-requests) for a GitHub Actions workflow. Add `--verbose` to see every check as it runs.

## Dashboard

```bash
regshield serve
```

![The RegShield dashboard showing a failed scenario and the rules it broke](https://raw.githubusercontent.com/SubodhSenpai/RegShield/main/docs/images/dashboard.png)

`regshield serve` opens `http://localhost:8000`, with each scenario's scores, pattern checks and steps, and every known-bad trace next to the one that passed. It reads `reports/latest_report.json`, which `regshield eval` and `evaluate_trace(..., save_report=True)` write. It runs on your machine only and has no login; `--host 0.0.0.0` would expose it to your network.

## LLM judge (optional)

Rules can't tell that "refunded $500" is wrong when the tool refunded $50. The LLM judge reads the whole trace and can. It works with any OpenAI-compatible API:

```bash
export OPENROUTER_API_KEY=sk-or-...     # or OPENAI_API_KEY for OpenAI
regshield eval scenarios.json --llm-judge
```

To use a local model, see [Judge answers with a local model](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md#judge-answers-with-a-local-model). RegShield reads keys from the environment and doesn't load `.env` files.

## Documentation

- [Getting started](https://github.com/SubodhSenpai/RegShield/blob/main/docs/getting-started.md)
- [Cookbook](https://github.com/SubodhSenpai/RegShield/blob/main/docs/cookbook.md): recipes for common checks, each with its real output
- [Agentic patterns](https://github.com/SubodhSenpai/RegShield/blob/main/docs/patterns.md)
- [Integrations](https://github.com/SubodhSenpai/RegShield/blob/main/docs/integrations.md)
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
