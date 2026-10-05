# Cookbook

Short recipes for the checks people ask about most. Each one is a scenario, a trace that breaks it, and what RegShield prints. The outputs are real: the test suite runs every recipe and compares.

The traces here are written by hand to keep the recipes short. In a real project you record them from your agent (see [Record a LangChain, LangGraph or smolagents agent](#record-a-langchain-langgraph-or-smolagents-agent)).

## Guard actions

### Run the tests before a deploy

`expected_order` lists tools that must run in that order. `expected_arguments` pins the values that matter.

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

### Never call a dangerous tool, and refund once at most

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "support_policy",
    "forbidden_tools": ["delete_account"],
    "max_tool_calls": {"issue_refund": 1},
}
trace = [
    {"action": {"name": "issue_refund", "args": {"order_id": "A-1"}}, "observation": "REFUNDED"},
    {"action": {"name": "issue_refund", "args": {"order_id": "A-1"}}, "observation": "REFUNDED"},
    {"action": {"name": "delete_account", "args": {"user_id": "u-9"}}, "observation": "DELETED"},
]
print(*evaluate_trace(scenario, trace).failures, sep="\n")
```

```text
Policy: Step 3: called forbidden tool 'delete_account'; 'issue_refund' was called 2 times (max 1)
```

### Ask a person before refunding

List the tools that need approval in `requires_approval`. Each call needs its own approval, and a call after a denial always fails.

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()

@recorder.tool
def issue_refund(order_id: str, amount: float) -> str:
    return "REFUNDED"

recorder.approval("issue_refund", approved=False, by="lead@shop.example")
issue_refund("A-1", 89.0)  # the agent refunds anyway

report = evaluate_trace({"scenario_id": "refund", "requires_approval": ["issue_refund"]}, recorder)
print(*report.failures, sep="\n")
```

```text
Human Approval: Step 2: 'issue_refund' ran after its approval was denied
```

With LangChain's `HumanInTheLoopMiddleware`, the callback handler records the approve and reject decisions for you.

### Check the arguments

Numbers compare as numbers (`"431.20"` equals `431.2`). Text ignores case, spaces at the ends, `_` and `-`.

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "convert_invoice",
    "expected_arguments": {"convert": {"amount": 431.2, "currency": "gbp"}},
}
trace = [{"action": {"name": "convert", "args": {"amount": "1", "currency": "GBP"}}, "observation": "0.79"}]
print(*evaluate_trace(scenario, trace).failures, sep="\n")
```

```text
Argument correctness 0.50 < 0.85: convert.amount was '1', expected 431.2
```

## Check the answer

### Catch "done!" after a failed call

A thought or final answer that claims success right after a tool error, or after a person denied the action, is flagged.

```python
from regression_shield import evaluate_trace

trace = {
    "steps": [
        {"action": {"name": "issue_refund", "args": {"order_id": "A-1"}},
         "observation": "ERROR: payment gateway timeout"},
    ],
    "final_response": "Good news: your refund has been processed!",
}
print(*evaluate_trace({"scenario_id": "refund_answer"}, trace).failures, sep="\n")
```

```text
Reasoning faithfulness 0.00 < 0.85: Final response claims success right after an error
```

This check reads wording, not meaning. An answer that says "refunded $500" when the tool refunded $50 needs the LLM judge (next recipe).

### Judge answers with a local model

The judge reads the whole trace and scores whether the answer is backed by the tool results. Any OpenAI-compatible server works, including Ollama on your machine:

```bash
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export JUDGE_MODEL=qwen2.5:3b
regshield eval scenarios.json --llm-judge
```

In Python, pass `use_llm_judge=True` to `evaluate_trace`. If the judge can't answer (rate limit, bad reply), the scenario fails unless you pass `judge_on_error="pass"`.

## Agent patterns

### Stop an agent that loops

```python
from regression_shield import evaluate_trace

scenario = {"scenario_id": "search", "expected_tools": ["search"], "optimal_step_count": 1}
step = {"action": {"name": "search", "args": {"q": "refund policy"}}, "observation": "no results"}
print(*evaluate_trace(scenario, [step, step, step]).failures, sep="\n")
```

```text
Step efficiency 0.00 < 0.70: 3 steps for an optimal 1, 2 repeated call(s)
```

For a hard limit on one tool, add `"max_tool_calls": {"search": 2}`.

### Keep each agent to its own tools

`agent_tools` says which tools each agent may use. `expected_agents` checks who acted, in order.

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder(agent="triage")
recorder.tool_call("lookup_order", {"order_id": "A-1"}, "shipped")
recorder.tool_call("issue_refund", {"order_id": "A-1"}, "REFUNDED")  # billing's job
recorder.handoff("billing")

report = evaluate_trace({
    "scenario_id": "support_team",
    "agent_tools": {"triage": ["lookup_order"], "billing": ["issue_refund"]},
    "expected_agents": ["triage", "billing"],
}, recorder)
print(*report.failures, sep="\n")
```

```text
Multi-Agent: Step 2: agent 'triage' called 'issue_refund', which isn't in its allowed tools
```

LangGraph supervisor and swarm graphs need no recording code: the callback handler tags each step with its agent and turns `transfer_to_<agent>` calls into handoffs.

### Check where a router sent the request

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
recorder.route("sales", thought="The customer mentions an invoice.")
print(*evaluate_trace({"scenario_id": "router", "expected_route": "billing"}, recorder).failures, sep="\n")
```

```text
Routing: Routed to 'sales', expected 'billing'
```

`regshield eval` also prints routing accuracy across every scenario in the file.

### Make independent calls run in parallel

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
recorder.tool_call("get_weather", {"city": "Lisbon"}, "24C")
recorder.tool_call("get_flights", {"city": "Lisbon"}, "$412")

scenario = {"scenario_id": "trip", "expected_parallel": [["get_weather", "get_flights"]]}
print(*evaluate_trace(scenario, recorder).failures, sep="\n")
```

