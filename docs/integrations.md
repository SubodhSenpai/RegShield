# Integrations

Every integration produces a trace for `evaluate_trace(scenario, trace)`. The LangChain handler and `TraceRecorder` can be passed directly.

- [LangChain](#langchain)
- [LangGraph](#langgraph)
- [smolagents](#smolagents)
- [Any framework: `TraceRecorder`](#any-framework-tracerecorder)
- [The `@shield` decorator](#the-shield-decorator)
- [REST API (any language)](#rest-api-any-language)

Runnable versions of everything on this page, using a local LLM, are in [examples/](../examples/README.md).

---

## LangChain

```bash
pip install "regression-shield[langchain]"
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

- each tool call with its arguments and result, or `ERROR: ...` if the tool raised
- the model's text before a call, as that step's thought
- the agent's final answer (the last AI message without tool calls), for the faithfulness check
- calls the model requested together, which LangChain runs in parallel, as one parallel group

Each new top-level run starts a fresh trace, so one handler can be reused.

## LangGraph

```bash
pip install "regression-shield[langgraph]"
```

Pass the same handler to a compiled graph. On top of the above, it records from LangGraph's own metadata, with no extra code:

| What | How it appears in the trace | Checked by |
|---|---|---|
| Graph nodes | A `node` event each time a top-level node runs | [Graph](patterns.md#graph-workflows) |
| Fan-out (nodes in the same step) | The nodes and their tool calls share a parallel group | [Parallel calls](patterns.md#parallel-tool-calls), graph |
| Sub-agents (`create_agent(name=...)`, supervisor, swarm) | Each step tagged with its `agent` | [Multi-agent](patterns.md#multi-agent-handoffs) |
| `transfer_to_<agent>` / `transfer_back_to_<agent>` tools | `handoff` events | Multi-agent |
| `HumanInTheLoopMiddleware` interrupts | An `approval` event per decision when you resume (`approve`/`edit` approved, `reject`/`respond` denied) | [Human approval](patterns.md#human-in-the-loop-approval) |

```python
report = evaluate_trace({
    "scenario_id": "content_pipeline",
    "allowed_transitions": {"writer": ["reviewer"], "reviewer": ["writer", "publish"]},
    "max_node_visits": {"reviewer": 3},
}, handler)
print(report.patterns["graph"]["details"]["path"])   # ['writer', 'reviewer', 'writer', 'reviewer', 'publish']
```

**Human in the loop.** Use the same handler for the first run and for resuming. The resume continues the trace instead of starting a new one:

```python
config = {"configurable": {"thread_id": "refund-1"}, "callbacks": [handler]}
result = agent.invoke({"messages": [...]}, config)                    # pauses for approval
if result.get("__interrupt__"):
    agent.invoke(Command(resume={"decisions": [{"type": "reject"}]}), config)

report = evaluate_trace({"scenario_id": "refund", "requires_approval": ["issue_refund"]}, handler)
```

**Your own events.** The handler is a [`TraceRecorder`](#any-framework-tracerecorder), so a node can add plans, routes, drafts or critiques to the same trace:

```python
handler = RegressionShieldCallbackHandler()

def planner(state):
    plan = make_plan(state)
    handler.plan(plan)
    return {"plan": plan}
```

## smolagents

```bash
pip install "regression-shield[smolagents]"
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

This works for `CodeAgent`, whose tools are called from Python code the model writes (its memory only shows the code), and for `ToolCallingAgent`. It records:

- each tool call as it runs, with its arguments and result or error
- the model's output for each step, as the thought of the calls made in it
- calls requested together in one step (smolagents runs them in threads) as one parallel group
- the run's answer, including the one smolagents asks for after `max_steps`
- managed agents: calling one is a handoff from its manager, and every step is tagged with the agent that made it

Each `agent.run` starts a new trace, unless you pass `reset=False` to continue the conversation.

If you couldn't instrument a `ToolCallingAgent` before it ran, rebuild the trace from its memory afterwards:

```python
from regression_shield import extract_smolagents_trace

agent.run(task)
report = evaluate_trace(scenario, extract_smolagents_trace(agent))
```

## Any framework: `TraceRecorder`

For your own agent loop, or a framework without an adapter (OpenAI Agents SDK, CrewAI, AutoGen, Pydantic AI, raw API calls), use a `TraceRecorder`:

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

Then, inside your loop, add the model's reasoning and final answer:

```python
reply = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOL_SCHEMAS)
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
| `@recorder.tool`, `recorder.wrap(fn, name=None, agent=None)` | A call each time the function runs |
| `recorder.tool_call(name, args, observation, agent=None)` | A call you ran yourself |
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

The recorder is thread-safe. When agents run concurrently, pass `agent=` to `wrap` or `tool_call` so each call is credited to the agent that made it, rather than to whichever agent was last handed control.

To connect another framework, call the matching method from its hooks: `handoff` when a task moves to another agent, `approval` wherever a person approves an action, and so on.

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

If the function returns a trace itself (a list of steps, or a dict with `steps`), leave out `get_trace`. With LangChain, use `get_trace=handler.get_trace`. Thresholds and judge settings can be passed as keyword arguments.

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

The response is the report (`status`, `composite_score`, `metrics`, `patterns`, `failures`...), and the dashboard shows it. A Python process can send a report it made itself with `report.sync_to_dashboard("http://localhost:8000")`.

The server listens on `127.0.0.1` only by default, accepts only `application/json`, and rejects requests that try to set the judge's `api_key`, `model` or `base_url`. See the [REST reference](reference.md#rest-api) for every endpoint.
