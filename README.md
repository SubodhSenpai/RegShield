# RegressionShield
### Agentic AI Reasoning and Execution Trace Evaluation Framework

[![pytest](https://img.shields.io/badge/pytest-24%20passed-brightgreen.svg)](tests/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

RegressionShield is an open-source, deterministic evaluation and observability framework designed for autonomous agentic AI systems. It monitors, scores, and asserts policy conformance across the entire ReAct reasoning chain (Thought -> Action -> Observation) in real time.

---

## The Critical Problem: Silent Failures in Agentic Systems

Traditional LLM evaluations (RAG benchmarks, semantic similarity, MMLU, BLEU/ROUGE) only evaluate the final output text. In autonomous agentic workflows (function calling, multi-step ReAct loops, code generation, tool orchestration), this creates critical blind spots:

1. **Policy Violations with Plausible Output**: An agent produces a polite, seemingly correct final answer while completely skipping mandatory verification tools (e.g. KYC authentication, balance verification, compliance audits).
2. **Inverted Prerequisite Chains**: An agent executes high-impact or destructive operations (e.g. `execute_wire_transfer`, `delete_database`, `rollback_deployment`) before verifying necessary security conditions.
3. **Loop Thrashing and Cost Inflation**: An agent becomes trapped in redundant query cycles, burning 10x more tokens and latency while eventually stumbling upon an answer.
4. **Ungrounded Reasoning State Transitions**: An agent's intermediate thoughts claim an operation succeeded even when the prior tool observation explicitly returned an error code.

RegressionShield provides deterministic, algorithmic quality gates that detect these regressions in CI/CD before code reaches production.

---

## Market Positioning and Competitor Comparison

| Feature / Capability | LangSmith | Braintrust | DeepEval | Arize Phoenix | AgentOps | RegressionShield |
|:---|:---|:---|:---|:---|:---|:---|
| **Core Architecture** | Cloud APM | Cloud Evals | Unit Tests | OTEL Collector | Session Replay | **Deterministic Quality Gate** |
| **Tool Order Enforcement** | Manual Python | Custom scripts | LLM-judge only | Trace waterfall | Session timeline | **Algorithmic Topological DAG** |
| **Loop / Thrashing Penalties** | No | No | No | No | Token metrics | **Deterministic Signature Math** |
| **Offline / Zero Cloud** | No (SaaS) | No (SaaS) | Partial | Self-hosted OTEL | No (SaaS) | **100% Offline (0.02s per test)** |
| **Cost per Test Run** | Metered SaaS | Metered SaaS | High (LLM tokens)| Infra overhead | Metered SaaS | **$0.00 (Algorithmic) + Optional Judge** |
| **Framework Independence** | LangChain biased | Generic API | Generic API | OpenTelemetry | CrewAI/AutoGen | **LangChain, smolagents, REST, Python** |

---

## Core Algorithmic Reasoning Metrics

RegressionShield scores agent execution traces across 5 orthogonal metrics that form a unified composite score (0.00 to 1.00):

| Metric | Evaluation Type | Mathematical Definition & Quality Goal |
|:---|:---|:---|
| **Tool Selection F1** | Algorithmic Set Math | Harmonic mean of Precision and Recall against the allowed/expected tool registry. Flags unauthorized, missing, or hallucinated tools. |
| **Argument Correctness** | Schema Validator | Verifies parameter values and types against expected ground truth schemas. Normalizes string cases, numbers, and key structures. |
| **Tool Call Ordering** | Topological Sequence Graph | Evaluates strict prerequisite dependencies (e.g. `auth` -> `read` -> `write`). Detects and penalizes inverted calls. |
| **Trace Efficiency** | Heuristic Loop Detector | Penalizes duplicate query signatures, oscillating state loops, and excessive exploration steps beyond optimal path. |
| **Reasoning Faithfulness** | Semantic Grounding | Analyzes whether intermediate thoughts accurately reflect prior tool observations without hallucinating success on error payloads. |
| **Composite Trace Score** | Weighted Quality Gate | Unified composite score: `0.25*(Tool F1) + 0.25*(Arg Correctness) + 0.20*(Ordering) + 0.15*(Efficiency) + 0.15*(Faithfulness)`. |

---

## Python SDK Quickstart

Install the package into any Python virtual environment:
```bash
pip install -e .
```

### 1. Direct Execution Trace Evaluation

Evaluate an agent execution trace and diagnose failures in 2 lines of code:

```python
from regression_shield import evaluate_trace, StepTrace

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

# Pass the execution trace steps taken by your agent:
report = evaluate_trace(
    scenario=scenario,
    trace=[
        StepTrace(1, thought="Verifying identity.", action_name="verify_identity", action_args={"customer_id": "CUST-908"}, observation="VERIFIED"),
        StepTrace(2, thought="Checking balance.", action_name="check_balance", action_args={"account_id": "ACCT-4401"}, observation="12000.0"),
        StepTrace(3, thought="Executing transfer.", action_name="execute_wire_transfer", action_args={"amount": 4500.0}, observation="SUCCESS"),
    ],
    api_key="your-api-key",                  # Optional: For semantic LLM judge
    model="minimax/minimax-m2.7:free",       # Any OpenAI-compatible model (gpt-4o-mini, ollama, etc.)
    base_url="https://openrouter.ai/api/v1", # Custom endpoint URL
    use_llm_judge=False,                     # Deterministic offline evaluation by default
    min_tool_selection=0.85,                 # Custom quality thresholds
    min_trace_efficiency=0.70,
)

print(f"Status: {report.status} | Composite Score: {report.composite_score}")
report.print_diagnostics()
```

If an agent makes a mistake (skips authentication, inverts sequence, or enters a loop), `report.print_diagnostics()` outputs an actionable breakdown:

```text
[FAILED] Scenario WIRE_TRANSFER_POLICY: Secure Wire Transfer
Composite Score: 0.42
--------------------------------------------------
  * tool_selection          : 0.50
  * argument_correctness    : 0.00
  * call_ordering           : 0.00
  * step_efficiency         : 1.00
  * reasoning_faithfulness  : 1.00

[!] Failure Diagnoses (Where your agent went wrong):
  -> Tool Selection F1 (0.50) < threshold (0.85). Missing: ['check_balance', 'verify_identity'], Unexpected: []
  -> Argument Correctness (0.00) < threshold (0.85). Mismatches detected: 2
  -> Tool Order Accuracy (0.00) < threshold (1.00). Violations: Missing prerequisite execution: 'verify_identity' or 'check_balance' not called
```

---

## Configurable Arguments and Control Parameters

Every evaluation interface in RegressionShield exposes uniform configuration parameters:

| Parameter | Type | Default | Description |
|:---|:---|:---|:---|
| `api_key` | `str` | `None` (or env var) | Bearer token for OpenAI-compatible providers (OpenRouter, OpenAI, Groq, local). |
| `model` | `str` | `"minimax/minimax-m2.7:free"` | LLM model identifier for semantic thought-observation verification. |
| `base_url` | `str` | `"https://openrouter.ai/api/v1"` | Custom OpenAI-compatible API base URL (e.g. `http://localhost:11434/v1` for Ollama). |
| `use_llm_judge` | `bool` | `False` | When `True`, runs a semantic LLM-as-a-judge audit verifying thought-observation faithfulness. |
| `min_tool_selection` | `float` | `0.85` | Minimum Tool Selection F1 threshold required to pass. |
| `min_argument_correctness` | `float` | `0.85` | Minimum argument schema correctness score. |
| `min_order_accuracy` | `float` | `1.00` | Minimum prerequisite sequence adherence score. |
| `min_trace_efficiency` | `float` | `0.70` | Minimum step efficiency and loop avoidance threshold. |

---

## Framework Adapters

### 1. LangChain Callback Tracer
```python
from regression_shield import RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler(
    api_key="your-api-key",
    model="gpt-4o-mini",
)

# Attach handler to any LangChain agent run:
agent_executor.invoke({"input": "Transfer $4,500 to ACCT-9912"}, config={"callbacks": [handler]})

# Evaluate the recorded trace:
report = handler.evaluate(scenario)
report.print_diagnostics()
```

### 2. Hugging Face smolagents Adapter
```python
from smolagents import CodeAgent, InferenceClientModel
from regression_shield.adapters.smolagents import evaluate_smolagent

agent = CodeAgent(tools=[...], model=InferenceClientModel())
agent.run("Execute customer refund")

# Extract and evaluate execution trace
report = evaluate_smolagent(agent, scenario=refund_policy)
print("Agent Passed:", report.passed)
```

### 3. Zero-Code Evaluation Decorator
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

---

## Command-Line Interface (`regshield`)

RegressionShield installs the standalone `regshield` binary:

```bash
# 1. Evaluate agent execution traces from a JSON benchmark file:
regshield eval --file examples/sample_scenarios.json

# 2. Evaluate with a custom model and API key:
regshield eval --file my_traces.json \
  --api-key "your-api-key" \
  --model "minimax/minimax-m2.7:free" \
  --base-url "https://openrouter.ai/api/v1" \
  --llm-judge \
  --min-tool-selection 0.90

# 3. Start the dynamic dashboard server:
regshield serve --port 8000 --model "minimax/minimax-m2.7:free"
```

---

## REST Ingestion Server (`POST /api/evaluate-trace`)

External agents written in any language (Python, TypeScript, Go, Rust, cURL) can post execution traces directly to the RegressionShield server:

```bash
# Start the ingestion server:
regshield serve --port 8000
```

Post an agent trace:
```bash
curl -X POST http://localhost:8000/api/evaluate-trace \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "WIRE_001",
    "expected_tools": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "expected_order": ["verify_identity", "check_balance", "execute_wire_transfer"],
    "model": "gpt-4o-mini",
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

Response format:
```json
{
  "status": "success",
  "scenario_id": "WIRE_001",
  "status_code": "PASSED",
  "composite_score": 1.0,
  "metrics": {
    "tool_selection": 1.0,
    "argument_correctness": 1.0,
    "call_ordering": 1.0,
    "step_efficiency": 1.0,
    "reasoning_faithfulness": 1.0
  },
  "failures": []
}
```

Check health and active model configuration:
```bash
curl http://localhost:8000/api/status
```

---

## Automated Testing (Pytest)

Run all unit, metric, and SDK integration tests (100% pass rate, offline and deterministic):

```bash
pytest -v tests/
```

---

## Repository Structure

```
RL environments/ (Branch: SDK)
├── regression_shield/
│   ├── __init__.py               # Top-level SDK API (evaluate_trace, AgentTraceEvaluator, LLMJudge)
│   ├── models.py                 # Dataclass models (StepTrace, ScenarioSpec, EvaluationReport)
│   ├── cli.py                    # regshield CLI implementation (eval, serve, demo)
│   ├── server.py                 # Dynamic web dashboard and REST ingestion server
│   ├── core/
│   │   ├── agent_metrics.py      # Core reasoning metrics (ToolSelection, Arguments, Order, Efficiency, Faithfulness)
│   │   ├── trace_evaluator.py    # Central execution trace evaluation orchestrator
│   │   └── llm_judge.py          # OpenAI-compatible semantic LLM judge
│   └── adapters/
│       ├── langchain.py          # LangChain callback handler tracer
│       ├── smolagents.py         # Hugging Face smolagents trace extractor & evaluator
│       └── decorator.py          # @evaluate_agent_trace convenience decorator
├── dashboard/
│   ├── index.html                # Visual ReAct trace and evaluation dashboard
│   ├── styles.css                # Dark glassmorphic dashboard styling
│   └── app.js                    # Live evaluation and polling logic
├── examples/
│   ├── quickstart_sdk.py         # 2-line quickstart with custom api_key and model
│   └── sample_scenarios.json     # Curated benchmark scenarios
├── tests/
│   ├── test_agent_reasoning.py   # Unit tests for reasoning metrics
│   └── test_sdk.py               # Unit tests for SDK, CLI, and LLM judge
├── pyproject.toml                # Package configuration and entrypoint (regshield)
└── README.md                     # Documentation
```

---

## License
MIT License.