```text
Parallel Calls: get_weather, get_flights should run in parallel but ran one after another
```

Record concurrent calls inside `with recorder.parallel():`. The LangChain handler and `instrument_smolagents` group them for you.

### Allow only certain graph transitions

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
for node in ["draft", "review", "draft", "publish"]:
    recorder.node(node)

report = evaluate_trace({
    "scenario_id": "content_graph",
    "allowed_transitions": {"draft": ["review"], "review": ["draft", "publish"]},
    "max_node_visits": {"review": 3},
}, recorder)
print(*report.failures, sep="\n")
```

```text
Graph Transitions: Step 4: 'draft' -> 'publish' is not an allowed transition
```

With LangGraph, each node the graph runs is recorded automatically. Nodes that ran in the same step (fan-out) count as one layer, so you only list real edges.

### End a writer and critic loop on an approved draft

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
recorder.draft("Buy now!!!")
recorder.critique(approved=False, feedback="Too pushy.")
recorder.draft("Buy now!!!")  # nothing changed
recorder.critique(approved=False, feedback="Still too pushy.")

print(*evaluate_trace({"scenario_id": "ad_copy", "max_revision_rounds": 3}, recorder).failures, sep="\n")
```

```text
Reflection Loop: Step 3: revision is unchanged after the critique at step 2; Step 4: the final draft was rejected by the evaluator
```

### Plan first, and replan after a failure

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()
recorder.plan(["search_flights", "book_flight", "send_confirmation"])
recorder.tool_call("search_flights", {"to": "LIS"}, "ERROR: timeout")
recorder.tool_call("book_flight", {"flight": "TP-123"}, "BOOKED")

print(*evaluate_trace({"scenario_id": "trip", "require_plan": True}, recorder).failures, sep="\n")
```

```text
Plan & Execute: Planned step 'send_confirmation' never ran; Step 3: continued with 'book_flight' after 'search_flights' failed (step 2) without replanning
```

## Workflow

### Record a LangChain, LangGraph or smolagents agent

```python
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace, instrument_smolagents

# LangChain agents, chains and compiled LangGraph graphs
handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})
report = evaluate_trace(scenario, handler)

# smolagents: CodeAgent or ToolCallingAgent, before the run
recorder = instrument_smolagents(agent)
agent.run(task)
report = evaluate_trace(scenario, recorder)
```

Any other framework: wrap your tools with a `TraceRecorder` (`search = recorder.wrap(search)`) and pass the recorder to `evaluate_trace`. See [Integrations](integrations.md).

### Fail a pytest test with the reasons

```python
from regression_shield import evaluate_trace

def test_deploy_gate():
    trace = run_my_agent("Deploy to staging")  # your agent, recorded
    evaluate_trace(SCENARIO, trace).raise_for_failures()
```

```console
$ pytest -q --tb=short
F                                                                        [100%]
______________________________ test_deploy_gate _______________________________
E   regression_shield.models.EvaluationFailed: deploy_gate failed:
E     - Argument correctness 0.00 < 0.85: deploy.env was 'prod', expected 'staging'
E     - Call ordering 0.00 < 1.00: 'deploy' (step 1) ran before its prerequisite 'run_tests' (step 2)
1 failed in 0.33s
```

### Gate pull requests

Save scenarios with recorded traces in a JSON file. A `regression_trace` is optional: a known-bad trace the scenario must catch.

```json
[
  {
    "scenario": {"scenario_id": "deploy_gate", "expected_order": ["run_tests", "deploy"]},
    "trace": [
      {"action": {"name": "run_tests", "args": {}}, "observation": "42 passed"},
      {"action": {"name": "deploy", "args": {"env": "staging"}}, "observation": "DEPLOYED"}
    ],
    "regression_trace": [
      {"action": {"name": "deploy", "args": {"env": "staging"}}, "observation": "DEPLOYED"}
    ]
  }
]
```

```yaml
# .github/workflows/agents.yml
on: [pull_request]
jobs:
  agents:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install regression-shield
      - run: regshield eval scenarios.json
```

```console
$ regshield eval scenarios.json
Evaluating 1 scenario(s) from scenarios.json

PASS  deploy_gate  (composite 1.00)

1/1 scenario(s) passed. Regressed traces caught: 1/1.
```

`regshield eval` exits with 0 when everything passes, 1 when a scenario fails or a regression trace slips through, and 2 on bad input.

### Set a stricter threshold

Each of the five scores has a threshold you can change. Here the tool selection F1 of 0.89 passes the default 0.85 but not 0.94:

```python
from regression_shield import evaluate_trace

scenario = {"scenario_id": "triage", "expected_tools": ["lookup_order", "check_stock", "refund", "notify"]}
trace = [{"action": {"name": name, "args": {}}, "observation": "ok"}
         for name in ["lookup_order", "check_stock", "refund", "notify", "send_survey"]]
print(evaluate_trace(scenario, trace).passed)
print(*evaluate_trace(scenario, trace, min_tool_selection=0.94).failures, sep="\n")
```

```text
True
Tool selection 0.89 < 0.94: unexpected ['send_survey']
```

On the command line: `regshield eval scenarios.json --min-tool-selection 0.94`.

### See every run in the dashboard

```python
evaluate_trace(scenario, trace, save_report=True)  # adds it to reports/latest_report.json
```

```bash
regshield serve  # http://localhost:8000
```

The dashboard shows each scenario's scores, pattern checks and steps, and puts every regression trace next to the trace that passed. It runs on your machine and needs no account. To send reports from another process, call `report.sync_to_dashboard("http://localhost:8000")`.
