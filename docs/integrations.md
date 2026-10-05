# Integrations

Every integration produces a trace for `evaluate_trace(scenario, trace)`.

- [LangChain](#langchain)
- [LangGraph](#langgraph)
- [smolagents](#smolagents)
- [Any framework: `TraceRecorder`](#any-framework-tracerecorder)
- [Raw OpenAI, Anthropic and Gemini SDK loops: `instrument()`](#raw-openai-anthropic-and-gemini-sdk-loops-instrument)
- [The `@shield` decorator](#the-shield-decorator)
- [REST API (any language)](#rest-api-any-language)

Runnable versions with a local LLM: [examples/](../examples/README.md). Guarding and exporting runs: [In production](production.md).

---

## LangChain

```bash
pip install "regression-shield[langchain] @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl"
```

```python
from langchain.agents import create_agent
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

agent = create_agent(model, tools=[verify_identity, check_balance, send_wire])
handler = RegressionShieldCallbackHandler()
agent.invoke({"messages": [{"role": "user", "content": "Wire $250 to ACCT-99"}]},
             config={"callbacks": [handler]})

report = evaluate_trace(scenario, handler)
```

The handler records:

- tool calls with arguments and results (`ERROR: ...` if a tool raised)
- the model's text before a call, as its thought
- the final answer
- calls requested together, as one parallel group
- token usage per model call (`handler.llm_calls`), for [cost tracking](reference.md#cost-tracking)

Each top-level run starts a fresh trace, so one handler can be reused.

**Block risky calls.** Give the handler a [`Guard`](production.md#block-risky-actions) and add its middleware. A blocked call doesn't run, and the agent is told why. A used-up budget raises `ActionBlocked`:

```python
from regression_shield import Guard, RegressionShieldCallbackHandler

handler = RegressionShieldCallbackHandler(guard=Guard(scenario, rate_limits={"send_wire": "5/hour"}))
agent = create_agent(model, tools=[verify_identity, check_balance, send_wire], middleware=[handler.middleware()])
agent.invoke({"messages": [...]}, config={"callbacks": [handler]})
```

## LangGraph

```bash
pip install "regression-shield[langgraph] @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl"
```

Pass the same handler to a compiled graph. It also records, with no extra code:

| What | How it appears in the trace | Checked by |
|---|---|---|
| Graph nodes | A `node` event each time a top-level node runs | [Graph](patterns.md#graph-workflows) |
| Fan-out (nodes in the same step) | The nodes and their tool calls share a parallel group | [Parallel calls](patterns.md#parallel-tool-calls), graph |
| Sub-agents (`create_agent(name=...)`, supervisor, swarm) | Each step tagged with its `agent` | [Multi-agent](patterns.md#multi-agent-handoffs) |
| `transfer_to_<agent>` / `transfer_back_to_<agent>` tools | `handoff` events | Multi-agent |
| `HumanInTheLoopMiddleware` interrupts | An `approval` per decision (`approve`/`edit` approved, `reject`/`respond` denied) | [Human approval](patterns.md#human-in-the-loop-approval) |

```python
report = evaluate_trace({
    "scenario_id": "content_pipeline",
    "allowed_transitions": {"writer": ["reviewer"], "reviewer": ["writer", "publish"]},
    "max_node_visits": {"reviewer": 3},
}, handler)
print(report.patterns["graph"]["details"]["path"])   # ['writer', 'reviewer', 'writer', 'reviewer', 'publish']
```

**Human in the loop.** Use the same handler to run and to resume, so the trace continues:

```python
config = {"configurable": {"thread_id": "refund-1"}, "callbacks": [handler]}
result = agent.invoke({"messages": [...]}, config)                    # pauses for approval
if result.get("__interrupt__"):
    agent.invoke(Command(resume={"decisions": [{"type": "reject"}]}), config)

report = evaluate_trace({"scenario_id": "refund", "requires_approval": ["issue_refund"]}, handler)
```

**A guard in your own graph.** `ToolNode(tools, wrap_tool_call=handler.wrap_tool_call)` (`awrap_tool_call` for async).

**Your own events.** The handler is a [`TraceRecorder`](#any-framework-tracerecorder), so nodes can add plans, routes or critiques:

```python
handler = RegressionShieldCallbackHandler()

def planner(state):
    plan = make_plan(state)
    handler.plan(plan)
    return {"plan": plan}
```

## smolagents

```bash
pip install "regression-shield[smolagents] @ https://github.com/SubodhSenpai/RegShield/releases/download/v0.5.0/regression_shield-0.5.0-py3-none-any.whl"
```

Instrument the agent once, before running it:

```python
from smolagents import CodeAgent
from regression_shield import evaluate_trace, instrument_smolagents

agent = CodeAgent(tools=[get_stock_price, convert_currency], model=model)
recorder = instrument_smolagents(agent)
agent.run("What is Apple's stock price in euros?")

report = evaluate_trace(scenario, recorder)
```

Works for `CodeAgent` (tools called from generated code) and `ToolCallingAgent`. It records:

- tool calls as they run, with results or errors
- each step's model output, as its thought
- calls requested together, as one parallel group
- the final answer
- managed agents, as handoffs
- token usage (`recorder.llm_calls`), for [cost tracking](reference.md#cost-tracking)

Each `agent.run` starts a new trace (`reset=False` continues it).

With a guard, `instrument_smolagents(agent, TraceRecorder(guard=guard))` blocks risky calls; the model sees why and can try something else.

Didn't instrument a `ToolCallingAgent` in time? Rebuild the trace from its memory:

```python
from regression_shield import extract_smolagents_trace

agent.run(task)
report = evaluate_trace(scenario, extract_smolagents_trace(agent))
```

## Any framework: `TraceRecorder`

For your own loop or any other framework (OpenAI Agents SDK, CrewAI, AutoGen, Pydantic AI):

```python
from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder()

@recorder.tool                               # records arguments, result or error (then re-raises)
def get_order(order_id: str) -> dict:
    return orders[order_id]

@recorder.tool(name="track_package")         # custom name; async functions work too
async def track(tracking: str) -> dict:
    ...
```

Inside your loop, record usage, reasoning and the final answer:

```python
reply = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOL_SCHEMAS)
recorder.llm_response(reply)                 # tokens and model, for cost tracking
message = reply.choices[0].message
if message.tool_calls:
    if message.content:
        recorder.thought(message.content)    # attached to the next recorded step
    for call in message.tool_calls:
        TOOLS[call.function.name](**json.loads(call.function.arguments))   # recorded by @recorder.tool
else:
    recorder.final_answer(message.content)
```

| Method | Records |
|---|---|
| `@recorder.tool`, `recorder.wrap(fn, name=None, agent=None, cost_usd=None)` | A call each time the function runs (`cost_usd`: price per call) |
| `recorder.tool_call(name, args, observation, agent=None, cost_usd=None)` | A call you ran yourself |
| `recorder.llm_response(response)` | Token usage from an SDK response or LangChain message |
| `recorder.llm_call(model, input_tokens, output_tokens, cached_input_tokens=0, cost_usd=None)` | Token usage, given directly |
| `recorder.thought(text)` | Reasoning for the next step |
| `recorder.plan(steps)` | A plan: tool names in order |
| `recorder.handoff(to)` | Control passing to another agent; later steps belong to it |
| `recorder.approval(tool, approved, by=None)` | A person's approval decision |
| `recorder.route(to)` | A router's decision |
| `recorder.node(name)` | Entering a graph node |
| `with recorder.parallel():` | Steps inside ran concurrently |
| `recorder.draft(content)`, `recorder.critique(approved, feedback)` | Evaluator-optimizer rounds |
| `recorder.final_answer(text)` | The agent's answer to the user |
| `recorder.get_trace()`, `recorder.reset()` | Read or clear the trace |
| `recorder.to_dict()` | The whole run as JSON, to save in a scenario file |

- The recorder is thread-safe. With concurrent agents, pass `agent=` to `wrap` or `tool_call`.
- For other frameworks, call the matching method from their hooks (`handoff`, `approval`...).
- With `TraceRecorder(guard=guard)`, wrapped tools are checked before running. Otherwise call `recorder.check(name, args)` before a tool and `recorder.check_llm()` before a model call.

## Raw OpenAI, Anthropic and Gemini SDK loops: `instrument()`

Calling the SDKs directly? Skip the `llm_response`, `thought` and `final_answer` lines. Instrument once and wrap each run:

```python
import regression_shield as rs

rs.instrument()                                  # once, at startup

with rs.TraceRecorder() as recorder:
    answer = run_my_agent(question)              # unchanged: plain SDK calls
report = rs.evaluate_trace(scenario, recorder)
```

Every model call in the block is recorded with tokens (OpenAI chat and Responses, Anthropic messages, Gemini `generate_content`; sync, async and streamed). Tool calls are rebuilt from the conversation:

- what the model asked for;
- the result your code sent back in the next request;
- the model's text before the calls, as their thought;
- a reply without tool calls, as the final answer.

With a guard, a blocked call raises `ActionBlocked` from the SDK call. Details: [In production](production.md#record-sdk-calls-with-no-code-changes).

## The `@shield` decorator

Evaluate a function every time it runs. It returns `(output, report)`:

```python
from regression_shield import TraceRecorder, shield

recorder = TraceRecorder()
tools = [recorder.wrap(t) for t in (run_unit_tests, deploy_production)]

@shield(scenario, get_trace=recorder.get_trace, raise_on_failure=True)   # EvaluationFailed on failure
def run_agent(task: str) -> str:
    recorder.reset()
    return my_agent(task, tools=tools)

output, report = run_agent("Deploy to staging")
```

If the function returns a trace itself, leave out `get_trace`. With LangChain, use `get_trace=handler.get_trace`. Thresholds go in as keyword arguments.

## REST API (any language)

Start the server and POST a scenario and a trace as JSON:

```bash
regshield serve
```

```bash
curl -X POST http://localhost:8000/api/evaluate-trace \
  -H "Content-Type: application/json" \
  -d '{
    "scenario": {"scenario_id": "refund", "requires_approval": ["issue_refund"]},
    "trace": [
      {"action": {"type": "approval", "tool": "issue_refund", "approved": true}},
      {"action": {"name": "issue_refund", "args": {"order_id": "A-1"}}, "observation": "REFUNDED"}
    ]
  }'
```

The response is the report, and the dashboard shows it. From Python: `report.sync_to_dashboard("http://localhost:8000")`.

The server listens on `127.0.0.1`, accepts only JSON, and rejects requests that set the judge's key, model or URL. [All endpoints](reference.md#rest-api).
