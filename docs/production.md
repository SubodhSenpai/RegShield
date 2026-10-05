# In production

The scenarios you test in CI can also guard running agents:

- **Block risky actions** with a `Guard`.
- **Record SDK calls** with `instrument()`, no code changes.
- **Export runs** to OpenTelemetry, a JSONL file or any URL.
- **Keep prices current** with `regshield pricing refresh`.

## Block risky actions

A `Guard` takes the same scenario your tests use and checks each action before it runs:

```python
from regression_shield import ActionBlocked, Guard, TraceRecorder

guard = Guard({
    "forbidden_arguments": {"run_sql": {"query": r"\b(drop|delete|truncate)\b"}},
    "prerequisites": {"deploy": ["run_tests"]},
    "requires_approval": ["issue_refund"],
    "max_cost_usd": 0.50,
}, rate_limits={"send_email": "10/minute"})

recorder = TraceRecorder(guard=guard)

@recorder.tool
def run_sql(query: str) -> str: ...
```

A blocked call doesn't run. Instead RegShield:

- records the attempt with `"blocked": {"rule": ..., "reason": ...}` and an `ERROR: Blocked by policy: <reason>. This action did not run.` observation
- raises `ActionBlocked` (with `tool`, `rule`, `reason` and `arguments`)
- lets the agent see why, so it can recover and tell the user the truth

Where to add the guard:

