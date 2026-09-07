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
    ],
    # Custom model & API key mapping:
    api_key="your-api-key",                  # Or OPENROUTER_API_KEY / OPENAI_API_KEY
    model="minimax/minimax-m2.7:free",       # Any model: gpt-4o-mini, claude, ollama
    base_url="https://openrouter.ai/api/v1", # OpenAI-compatible endpoint
    use_llm_judge=False,                     # Optional semantic reasoning verification
    min_tool_selection=0.85,                 # Custom quality thresholds
    min_trajectory_efficiency=0.70,
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

### 2. Configurable Arguments & Control Parameters

Every evaluation interface in RegressionShield allows users to map their own API keys, models, and thresholds:

| Parameter | Type | Default | Description |
|:----------|:-----|:--------|:------------|
| `api_key` | `str` | `None` (or env var) | API key for OpenAI-compatible LLM judge (OpenRouter, OpenAI, Groq, etc.). |
| `model` | `str` | `"minimax/minimax-m2.7:free"` | LLM model identifier to use for semantic reasoning verification. |
| `base_url` | `str` | `"https://openrouter.ai/api/v1"` | Custom OpenAI-compatible API base URL (e.g. `http://localhost:11434/v1` for Ollama, vLLM). |
| `use_llm_judge` | `bool` | `False` | When `True`, executes an LLM-as-a-judge audit verifying thought-observation faithfulness. |
| `min_tool_selection` | `float` | `0.85` | Minimum Tool Selection F1 threshold required to pass. |
| `min_argument_correctness` | `float` | `0.85` | Minimum argument schema correctness score. |
| `min_order_accuracy` | `float` | `1.00` | Minimum prerequisite sequence adherence score. |
| `min_trajectory_efficiency` | `float` | `0.70` | Minimum step efficiency and loop avoidance threshold. |

### 3. Drop-in LangChain Callback Tracer
```python
from regression_shield import RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler(
    api_key="your-api-key",
    model="gpt-4o-mini",
)

# Pass handler into any LangChain agent execution:
agent_executor.invoke({"input": "Transfer $4,500 to ACCT-9912"}, config={"callbacks": [handler]})

# Evaluate the recorded trace:
report = handler.evaluate(scenario)
report.print_diagnostics()
```

### 4. Zero-Code Evaluation Decorator
```python
from regression_shield.adapters.decorator import evaluate_agent_trace

@evaluate_agent_trace(
    scenario=scenario,
    model="minimax/minimax-m2.7:free",
    use_llm_judge=False,
)
def run_my_agent(user_query: str):
    # Agent executes its ReAct loop
    return {"steps": [...], "final_response": "..."}

result, report = run_my_agent("Process wire transfer")
print("Agent Passed:", report.passed)
```

### 5. Using the `regshield` CLI
```bash
# 1. Evaluate agent trajectories from any JSON file:
regshield eval --file my_trajectories.json

# 2. Evaluate with a custom model and API key:
regshield eval --file my_trajectories.json \
  --api-key "sk-or-..." \
  --model "minimax/minimax-m2.7:free" \
  --llm-judge \
  --min-tool-selection 0.90

# 3. Start the dynamic dashboard server with custom model config:
regshield serve --port 8000 --model "minimax/minimax-m2.7:free"
```

---

## 🖥️ Dynamic Web Dashboard & REST Ingestion API

RegressionShield features a dynamic web dashboard backed by a local REST API server:

### Starting the Server
```bash
# Start the dynamic dashboard server on port 8000:
regshield serve --port 8000

# Or via Python module:
python -m regression_shield.server --port 8000
```

Once running, navigate to **`http://localhost:8000`** in your browser:
- **🟢 Live Server Connection**: Shows connection status, active model, and uptime.
- **🔍 Interactive ReAct Step Inspector**: Step-by-step visual trace (`Thought` ➔ `Action` ➔ `Observation`) with syntax highlighting.
- **📊 Baseline vs. Regression Delta Matrix**: Side-by-side comparison highlighting policy regressions and failure diagnostics.

### External Ingestion REST API (`POST /api/evaluate-trajectory`)
Any agent running anywhere (Python, Node.js, Go, cURL) can post trajectories directly into RegressionShield with custom API keys and models:

```bash
curl -X POST http://localhost:8000/api/evaluate-trajectory \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "FIN_001",
    "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "model": "gpt-4o-mini",
    "api_key": "your-key-here",
    "steps": [
      {
        "step_index": 1,
        "thought": "Checking customer identity first.",
        "action": {"type": "tool_call", "name": "verify_identity", "args": {"customer_id": "CUST-908"}},
        "observation": "VERIFIED"
      }
    ]
  }'
```

---

## 🧪 Automated Testing (Pytest)

Run all unit and trajectory evaluation tests (100% pass rate, offline & deterministic):
```bash
pytest -v tests/
```

---

## 📁 Repository Structure

```
RL environments/ (Branch: SDK)
├── regression_shield/
│   ├── __init__.py               # Top-level SDK API (evaluate_trajectory, AgentTrajectoryEvaluator, LLMJudge)
│   ├── models.py                 # Pydantic/dataclass models (StepTrace, ScenarioSpec, EvaluationReport)
│   ├── cli.py                    # regshield CLI (eval, serve, demo)
│   ├── server.py                 # Dynamic web dashboard & REST ingestion server
│   ├── core/
│   │   ├── agent_metrics.py      # Core reasoning metrics (ToolSelection, Arguments, Order, Efficiency, Faithfulness)
│   │   ├── trajectory_evaluator.py # Central evaluation orchestrator
│   │   └── llm_judge.py          # OpenAI-compatible semantic LLM judge
│   └── adapters/
│       ├── langchain.py          # LangChain callback handler tracer
│       ├── smolagents.py         # Hugging Face smolagents trace extractor & evaluator
│       └── decorator.py          # @evaluate_agent_trace decorator
├── dashboard/
│   ├── index.html                # Visual ReAct trace & evaluation dashboard
│   ├── styles.css                # Premium dark glassmorphic styling
│   └── app.js                    # Live evaluation & polling logic
├── examples/
│   ├── quickstart_sdk.py         # 2-line quickstart with custom api_key & model
│   └── sample_scenarios.json     # Curated benchmark scenarios
├── tests/
│   ├── test_agent_reasoning.py   # Unit tests for reasoning metrics
│   └── test_sdk.py               # Unit tests for SDK, CLI, and LLM judge
├── pyproject.toml                # Package configuration & entrypoint (regshield)
└── README.md                     # Documentation
```

---

## 📄 License
MIT License.

