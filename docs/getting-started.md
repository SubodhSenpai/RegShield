# Getting started

## Install

```bash
pip install regression-shield
```

Optional extras for the framework integrations:

```bash
pip install "regression-shield[langchain]"    # LangChain callback handler
pip install "regression-shield[langgraph]"    # LangGraph (includes LangChain)
pip install "regression-shield[smolagents]"   # Hugging Face smolagents
pip install "regression-shield[all]"          # all of the above
```

RegShield needs Python 3.10 or newer. The core checks run offline and need no API key.

## 1. Describe what the agent should do

A **scenario** is a dict (or JSON object) of rules. Every field except `scenario_id` is optional, and a check runs only when its field is set:

```python
scenario = {
    "scenario_id": "deploy_gate",
    "title": "Tests before deploy",
    "expected_tools": ["run_unit_tests", "deploy_production"],        # tools that must run
    "expected_order": ["run_unit_tests", "deploy_production"],        # tests before deploy
    "expected_arguments": {"deploy_production": {"env": "staging"}},
    "forbidden_tools": ["drop_database"],                              # never allowed
}
```

A misspelled field name raises an error instead of being ignored. Put your own data under `metadata`. See the [reference](reference.md#scenario-fields) for every field.

## 2. Capture what the agent did

A **trace** is the list of steps the agent took. Each step has an action, what came back, and optionally the reasoning before it:

```python
trace = [
    {"thought": "Run the tests first.",
     "action": {"name": "run_unit_tests", "args": {}},
     "observation": "42 passed"},
    {"thought": "Tests pass, deploying to staging.",
     "action": {"name": "deploy_production", "args": {"env": "staging"}},
     "observation": "DEPLOYED"},
]
```

You rarely write traces by hand. Record them from a real run:

```python
# LangChain or LangGraph
from regression_shield import RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler()
agent.invoke({"messages": [{"role": "user", "content": "Deploy to staging"}]}, config={"callbacks": [handler]})
trace = handler          # anything with get_trace() can be evaluated directly
```

```python
# Your own code: wrap the tools
from regression_shield import TraceRecorder

recorder = TraceRecorder()
run_unit_tests = recorder.wrap(run_unit_tests)
deploy_production = recorder.wrap(deploy_production)
my_agent("Deploy to staging", tools=[run_unit_tests, deploy_production])
trace = recorder
```

See [Integrations](integrations.md) for smolagents and more.

## 3. Evaluate

```python
from regression_shield import evaluate_trace

report = evaluate_trace(scenario, trace)
print(report.format())

report.passed            # True / False
report.composite_score   # 0.0 to 1.0
report.failures          # every reason it failed, in plain English
report.patterns          # results of the agentic pattern checks that ran
```

If the agent deploys to `prod` before testing:

```text
FAILED  deploy_gate  Tests before deploy  (composite 0.55)
  ...
Failures:
  - Argument correctness 0.00 < 0.85: deploy_production.env was 'prod', expected 'staging'
  - Call ordering 0.00 < 1.00: 'deploy_production' (step 1) ran before its prerequisite 'run_unit_tests' (step 2)
```

Thresholds are keyword arguments, for example `evaluate_trace(scenario, trace, min_step_efficiency=0.5)`. Add `verbose=True` to see every check as it runs.

## 4. Test it

In pytest, `raise_for_failures()` fails the test and lists every reason:

```python
from regression_shield import evaluate_trace

def test_deploy_gate():
    trace = run_agent_and_record("Deploy to staging")
    evaluate_trace(scenario, trace).raise_for_failures()
```

LLM agents don't behave the same on every run. Run important scenarios several times, or on a set of inputs, and look at the pass rate.

## 5. Gate your CI

Save scenarios with recorded traces in a JSON file. `regression_trace` is optional: a known-bad trace the scenario must catch.

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
regshield eval scenarios.json    # exit code 0 all passed, 1 something failed, 2 bad input
regshield demo                   # the bundled samples, one per pattern
```

A run fails when a scenario fails, or when a `regression_trace` passes (the scenario doesn't catch that regression).

GitHub Actions:

```yaml
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

## 6. Look at the results

```bash
regshield serve
```

The dashboard at `http://localhost:8000` shows each scenario's metrics, pattern checks and full trace. It reads `reports/latest_report.json` in the folder you start it from; `regshield eval` writes that file, and so does `evaluate_trace(..., save_report=True)`.

## Next

- Plans, handoffs, approvals, routers, graphs or critique loops: [Agentic patterns](patterns.md)
- Framework details: [Integrations](integrations.md)
- Nine real agents run against a local LLM: [Examples](../examples/README.md)