| Agent | Add the guard |
|---|---|
| Your own tools | `TraceRecorder(guard=guard)`, then `@recorder.tool` or `recorder.wrap(fn)`. Otherwise call `recorder.check(name, args)`. |
| LangChain `create_agent` | `RegressionShieldCallbackHandler(guard=guard)` as a callback, plus `middleware=[handler.middleware()]`. Blocked calls return an error `ToolMessage`. |
| LangGraph `ToolNode` | `ToolNode(tools, wrap_tool_call=handler.wrap_tool_call)` |
| smolagents | `instrument_smolagents(agent, TraceRecorder(guard=guard))` |
| Raw OpenAI / Anthropic / Gemini SDK | `instrument()` plus `with TraceRecorder(guard=guard):` ([below](#record-sdk-calls-with-no-code-changes)) |

### Rules the guard enforces

| Rule | Blocks a call when |
|---|---|
| `forbidden_tools` | the tool is in the list |
| `agent_tools` | the current agent isn't allowed this tool |
| `forbidden_arguments` | an argument matches a pattern (regular expressions, case-insensitive) |
| `prerequisites` | a listed tool hasn't run in this run, or its latest run failed |
| `requires_approval` | no unused approval exists (see [Approvals](#approvals)); each approval allows one call |
| `max_tool_calls` | the tool already ran that many times in this run (blocked attempts don't count) |
| `max_cost_usd` | the run's spend, plus the tool's price from your pricing, would go over the budget |
| `rate_limits` (guard only) | too many calls in the time window, counted across all runs that share the guard |

- **Budgets** (`max_cost_usd`, `max_tokens`, `max_llm_calls`) also stop further model calls with `ActionBlocked`, via `instrument()`, the LangChain middleware or `instrument_smolagents`. A run can overshoot by one call.
- **Local models** are free, so cap them with `max_tokens` or `max_llm_calls` ([details](local-models.md#5-costs-with-local-models)).
- **Other fields**, like expected tools and order, can only be judged after a run, so the guard ignores them.

### Rate limits

Formats: `"N/second"`, `"N/minute"`, `"N/hour"`, `"N/day"`, `"N/5min"` or `(calls, seconds)`. `"*"` limits all tools together. Share one guard so limits hold across runs:

```python
guard = Guard(rate_limits={"send_email": "10/minute", "*": "500/hour"})
```

### Approvals

A `requires_approval` tool runs only after an approval, given either way:

- Record a person's decision with `recorder.approval("issue_refund", approved=True, by="alice")`.
- Give the guard an `approver(tool, args) -> bool` to ask at call time:

```python
guard = Guard({"requires_approval": ["issue_refund"]},
              approver=lambda tool, args: args["amount"] <= 200)  # a manager signs off on small refunds
```

The approver's answer is recorded. A "no", or an approver that raises, blocks the call.

### Roll out a new rule safely

`Guard(scenario, warn_only=True)` runs every call and logs what it would have blocked (a `guard_warning` on the step, also exported). A scenario's `warn_only` list does it per check (`"policy"`, `"budget"`, `"human_approval"`, `"multi_agent"`).

### What CI makes of blocked calls

- Blocked attempts at forbidden tools, arguments or unmet prerequisites still fail Policy, marked `(blocked)`.
- A blocked attempt costs nothing.
- A call blocked for lack of approval doesn't count as running without one.
- Claiming a blocked action succeeded fails faithfulness.
- `report.details["blocked_actions"]` lists them.

## Record SDK calls with no code changes

```python
import regression_shield as rs

rs.instrument()                              # once, at startup

with rs.TraceRecorder(guard=guard) as recorder:
    answer = run_my_agent(question)          # your own loop on the OpenAI, Anthropic or Gemini SDK
report = rs.evaluate_trace(scenario, recorder)
```

Inside a `with recorder:` block, every SDK model call is recorded with tokens: OpenAI chat and Responses, Anthropic messages, Gemini `generate_content`, sync and async. Calls outside a block are ignored.

Tool calls are rebuilt from the conversation:

- **The call:** the tool the model asks for.
- **The result:** what your code sends back next (OpenAI `tool` messages and `function_call_output`, Anthropic `tool_result` with `is_error`, Gemini `function_response`).
- **Gemini's automatic function calling:** each turn too.
- **The final answer:** a reply without tool calls.

A requested call with no result by the end is marked `"unconfirmed": true`.

Things to know:

- **Guard:** a reply asking for a blocked call raises `ActionBlocked` from the SDK call, so none of its calls run. A used-up budget stops the next request.
- **Wrapped tools** (`@recorder.tool`) are recorded once, where they run.
- **Streaming:** `stream=True` is recorded when the stream ends. For OpenAI token counts, pass `stream_options={"include_usage": True}`.
- **Not captured:** `.stream()` helpers. Use `stream=True` or `recorder.llm_response(final_message)`.
- **Other recorders:** `instrument()` leaves the LangChain handler and `instrument_smolagents` alone.
- **Async:** each asyncio task sees the recorder it entered; threads you start don't.
- **Undo:** `rs.uninstrument()`.

## Send runs to your monitoring service

```python
import regression_shield as rs

rs.export_traces(
    rs.OpenTelemetryExporter(endpoint="http://localhost:4318"),  # an OTLP/HTTP collector
    sample_rate=0.1,              # export 10% of healthy runs...
    keep_errors=True,             # ...and every run where a tool failed, a call was blocked or a guard warned
    max_runs_per_minute=600,      # protect the backend from a flood
)
```

From then on, every recorder streams its runs, except `TraceRecorder(export=False)`.

**Exporters:**

| Exporter | Sends |
|---|---|
| `OpenTelemetryExporter` | GenAI spans (`invoke_agent`, `execute_tool`, `chat`) plus `regshield.*` cost and guard attributes. Needs the `otel` extra ([install](getting-started.md#install)). |
| `JSONLExporter(path)` | One JSON event per line. With `capture_content=True`, `run_end` carries the whole trace, ready to become a test case. |
| `HTTPExporter(url, headers=...)` | Batches of `{"events": [...]}` from a background thread, with retries. Drops events rather than slow the agent (`exporter.dropped`). |
| Your own | Subclass `Exporter` and implement `export(event)`. |

OpenTelemetry details:

- Works with Grafana Tempo, Jaeger, Honeycomb, Datadog, Langfuse, Phoenix or any OTLP collector.
- Destination: `endpoint` (with `headers`), the `OTEL_EXPORTER_OTLP_*` variables, your own `tracer_provider` or `span_exporter`, or your app's provider.
- Blocked and failed calls get an error status. A run inside one of your spans becomes its child.

**Events:** `run_start`, then each `tool_call`, `llm_call` and pattern event (`handoff`, `approval`, `plan`, `route`, `node`, `draft`, `critique`) as it's recorded, then `run_end`.

- `tool_call` events carry `tool`, `status` (`ok`, `error` or `blocked`), `duration_ms` and `step`.
- `llm_call` events carry `model`, token counts, `duration_ms` and `cost_usd`.
- `run_end` carries `status` (`ok`, `error` or `blocked`), counts, tokens and `cost_usd`.

**Privacy:** prompts, arguments, tool results and answers stay out of exports unless the exporter has `capture_content=True`.

**What counts as a run:**

| How you record | One run is |
|---|---|
| `with recorder:` | the block (`recorder.start_run(name, user_id=...)` names it and adds attributes) |
| LangChain/LangGraph handler | each top-level invocation |
| smolagents | each `agent.run` |
| Anything else | everything until `recorder.end_run()` or `recorder.reset()` |

**From your config file:** name the destinations in it, and call `rs.export_traces()` with no arguments:

```toml
export_otlp_endpoint = "http://localhost:4318"   # and/or export_jsonl_path, export_http_url
export_sample_rate = 0.1
export_max_runs_per_minute = 600
```

Credentials stay out of the file: use `OTEL_EXPORTER_OTLP_HEADERS` or `REGSHIELD_EXPORT_HTTP_HEADERS` (`Authorization=Bearer <token>`), in the environment or `.env`.

**Failures:** a failing exporter never breaks the agent. `rs.export_stats()` shows the counts. `rs.stop_exporting()` flushes and stops, and runs at exit.

## Keep prices current

Costs use a bundled, dated list of public prices (`report.cost["prices_as_of"]`). Refresh it from LiteLLM's list:

```bash
regshield pricing refresh                 # download the latest list prices
regshield pricing show gpt-4o my-model    # the price RegShield uses for each model
```

- The refreshed list is cached (`REGSHIELD_CACHE_DIR` moves it) and used when it's at least as new as the bundled one.
- Offline machines: `--from FILE`.
- Same prices everywhere: `--output PATH`, then point `REGSHIELD_PRICE_LIST` at it.
- Your own prices (`pricing=` or `[tool.regshield.pricing]`) always win.
