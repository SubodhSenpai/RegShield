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

### Block dangerous arguments

When a tool is generic (SQL, shell, HTTP, file paths), the danger is in its arguments. `forbidden_arguments` maps a tool (or `"*"` for any tool) to argument patterns it must never get. Patterns are regular expressions, matched case-insensitively.

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "code_freeze",
    "forbidden_arguments": {"run_sql": {"query": r"\b(insert|update|delete|drop|truncate|alter)\b"}},
}
trace = [
    {"action": {"name": "run_sql", "args": {"query": "SELECT id, email FROM users"}}, "observation": "3 rows"},
    {"action": {"name": "run_sql", "args": {"query": "DELETE FROM users WHERE id = 2"}}, "observation": "1 row"},
]
print(*evaluate_trace(scenario, trace).failures, sep="\n")
```

```text
Policy: Step 2: run_sql.query matches forbidden pattern /\b(insert|update|delete|drop|truncate|alter)\b/: 'DELETE FROM users WHERE id = 2'
```

Use `"*"` as the argument name to check every argument: `{"run_shell": {"*": r"rm\s+-rf"}}`.

### Deploy only if the tests passed

`expected_order` checks that the tests ran first, not that they passed. `prerequisites` needs each prerequisite's latest result before the call to be a success.

```python
from regression_shield import evaluate_trace

scenario = {"scenario_id": "deploy_gate", "prerequisites": {"deploy": ["run_tests"]}}
trace = [
    {"action": {"name": "run_tests", "args": {}}, "observation": "ERROR: 3 failed, 41 passed"},
    {"action": {"name": "deploy", "args": {"env": "prod"}}, "observation": "DEPLOYED"},
]
print(*evaluate_trace(scenario, trace).failures, sep="\n")
```

```text
Policy: Step 2: 'deploy' ran after its prerequisite 'run_tests' failed (step 1)
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

Objects and lists are compared item by item with the same rules, so key order and `2` versus `2.0` don't matter. Lists keep their order, and booleans only match booleans:

```python
from regression_shield import evaluate_trace

scenario = {
    "scenario_id": "order",
    "expected_arguments": {"place_order": {"items": [{"sku": "A-1", "qty": 2}], "gift_wrap": True}},
}
trace = [{"action": {"name": "place_order", "args": {"items": [{"qty": 2.0, "sku": "a-1"}], "gift_wrap": 1}},
          "observation": "PLACED"}]
print(*evaluate_trace(scenario, trace).failures, sep="\n")
```

```text
Argument correctness 0.50 < 0.85: place_order.gift_wrap was 1, expected True
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

A result counts as a failure when it starts with `ERROR`, when a JSON result reports one (an `error` field, `"success": false`, a status like `"declined"`, an HTTP error code, a non-zero `exit_code`), or when the text says so ("failed", "403 Forbidden"). `"error": null`, "0 errors" and `error_rate` don't count.

### Catch claims the trace contradicts

A claim about a specific tool is checked against that tool's own result, even after other calls. Messages the agent sends (email, reply, notify... tools) are checked too: this agent's refund failed, and it told the customer it went through.

```python
from regression_shield import evaluate_trace

trace = {
    "steps": [
        {"action": {"name": "issue_refund", "args": {"order_id": "A-1"}},
         "observation": '{"status": "failed", "error": "card_expired"}'},
        {"action": {"name": "send_email", "args": {"to": "jo@shop.example", "body": "Your refund has been processed."}},
         "observation": "sent"},
    ],
    "final_response": "Your refund has been issued and I've emailed you a confirmation.",
}
print(*evaluate_trace({"scenario_id": "refund_email"}, trace).failures, sep="\n")
```

```text
Reasoning faithfulness 0.00 < 0.85: Step 2: message sent with 'send_email' claims 'issue_refund' succeeded, but it failed (step 1); Final response claims 'issue_refund' succeeded, but it failed (step 1)
```

A claim that an action was done by a tool that never ran ("your order has been refunded", "I called export_data") is flagged too, for the tools the trace or the scenario names. "I've emailed you" stays fine here: that call succeeded.

This check reads wording, not meaning. An answer that says "refunded $500" when the tool refunded $50 needs the LLM judge (next recipe).

### Judge answers with a local model

The judge reads the whole trace and scores whether the answer is backed by the tool results. Any OpenAI-compatible server works, including Ollama on your machine:

```bash
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export JUDGE_MODEL=qwen2.5:3b
regshield eval scenarios.json --llm-judge
```

In Python, pass `use_llm_judge=True` to `evaluate_trace`. If the judge can't answer (rate limit, bad reply), the scenario fails unless you pass `judge_on_error="pass"`. A small local model can be slow: raise the 30-second limit with `judge_timeout=120` or `--judge-timeout 120`. Each verdict also records the judge's own token usage and cost (`report.judge_audit["usage"]`, `["cost_usd"]`).

## Cost

### Cap what a run may cost

Record each model call's token usage with the trace (`llm_calls`) and set a budget. The LangChain/LangGraph handler and `instrument_smolagents` record usage for you; elsewhere call `recorder.llm_response(response)` with the SDK's response.

```python
from regression_shield import evaluate_trace

