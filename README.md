# RegressionShield 🛡️
### Agentic AI Reasoning & Execution Trajectory Evaluation Framework

[![pytest](https://img.shields.io/badge/pytest-33%20passed-brightgreen.svg)](tests/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Dedicated Observability & Evaluation for Autonomous Agentic AI Systems.**  
> Traditional text-in, text-out evaluations only check the final response string, missing 30–40% of critical runtime defects. Autonomous agents can stumble upon an acceptable answer while violating enterprise security policies, skipping mandatory verification tools, thrashing in duplicate loops, or hallucinating intermediate reasoning steps.
>
> **RegressionShield monitors and grades the entire ReAct reasoning chain (`Thought` ➔ `Action` ➔ `Observation`) in real time.**

---

## 🚀 Key Capabilities

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             RegressionShield                                │
│                                                                             │
│  [ ReAct Execution Chain & Tool Calling Evaluation ]                        │
│  • Tool Selection F1 (Precision & Recall against allowed tool registries)   │
│  • Argument Schema Validation (Types, bounds, and ground truth parameters)  │
│  • Sequential Order Enforcement (Topological prerequisite dependencies)     │
│  • Step Efficiency & Loop Thrashing Penalties (Detects query oscillation)   │
│  • Intermediate Reasoning Faithfulness (Grounded in prior observations)     │
│  • Composite Trajectory Index (Unified 0.0 – 1.0 quality gate)              │
│                                                                             │
│  [ Open-Source Agent Ecosystem Integration ]                                │
│  • Hugging Face smolagents (ToolCallingAgent live tool execution audit)     │
│  • Enterprise Tool Registry (Identity verification, balance, wire, SRE)     │
│                                                                             │
│  [ Dynamic Local Web Dashboard & REST Server ]                              │
│  • Local HTTP Server: python server.py (or python demo_runner.py --serve)   │
│  • Real-Time ReAct Step Inspector (Inspect thoughts, tool calls, and data)  │
│  • Baseline vs. Regression Delta Comparison Matrix                          │
│  • Live Browser Execution Triggers (Run evals directly from UI)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Core Agentic Reasoning Metrics

| Metric | Type | What It Verifies |
|:-------|:-----|:-----------------|
| **Tool Selection F1** | Algorithmic | Validates precision & recall of invoked tools against required registry. Flags unauthorized, redundant, or missing tools. |
| **Argument Correctness** | Schema Validator | Verifies parameters passed to tools match expected schema types and exact ground truth values (supports numeric/string normalization). |
| **Tool Call Ordering** | Sequence Graph | Enforces prerequisite execution order (e.g. `verify_identity` ➔ `check_balance` ➔ `execute_wire_transfer`). Catches inverted calls. |
| **Trajectory Efficiency** | Heuristic Loop Detector | Detects agent oscillations, duplicate queries, and cycle loops. Penalizes excessive exploration steps. |
| **Reasoning Faithfulness** | Semantic Verifier | Validates intermediate `Thought` alignment with prior `Observation` payloads (e.g. catches agent claiming success after API error). |
| **Composite Trajectory Score** | Weighted Index | Unified 0.0 - 1.0 quality gate index combining tools, args, order, and reasoning. |

---

## 📦 Python SDK Quickstart (Evaluate Any Agent in 2 Lines)

Install the SDK into any Python project or virtual environment:
```bash
pip install -e .
```

### 1. Direct Trajectory Evaluation & Failure Diagnosis
```python
from regression_shield import evaluate_trajectory, StepTrace

# Define the expected policy rules for your workflow
scenario = {
    "scenario_id": "WIRE_TRANSFER_POLICY",
    "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "expected_order": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "expected_arguments": {
        "verify_identity": {"customer_id": "CUST-908"},
        "execute_wire_transfer": {"amount": 4500.0}
    }
}

# Pass the steps executed by your agent:
report = evaluate_trajectory(
    scenario=scenario,
    trajectory=[
        StepTrace(1, thought="Verifying identity.", action_name="verify_identity", action_args={"customer_id": "CUST-908"}, observation="VERIFIED"),
        StepTrace(2, thought="Checking balance.", action_name="check_balance", action_args={"account_id": "ACCT-4401"}, observation="12000.0"),
        StepTrace(3, thought="Executing transfer.", action_name="execute_wire_transfer", action_args={"amount": 4500.0}, observation="SUCCESS"),
    ]
)

print(f"Status: {report.status} | Composite: {report.composite_score}")
report.print_diagnostics()
```

If your agent makes a mistake (skips authentication, calls tools out of order, or loops), `report.print_diagnostics()` pinpoints the exact failure:
```text
[FAILED] Scenario WIRE_TRANSFER_POLICY
Composite Score: 0.42
[!] Failure Diagnoses (Where your agent went wrong):
  -> Tool Selection F1 (0.50) < threshold (0.85). Missing: ['verify_identity', 'check_balance']
  -> Tool Order Accuracy (0.00) < threshold (1.00). Prerequisite violated: 'verify_identity' never called
```

### 2. Drop-in LangChain Callback Tracer
```python
from regression_shield import RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler()

# Pass handler into any LangChain agent execution:
agent_executor.invoke({"input": "Transfer $4,500 to ACCT-9912"}, config={"callbacks": [handler]})

# Evaluate the recorded trace:
report = handler.evaluate(scenario)
report.print_diagnostics()
```

### 3. Using the `regshield` CLI
```bash
# Evaluate agent trajectories from any JSON file:
regshield eval --file my_trajectories.json

# Start the dynamic dashboard server:
regshield serve --port 8000
```

---

## 🖥️ Dynamic Web Dashboard & Local Server

RegressionShield features a modern, dynamic web dashboard backed by a local REST API server:

### Starting the Server
```bash
# Start the dynamic dashboard server on port 8000:
python server.py

# Or via the CLI runner:
python demo_runner.py --serve
```

Once running, navigate to **`http://localhost:8000`** in your browser:
- **🟢 Live Server Connection**: Shows connection status and active OpenRouter LLM judge model (`minimax/minimax-m2.7:free`).
- **⚡ Live Evaluation Triggers**: Click *"Run Live Trajectory Eval"* or *"smolagents Audit"* to trigger live agent reasoning evaluations directly from your browser.
- **🔍 Interactive ReAct Step Inspector**: Step-by-step visual trace (`Thought` ➔ `Action` ➔ `Observation`) with JSON argument syntax highlighting.
- **📊 Baseline vs. Regression Delta Matrix**: Side-by-side comparison highlighting policy regressions ($\Delta -0.50$, $\Delta -1.00$) and root causes.
- **🤗 Hugging Face smolagents Audit**: Real-time inspection of open-source agent tool execution and LLM judge rationale.

---

## ⚡ Quick Start

### 1. Environment Configuration
Create a `.env` file in the project root:
```env
OPENROUTER_API_KEY=your_key_here
JUDGE_MODEL=minimax/minimax-m2.7:free
```

### 2. Run Live Agentic Reasoning Evaluations
```bash
# Default: Runs Baseline vs. Regression Trajectory comparison and saves report
python demo_runner.py

# Live Hugging Face smolagents audit
python demo_runner.py --opensource

# Evaluate baseline agent only
python demo_runner.py --baseline

# Evaluate regressed agent only
python demo_runner.py --regression
```

---

## 🧪 Automated Testing (Pytest)

Run all unit and trajectory evaluation tests:
```bash
# Run entire test suite (100% pass rate)
pytest -v

# Run agentic reasoning and metric tests
pytest -v tests/test_agent_reasoning.py

# Run trajectory evaluator tests
pytest -v tests/test_trajectory_eval.py

# Run live OpenRouter agent tests
pytest -v tests/test_live_agent.py
```

---

## 📁 Repository Structure

```
RL environments/
├── config/
│   ├── __init__.py
│   └── settings.py               # Central thresholds and API config
├── core/
│   ├── __init__.py
│   ├── agent_metrics.py          # ToolSelection, ArgumentCorrectness, ToolCallOrder, StepEfficiency
│   ├── trajectory_evaluator.py   # Agent trajectory evaluation orchestrator
│   └── verifiers.py              # LLM judge verification and token efficiency
├── agent/
│   ├── __init__.py
│   ├── live_tool_agent.py        # Live function-calling agent (OpenRouter ReAct loop)
│   └── tools.py                  # Enterprise tool schema definitions & executor
├── integrations/
│   ├── __init__.py
│   └── smolagents_evaluator.py   # Hugging Face smolagents integration
├── data/
│   └── agent_trajectories.json   # Trajectory scenarios (Fintech wire, Cloud SRE, E-commerce)
├── dashboard/
│   └── index.html                # Dynamic visual ReAct trace & evaluation dashboard
├── tests/
│   ├── test_agent_reasoning.py   # Core reasoning metrics & composite unit tests
│   ├── test_trajectory_eval.py   # Trajectory & tool calling tests
│   ├── test_fallback_models.py   # OpenRouter fallback cascade tests
│   └── test_live_agent.py        # Live tool calling agent tests
├── reports/
│   └── latest_report.json        # Dynamically generated live evaluation report
├── server.py                     # Dynamic HTTP server & REST API
├── demo_runner.py                # Live CLI demo runner & server launcher
└── README.md                     # Documentation
```

---

## 📄 License
MIT License.
