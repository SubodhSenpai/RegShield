# RegShield

**Deterministic quality gates and regression testing for autonomous AI agents.**

Catch prerequisite inversions, loop thrashing, and policy violations in your CI/CD pipeline before agent code reaches production.

---

## Why RegShield?

Traditional evals score text outputs. But agents execute actions—querying databases, calling external APIs, and making irreversible state changes. A prompt tweak might produce a convincing final text answer while silently skipping authentication or looping repeatedly.

RegShield evaluates the **execution trace** (`Thought -> Action -> Observation`) deterministically:

* **Prerequisite Inversion**: Calling `deploy_production()` before `run_tests()`.
* **Loop Thrashing**: Repeating identical queries when stuck, burning budget and latency.
* **Schema Drift**: Calling tools with invalid parameters or mismatched types.
* **Hallucinated State**: Reasoning that an action succeeded when the tool returned an error.
* **100% Local & Fast**: Runs offline in milliseconds. No LLM required for core policy checks ($0 inference cost).

---

## Installation

```bash
pip install regression-shield
```

*(or install from source: `pip install -e .`)*

---

## Quickstart

Evaluate an execution trace against a declarative scenario policy:

```python
from regression_shield import evaluate_trace

# 1. Define expected policy rules
scenario = {
    "scenario_id": "deploy_gate",
    "expected_tools": ["run_unit_tests", "deploy_production"],
    "expected_order": ["run_unit_tests", "deploy_production"],
    "expected_arguments": {
        "deploy_production": {"env": "staging"}
    },
    "optimal_step_count": 2,
}

# 2. Evaluate the agent's actual steps
result = evaluate_trace(
    scenario=scenario,
    trace=[
        {"thought": "Running test suite.", "action": {"name": "run_unit_tests", "args": {}}, "observation": "PASSED"},
        {"thought": "Deploying build.", "action": {"name": "deploy_production", "args": {"env": "staging"}}, "observation": "DEPLOYED"},
    ]
)

result.print_diagnostics()
print(f"Passed: {result.passed} | Score: {result.composite_score:.2f}")
```

If the agent regresses (e.g. executes deploy before tests), `print_diagnostics()` pinpoints the exact failure:

```text
[FAIL] deploy_gate: Cloud Deploy (Composite: 0.80)
    -> Order inversion: 'deploy_production' (step 1) executed before prerequisite 'run_unit_tests' (step 2)
```

---

## Evaluation Dimensions

Every trace is scored across 5 deterministic dimensions (0.0 to 1.0):

| Metric | Weight | What It Enforces | Default Threshold |
|---|:---:|---|:---:|
| **Tool Selection F1** | 25% | Harmonic mean of precision and recall over expected tools. Flags missing or unauthorized calls. | ≥ 0.85 |
| **Argument Correctness** | 25% | Validates tool arguments against parameter schemas and ground truth values. | ≥ 0.85 |
| **Call Ordering** | 20% | Strict enforcement of prerequisite sequence dependencies. Any inversion zeroes the score. | 1.00 |
| **Step Efficiency** | 15% | Penalizes redundant duplicate calls (loop thrashing) and excessive step counts. | ≥ 0.70 |
| **Reasoning Faithfulness** | 15% | Flags when thoughts claim success despite error observations. | ≥ 0.85 |

*Composite Score Threshold: ≥ 0.75 to pass.*

---

## Integrations

### LangChain

```python
from regression_shield import evaluate_trace
from regression_shield.adapters.langchain import RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler()
agent.invoke({"input": task}, config={"callbacks": [handler]})

result = evaluate_trace(scenario=scenario, trace=handler.get_trace())
```

### Hugging Face smolagents

```python
from regression_shield import evaluate_trace
from regression_shield.adapters.smolagents import extract_smolagents_trace

agent.run(task)
result = evaluate_trace(scenario=scenario, trace=extract_smolagents_trace(agent))
```

### Python Function Decorator (`@shield`)

```python
from regression_shield import shield

@shield(scenario=scenario, on_violation="raise")
def my_agent(prompt: str):
    return agent_executor.run(prompt)

output, report = my_agent("Deploy to staging")
```

---

## CI/CD Quality Gate

Run RegShield in your GitHub Actions or pre-commit workflow:

```bash
# Exit code 0 = Passed | Exit code 1 = Block PR
regshield eval -f ./examples/sample_scenarios.json --fail-on-regression
```

Example GitHub Actions workflow (`.github/workflows/quality_gate.yml`):

```yaml
name: Agent Quality Gate
on: [pull_request]

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install regression-shield
      - run: regshield eval -f ./scenarios.json --fail-on-regression
```

---

## Local Observability Dashboard

Launch the built-in minimal trace inspector on your local machine:

```bash
regshield serve --port 8000
```

* Zero configuration, runs 100% locally on `http://localhost:8000`.
* Ingest traces from any language via REST: `POST /api/evaluate-trace`.
* Auto-persists reports to `./reports/latest_report.json`.

---

## Development & Tests

```bash
# Run the test suite (25 tests, offline, < 0.6s)
pytest
```

---

## License

MIT