trace = {
    "steps": [{"action": {"name": "export_report", "args": {"month": "2026-09"}}, "observation": "exported"}],
    "llm_calls": [{"model": "gpt-4o", "input_tokens": 9000, "output_tokens": 300}] * 5,
}
scenario = {"scenario_id": "monthly_report", "max_cost_usd": 0.10, "max_llm_calls": 4}
report = evaluate_trace(scenario, trace)
print(report.format())
```

```text
FAILED  monthly_report  (composite 1.00)
  tool_selection          1.00
  argument_correctness    1.00
  call_ordering           1.00
  step_efficiency         1.00
  reasoning_faithfulness  1.00
  pattern checks: Budget FAIL
  cost: $0.1275 (5 LLM calls, 46,500 tokens)
Failures:
  - Budget: Cost $0.1275 is over the $0.1000 budget (gpt-4o $0.1275); 5 LLM calls (max 4)
```

Calls are priced from a bundled snapshot of public list prices (`report.cost` shows which entry matched). A cost the provider reported in the trace wins, and you can set your own prices, including for paid tools: `evaluate_trace(..., pricing={"models": {"my-finetune*": {"input": 1.0, "output": 4.0}}, "tools": {"web_search": 0.005}})`, in USD per million tokens and per call. `max_tokens` caps input plus output tokens.

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

### Run the agent several times

An agent that passes once can fail the next run. Record the same task a few times and evaluate the runs together:

```python
from regression_shield import evaluate_runs

scenario = {"scenario_id": "refund", "expected_arguments": {"issue_refund": {"amount": 50}}}
runs = [[{"action": {"name": "issue_refund", "args": {"amount": amount}}, "observation": "REFUNDED"}]
        for amount in (50, 50, 500, 50)]
print(evaluate_runs(scenario, runs).format())
```

```text
FAILED  refund  (3/4 runs passed, pass rate 0.75, required 1.00)
  run 1: PASSED
  run 2: PASSED
  run 3: FAILED  Argument correctness 0.00 < 0.85: issue_refund.amount was 500, expected 50
  run 4: PASSED
Failures:
  - 3/4 runs passed (pass rate 0.75, required 1.00)
  - Argument correctness in 1/4 runs
```

By default every run must pass. Pass `min_pass_rate=0.8` to accept some failures. In a scenario file, give an item `traces` (a list of runs) instead of `trace`; `regshield eval --min-pass-rate 0.8` sets the rate.

### Roll out a new check without failing CI

List checks in `warn_only` to report their failures as warnings while you tune them:

```python
from regression_shield import evaluate_trace

scenario = {"scenario_id": "refund", "max_tool_calls": {"issue_refund": 1}, "warn_only": ["policy"]}
trace = [{"action": {"name": "issue_refund", "args": {"order_id": "A-1"}}, "observation": "REFUNDED"}] * 2
report = evaluate_trace(scenario, trace)
print(report.passed)
print(*report.warnings, sep="\n")
```

```text
True
Policy: 'issue_refund' was called 2 times (max 1)
```

`warn_only` takes the five metric names (`reasoning_faithfulness`...), the pattern checks (`policy`, `human_approval`, `budget`...) and `llm_judge`.

### Share settings between pytest and CI

Put thresholds, judge settings and prices in `pyproject.toml` (or a `regshield.toml`), and both `evaluate_trace` and `regshield eval` use them. Arguments and command-line flags still win:

```toml
[tool.regshield]
min_tool_selection = 0.9
judge_model = "qwen2.5:3b"
judge_base_url = "http://127.0.0.1:11434/v1"
judge_timeout = 120

[tool.regshield.pricing.models]
"qwen*" = { input = 0, output = 0 }

[tool.regshield.pricing.tools]
web_search = 0.005
```

API keys stay in environment variables. See [Configuration](reference.md#configuration-file) for every setting.

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
