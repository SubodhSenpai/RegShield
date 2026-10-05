# Cookbook

Short recipes for the checks people ask about most. Most are a scenario, a trace that breaks it, and what RegShield prints. The [In production](#in-production) ones show the same rules guarding a running agent. The outputs are real: the test suite runs every recipe and compares.

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

The judge reads the whole trace and scores whether the answer is backed by the tool results. Any OpenAI-compatible server works, including Ollama on your machine. After `ollama pull qwen2.5:7b`, set it in `pyproject.toml`; a server on your own machine or network needs no API key:

```toml
[tool.regshield]
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
judge_timeout = 120
```

Or for one run: `regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b`. The same works for vLLM, LM Studio or llama.cpp on your servers. Step-by-step setup, every setting, CI and troubleshooting are in [Local models with Ollama](#local-models-with-ollama).

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

Calls are priced from a bundled snapshot of public list prices (`report.cost` shows which entry matched). A cost the provider reported in the trace wins, and you can set your own prices, including for paid tools: `evaluate_trace(..., pricing={"models": {"my-finetune*": {"input": 1.0, "output": 4.0}}, "tools": {"web_search": 0.005}})`, in USD per million tokens and per call. `max_tokens` caps input plus output tokens. Run `regshield pricing refresh` to update the list prices.

### Mix local models and paid APIs

Each model call is priced on its own. A local model (an Ollama name like `qwen2.5:7b`, or one served by LM Studio or your own vLLM) costs nothing per token, so a run that mixes local and paid models costs only its paid calls:

```python
from regression_shield import evaluate_trace

trace = {
    "steps": [{"action": {"name": "lookup_order", "args": {"order_id": "A-1"}}, "observation": "DELIVERED"}],
    "llm_calls": [
        {"model": "qwen2.5:7b", "input_tokens": 9000, "output_tokens": 600},  # on your own GPU
        {"model": "gpt-4o-mini", "input_tokens": 1200, "output_tokens": 80},  # a paid API
    ],
}
report = evaluate_trace({"scenario_id": "hybrid", "max_cost_usd": 0.01}, trace)
for model, usage in report.cost["models"].items():
    print(f"{model}: ${usage['usd']:.6f} ({usage['price_source']})")
priced = evaluate_trace({"scenario_id": "hybrid"}, trace, pricing={"models": {"qwen2.5*": {"input": 0.05, "output": 0.10}}})
print(f"with a GPU price: ${priced.cost['total_usd']:.6f}")
```

```text
qwen2.5:7b: $0.000000 (local)
gpt-4o-mini: $0.000228 (snapshot)
with a GPU price: $0.000738
```

To account for your hardware, give local models a price per million tokens, as above. `max_cost_usd` can't stop a free model, so cap local runs with `max_tokens` or `max_llm_calls`.

## In production

The same rules can protect a running agent. More in [In production](production.md).

### Block a dangerous call while the agent runs

Give the recorder a `Guard` built from your scenario. A call that breaks a rule doesn't run: `ActionBlocked` says why, and the attempt is recorded.

```python
from regression_shield import ActionBlocked, Guard, TraceRecorder

guard = Guard({"forbidden_arguments": {"run_sql": {"query": r"\b(drop|delete|truncate)\b"}}})
recorder = TraceRecorder(guard=guard)

@recorder.tool
def run_sql(query: str) -> str:
    return "3 rows"

print(run_sql("SELECT * FROM users LIMIT 3"))
try:
    run_sql("DROP TABLE users")
except ActionBlocked as blocked:
    print(blocked)
print(recorder.get_trace()[1]["blocked"]["rule"])
```

```text
3 rows
Blocked by policy: run_sql.query matches forbidden pattern /\b(drop|delete|truncate)\b/: 'DROP TABLE users'. This action did not run.
forbidden_arguments
```

With LangChain, the guard goes in the handler and its middleware goes in the agent. A blocked call then comes back to the model as an error tool message, and the agent carries on:

```python
handler = RegressionShieldCallbackHandler(guard=guard)
agent = create_agent(model, tools=[run_sql], middleware=[handler.middleware()])
agent.invoke({"messages": [{"role": "user", "content": "Clean up the users table"}]}, config={"callbacks": [handler]})
```

### Ask a manager before a large refund

An `approver` is asked at the moment a `requires_approval` tool is about to run. Its answer is recorded as an approval, and a "no" blocks the call.

```python
from regression_shield import ActionBlocked, Guard, TraceRecorder

def manager_approves(tool, args):
    return args["amount"] <= 200  # in real life: ask in Slack, a dashboard or a CLI prompt

recorder = TraceRecorder(guard=Guard({"requires_approval": ["issue_refund"]}, approver=manager_approves))
issue_refund = recorder.tool(lambda order_id, amount: f"refunded ${amount}", name="issue_refund")

print(issue_refund("A-1001", 49.99))
try:
    issue_refund("A-1002", 850)
except ActionBlocked as blocked:
    print(blocked.reason)
for step in recorder.get_trace():
    action = step["action"]
    if action["type"] == "approval":
        print(f"approval by {action['by']}: {'yes' if action['approved'] else 'no'}")
    else:
        print(f"{action['name']}({action['args']['amount']}): {'blocked' if step.get('blocked') else 'ran'}")
```

```text
refunded $49.99
approval for 'issue_refund' was denied
approval by approver: yes
issue_refund(49.99): ran
approval by approver: no
issue_refund(850): blocked
```

Without an approver, the call waits for an approval you record with `recorder.approval("issue_refund", approved=True, by="alice")`.

### Try a new rule without blocking anything

`warn_only=True` lets every call run. Each one that would have been blocked is logged and marked on its step, and exported runs show it. Watch it for a while, then switch blocking on.

```python
from regression_shield import Guard, TraceRecorder

recorder = TraceRecorder(guard=Guard({"forbidden_tools": ["delete_user"]}, warn_only=True))
delete_user = recorder.tool(lambda user_id: "deleted", name="delete_user")
print(delete_user("u-1"))
print(recorder.get_trace()[0]["guard_warning"])
```

```text
deleted
{'rule': 'forbidden_tools', 'reason': "'delete_user' is a forbidden tool"}
```

A scenario's own `warn_only` list (`["budget"]`, `["policy"]`...) does the same for just those checks.

### Rate-limit an action across runs

Share one guard between runs, and the limit holds across all of them.

```python
from regression_shield import ActionBlocked, Guard, TraceRecorder

guard = Guard(rate_limits={"send_email": "2/minute"})
for customer in ["ana@shop.co", "ben@shop.co", "cy@shop.co"]:
    recorder = TraceRecorder(guard=guard)  # one run per customer
    send_email = recorder.tool(lambda to: f"sent to {to}", name="send_email")
    try:
        print(send_email(customer))
    except ActionBlocked as blocked:
        print(blocked.reason)
```

```text
sent to ana@shop.co
sent to ben@shop.co
'send_email' hit the rate limit of 2 per minute
```

### Stop a runaway agent at its budget

`instrument()`, the LangChain middleware and `instrument_smolagents` check the budget before each model call; `check_llm()` is the same check for your own loop.

```python
from regression_shield import ActionBlocked, Guard, TraceRecorder

recorder = TraceRecorder(guard=Guard({"max_cost_usd": 0.05}))
try:
    while True:  # an agent that never finishes on its own
        recorder.check_llm()
        recorder.llm_call("gpt-4o", input_tokens=8000, output_tokens=400)
except ActionBlocked as blocked:
    print(blocked.reason)
print(len(recorder.llm_calls), "model calls")
```

```text
the run has spent $0.0720 of its $0.0500 budget
3 model calls
```

A call's cost is only known once it returns, so a run can go over its budget by one model call.

### Record a raw SDK agent without changing it

`instrument()` records OpenAI, Anthropic and Gemini SDK calls made inside a `with recorder:` block, including the tool calls the model asked for and the results your code sent back.

```python
import regression_shield as rs

rs.instrument()  # once, at startup

with rs.TraceRecorder(guard=guard) as recorder:
    answer = my_agent(question)  # your own loop on the SDK, unchanged
report = rs.evaluate_trace(scenario, recorder)
```

With a guard, a reply asking for a blocked call raises `ActionBlocked` from the SDK call, before your code can run it.

### Send runs to your monitoring service

`export_traces` streams every run as events. `OpenTelemetryExporter(endpoint="http://localhost:4318")` sends them as spans, `JSONLExporter` to a file, `HTTPExporter` to any URL; here a small exporter of our own prints them.

```python
from regression_shield import Exporter, TraceRecorder, export_traces, stop_exporting

class Show(Exporter):
    def export(self, event):
        print(" ".join(str(v) for v in (event["event"], event.get("tool"), event.get("status")) if v))

export_traces(Show(), sample_rate=1.0)
recorder = TraceRecorder()
recorder.tool_call("lookup_order", {"order_id": "A-1"}, "DELIVERED")
recorder.tool_call("issue_refund", {"order_id": "A-1"}, "ERROR: gateway timeout")
recorder.end_run()
stop_exporting()
```

```text
run_start
tool_call lookup_order ok
tool_call issue_refund error
run_end ok
```

With `sample_rate=0.1`, a tenth of healthy runs is exported, plus every run where something went wrong (`keep_errors`). Prompts, arguments and results stay out unless the exporter has `capture_content=True`.

### Keep model prices current

Providers change prices often. RegShield ships with a dated list of public prices. Refresh it whenever you like:

```bash
regshield pricing refresh                          # download the latest list prices
regshield pricing show gpt-4o claude-sonnet-4-5    # the price RegShield uses for each model
```

The refreshed list is saved in your user cache and used from then on. `pricing refresh` also tells you which prices changed. For the same numbers on every machine and in CI, save the list in your repository with `--output prices.json` and set `REGSHIELD_PRICE_LIST=prices.json`. `pricing show` exits with 1 when a model has no price, so CI can check that every model you use is priced.

## Local models with Ollama

Run the LLM judge, and your agents, on your own GPU or servers instead of a paid API. Nothing leaves your infrastructure, and calls cost nothing per token. These recipes go from installing Ollama to running the judge in CI. [Local and self-hosted models](local-models.md) has the overview.

### Install Ollama and pull a model

| System | Install |
|---|---|
| Windows | Run the installer from [ollama.com/download](https://ollama.com/download). Ollama runs in the background (tray icon) and starts when you log in. |
| macOS | Install the app from [ollama.com/download](https://ollama.com/download), or `brew install ollama` and then `ollama serve`. |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` installs Ollama and starts it as a service. |
| Docker | `docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama` (leave out `--gpus=all` without an NVIDIA GPU) |

Then download a model and check that it answers:

```bash
ollama pull qwen2.5:7b                  # download the model (about 4.7 GB)
ollama run qwen2.5:7b "Say hello"       # a quick check that it answers
curl http://localhost:11434/v1/models   # the OpenAI-compatible API RegShield talks to
```

| GPU memory | Model | Notes |
|---|---|---|
| 4 GB | `qwen2.5:3b` | Fine for short traces; RegShield's own real-agent tests run on one |
| 8 GB | `qwen2.5:7b`, `llama3.1:8b` | A good default for the judge and for tool-calling agents |
| 16 GB or more | `qwen2.5:14b` | Long traces and harder cases |
| No GPU | `qwen2.5:3b` | Runs on the CPU, more slowly; raise `judge_timeout` |

To keep everything on your own machines, start Ollama with `OLLAMA_NO_CLOUD=1`. Without it, models with a `-cloud` tag (`gpt-oss:120b-cloud`) run on Ollama's servers.

### Point the LLM judge at Ollama

Put the settings in `pyproject.toml`, so pytest and CI share them. A `regshield.toml` works too, without the `[tool.regshield]` line. A server on your machine or private network needs no API key:

```toml
[tool.regshield]
llm_judge = true                               # judge every trace
judge_base_url = "http://localhost:11434/v1"   # Ollama's OpenAI-compatible API
judge_model = "qwen2.5:7b"                     # exactly as `ollama list` shows it
judge_timeout = 120                            # seconds; the first call also loads the model
judge_on_error = "fail"                        # "pass" to ignore a judge that can't answer
```

```bash
regshield eval scenarios.json
```

This is real output from qwen2.5 3B on a 4 GB laptop GPU. The trace's answer says "I refunded $500" while the tool refunded $50:

```text
FAIL  refund_overstated  (composite 1.00)
      LLM judge (qwen2.5-16k:3b): 0.00  The tool returned a refund of $50 for order A-1, but the final response claims a refund of $500.
      - LLM judge (qwen2.5-16k:3b): The tool returned a refund of $50 for order A-1, but the final response claims a refund of $500.
LLM judge: 2 calls, 614 tokens, $0.0000
```

Every metric scores 1.00 here; only the judge, which reads meaning, sees the mistake. It costs nothing because the model is local.

### Every way to set the judge

| Setting | `[tool.regshield]` | Environment variable | Command line | Python argument |
|---|---|---|---|---|
| Turn the judge on | `llm_judge = true` | `REGSHIELD_LLM_JUDGE=true` | `--llm-judge` (`--no-llm-judge` turns it off) | `use_llm_judge=True` |
| Server address | `judge_base_url` | `REGSHIELD_JUDGE_BASE_URL` (or `OPENAI_BASE_URL`) | `--base-url` | `base_url=` |
| Model | `judge_model` | `REGSHIELD_JUDGE_MODEL` (or `JUDGE_MODEL`) | `--model` | `model=` |
| Seconds to wait for each verdict | `judge_timeout` (default 30) | `REGSHIELD_JUDGE_TIMEOUT` (or `JUDGE_TIMEOUT`) | `--judge-timeout` | `judge_timeout=` |
| When the judge can't answer | `judge_on_error = "fail"` (default) or `"pass"` | `REGSHIELD_JUDGE_ON_ERROR` | `--judge-on-error` | `judge_on_error=` |
| API key, for hosted APIs or a server that checks keys | never in the file: the environment, or the `env_file` it names | `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | `--api-key` | `api_key=` |
| Your own price for the model | `[tool.regshield.pricing.models]` | | | `pricing=` |

A command-line flag or Python argument wins over an environment variable, which wins over the file. `regshield config show` prints the judge RegShield would use, and where each setting came from. To judge many traces with the same settings from Python:

```python
from regression_shield import AgentTraceEvaluator

evaluator = AgentTraceEvaluator(use_llm_judge=True, base_url="http://localhost:11434/v1",
                                model="qwen2.5:7b", judge_timeout=120)
report = evaluator.evaluate(scenario, trace)
```

RegShield sends no key to a server on this machine, a private network address, or an internal host name such as a Docker or Kubernetes service:

```python
from regression_shield import LLMJudge

for url in ["http://localhost:11434/v1", "http://ollama:11434/v1", "http://192.168.1.50:8000/v1",
            "https://openrouter.ai/api/v1"]:
    judge = LLMJudge(base_url=url, model="qwen2.5:7b")
    print(f"{judge.base_url:30} key needed: {judge.needs_key}")
```

```text
http://localhost:11434/v1      key needed: False
http://ollama:11434/v1         key needed: False
http://192.168.1.50:8000/v1    key needed: False
https://openrouter.ai/api/v1   key needed: True
```

### Run your agent on Ollama

Point your SDK or framework at Ollama, and RegShield records the agent exactly as it would with a paid API:

```python
# OpenAI SDK: it insists on a key, and Ollama ignores it
from openai import OpenAI
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

# Anthropic SDK: Ollama also speaks Anthropic's Messages API
from anthropic import Anthropic
client = Anthropic(base_url="http://localhost:11434", api_key="ollama")

# LangChain and LangGraph: ChatOllama (pip install langchain-ollama), or ChatOpenAI with the base_url above
from langchain_ollama import ChatOllama
model = ChatOllama(model="qwen2.5:7b")

# smolagents
from smolagents import OpenAIServerModel
model = OpenAIServerModel(model_id="qwen2.5:7b", api_base="http://localhost:11434/v1", api_key="ollama")
```

Then record the run the usual way:

- **SDKs:** `instrument()` and `with TraceRecorder():`.
- **LangChain:** the callback handler.
- **smolagents:** `instrument_smolagents`.

Guards and export work the same. Pick a model that can call tools, such as Qwen 2.5, Llama 3.1 or later, or Mistral NeMo. Other models answer in text and never call your tools.

### Give the model a longer context window

A long trace must fit in the model's context window, or the judge sees only part of it. Ollama's default depends on your GPU memory: 4k tokens on small GPUs. To raise it for one model, write a `Modelfile`:

```text
FROM qwen2.5:3b
PARAMETER num_ctx 16384
```

```bash
ollama create qwen2.5-16k:3b -f Modelfile   # then set judge_model = "qwen2.5-16k:3b"
```

To raise it for every model, start Ollama with `OLLAMA_CONTEXT_LENGTH=16384`. A longer context window uses more GPU memory. RegShield's own tests use exactly this `qwen2.5-16k:3b` on a 4 GB GPU.

### Keep the model loaded, or free the GPU

Ollama unloads a model after 5 minutes without calls, and the next call waits a few seconds while it loads again.

| You want | Do this |
|---|---|
| Quick repeated test runs | Start Ollama with `OLLAMA_KEEP_ALIVE=30m` |
| The GPU back right after a run | `ollama stop qwen2.5:7b`, or start Ollama with `OLLAMA_KEEP_ALIVE=0` |
| To see what's loaded | `ollama ps` |
| Several agents or test workers at once | `OLLAMA_NUM_PARALLEL=2` (uses more memory) |

On Windows, set these as user environment variables, then quit Ollama from the tray and start it again.

### Use Ollama on another machine, in Docker or in Kubernetes

Ollama listens only on `127.0.0.1` by default. On a GPU server, let it accept connections from your network:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Then set `judge_base_url = "http://gpu-server.local:11434/v1"`, or use the server's IP address. Ollama has no login, so keep it behind your firewall or VPN.

With Docker Compose, the tests reach Ollama by its service name:

```yaml
services:
  ollama:
    image: ollama/ollama
    volumes: ["ollama:/root/.ollama"]
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
  agent-tests:
    build: .
    environment:
      OPENAI_BASE_URL: http://ollama:11434/v1
      JUDGE_MODEL: qwen2.5:7b
    command: regshield eval scenarios.json --llm-judge --judge-timeout 120
    depends_on: [ollama]
volumes:
  ollama: {}
```

Pull the model once with `docker compose exec ollama ollama pull qwen2.5:7b`. In Kubernetes, use the service name the same way: `http://ollama.ai.svc.cluster.local:11434/v1`.

Other servers work the same; only the address and the model name change:

| Server | Start it | `judge_base_url` | `judge_model` |
|---|---|---|---|
| vLLM | `vllm serve Qwen/Qwen2.5-7B-Instruct` | `http://gpu-server:8000/v1` | `Qwen/Qwen2.5-7B-Instruct` |
| LM Studio | Developer tab, then *Start server* | `http://localhost:1234/v1` | the model's name in LM Studio |
| llama.cpp | `llama-server -m qwen2.5-7b-instruct-q4_k_m.gguf --port 8080` | `http://localhost:8080/v1` | any name |

### Switch between a local model and a paid API

Keep the local judge as your everyday setting, and pick a hosted one when you want it, in CI for example. Use one settings file for each:

```toml
# regshield.toml: everyday runs, on your own GPU
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
judge_timeout = 120
```

```toml
# regshield.paid.toml: a hosted judge
llm_judge = true
judge_base_url = "https://openrouter.ai/api/v1"
judge_model = "openai/gpt-4.1-mini"
```

```bash
regshield eval scenarios.json                                   # local judge
export OPENROUTER_API_KEY=sk-or-...                             # the key stays in the environment
REGSHIELD_CONFIG=regshield.paid.toml regshield eval scenarios.json   # paid judge
```

For a single run, flags work too: `--base-url`, `--model` and `--api-key`.

### Run the judge in CI with Ollama

On GitHub Actions, run Ollama as a service container next to the job:

```yaml
# .github/workflows/agents.yml
jobs:
  agent-tests:
    runs-on: ubuntu-latest
    services:
      ollama:
        image: ollama/ollama
        ports: ["11434:11434"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
      - name: Pull the judge model
        run: curl -sf http://localhost:11434/api/pull -d '{"model": "qwen2.5:3b", "stream": false}'
      - run: regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:3b --judge-timeout 300
```

Hosted runners have no GPU, so a 3B model on the CPU, with a generous timeout, is the practical choice there. A self-hosted runner with a GPU is much faster. The model downloads on every run: about 2 GB for `qwen2.5:3b`.

### Fix common problems

The messages below are the ones RegShield prints:

| What you see | Why | Fix |
|---|---|---|
| `could not run: ConnectError: ... refused` | Ollama isn't running, or the address or port is wrong | Start Ollama (the app, or `ollama serve`); check `curl http://localhost:11434/v1/models` |
| `could not run: HTTP 404 ...: model "llama3.1:8b" not found, try pulling it first` | The model isn't downloaded, or its name is spelled differently | `ollama pull llama3.1:8b`, or copy the name from `ollama list` |
| `could not run: ReadTimeout` | The first call loads the model, and a big model or a CPU is slow | Raise `judge_timeout`; keep the model loaded with `OLLAMA_KEEP_ALIVE` |
| `error: The LLM judge uses your own server (...): set judge_model` | No model name was given | Set `judge_model` |
| `error: The LLM judge's server ... needs an API key` | The address doesn't look like your own server: a public name or IP | Pass `--api-key` (any text, if the server doesn't check keys) |
| Verdicts that seem random | The model is too small, or the trace doesn't fit its context | Use a 7B model or bigger; [raise the context window](#give-the-model-a-longer-context-window) |
| The agent never calls a tool | The model doesn't support tool calling | Use Qwen 2.5, Llama 3.1 or later, or Mistral NeMo |
| Out of memory, or very slow | The model doesn't fit the GPU | A smaller or more quantized model (`qwen2.5:3b`, `qwen2.5:7b-instruct-q4_K_M`); close other programs using the GPU |

How local models are priced, and how to count your GPU cost, is in [Mix local models and paid APIs](#mix-local-models-and-paid-apis).

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
from regression_shield import RegressionShieldCallbackHandler, TraceRecorder, evaluate_trace, instrument, instrument_smolagents

# LangChain agents, chains and compiled LangGraph graphs
handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})
report = evaluate_trace(scenario, handler)

# smolagents: CodeAgent or ToolCallingAgent, before the run
recorder = instrument_smolagents(agent)
agent.run(task)
report = evaluate_trace(scenario, recorder)

# Your own loop on the OpenAI, Anthropic or Gemini SDK, unchanged
instrument()
with TraceRecorder() as recorder:
    run_my_agent(task)
report = evaluate_trace(scenario, recorder)
```

Any other framework: wrap your tools with a `TraceRecorder` (`search = recorder.wrap(search)`) and pass the recorder to `evaluate_trace`. See [Integrations](integrations.md). All of these work the same with paid APIs and with local models ([Local and self-hosted models](local-models.md)).

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
      - run: pip install https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl
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

### Keep every setting in one file

One file holds every setting for pytest, `regshield eval` and production: thresholds, the judge, prices, logs and export. Start it with:

```bash
regshield config init    # writes regshield.toml (every setting, commented out) and .env.example
```

Uncomment what you need. API keys stay out of this file, which you commit. They go in a `.env` that you don't commit, loaded by `env_file`:

```toml
# regshield.toml
env_file = ".env"
min_tool_selection = 0.9
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5-16k:3b"
judge_timeout = 120
export_jsonl_path = "runs/agent-runs.jsonl"

[pricing.models]
"qwen2.5*" = { input = 0.05, output = 0.10 }
```

```bash
# .env, listed in .gitignore
OPENROUTER_API_KEY=sk-or-...
REGSHIELD_LOG_LEVEL=info
```

Every setting can be overridden by an environment variable, `REGSHIELD_` plus the setting's name in capitals, for one machine or one CI job. `regshield config show` prints what's in effect and where each value comes from. Key values are never printed:

```text
Setting (highest priority first: arguments, environment, file, defaults)
  min_tool_selection           0.9                                regshield.toml
  min_argument_correctness     0.85                               default
  llm_judge                    true                               regshield.toml
  judge_model                  qwen2.5-16k:3b                     regshield.toml
  judge_timeout                200.0                              REGSHIELD_JUDGE_TIMEOUT
  log_level                    info                               REGSHIELD_LOG_LEVEL (from .env)
  export_jsonl_path            runs\agent-runs.jsonl              regshield.toml
  ...
API keys (never stored in the config file)
  OPENROUTER_API_KEY           set (from .env)
  OPENAI_API_KEY               not set

LLM judge would use: qwen2.5-16k:3b at http://localhost:11434/v1 (your own server, no key needed)
```

In CI, where there's no `.env`, the same file works: a missing `env_file` is skipped, and keys come from the CI's secrets. In `pyproject.toml`, put the same lines under `[tool.regshield]`. Every setting is listed in [Configuration](reference.md#configuration-file).

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
