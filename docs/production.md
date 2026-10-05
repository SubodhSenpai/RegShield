# In production

The scenarios you test in CI can also protect your agents while they run. This page covers four things:

- **Block risky actions**: a `Guard` checks each tool call against your rules before it runs.
- **Record SDK calls with no code changes**: `instrument()` captures raw OpenAI, Anthropic and Gemini SDK loops.
- **Send runs to your monitoring service**: OpenTelemetry, a JSONL file or any HTTP endpoint, with sampling and rate limits.
- **Keep prices current**: `regshield pricing refresh` updates the list prices used for cost.

## Block risky actions

A `Guard` takes a scenario, the same one your tests use, and checks each action before it happens. Attach it to whatever records your agent:

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

A call that breaks a rule doesn't run. RegShield then does three things:

- It records the attempt on the trace, with `"blocked": {"rule": ..., "reason": ...}` and the observation `ERROR: Blocked by policy: <reason>. This action did not run.`
- It raises `ActionBlocked`. Its message is the same text, and it has `tool`, `rule`, `reason` and `arguments` attributes.
- It tells the agent why. LangGraph, smolagents and most agent loops turn the exception into an error message the model reads, so the agent can recover and tell the user the truth.

Where the guard applies depends on how you run the agent:

| Agent | Add the guard |
|---|---|
| Your own tools | `TraceRecorder(guard=guard)`, then `@recorder.tool` or `recorder.wrap(fn)`. Call `recorder.check(name, args)` before running a tool any other way. |
| LangChain `create_agent` | `handler = RegressionShieldCallbackHandler(guard=guard)`, then `create_agent(..., middleware=[handler.middleware()])`. Also pass the handler as a callback. A blocked call returns an error `ToolMessage`, and the agent carries on. |
| LangGraph `ToolNode` | `ToolNode(tools, wrap_tool_call=handler.wrap_tool_call)` |
| smolagents | `instrument_smolagents(agent, TraceRecorder(guard=guard))` |
| Raw OpenAI / Anthropic / Gemini SDK | `instrument()` plus `with TraceRecorder(guard=guard):`. A reply asking for a blocked call raises `ActionBlocked` from the SDK call, before your code can run it (see [below](#record-sdk-calls-with-no-code-changes)). |

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

The run's budget also stops further model calls: `max_cost_usd`, `max_tokens` and `max_llm_calls`. This happens with `instrument()`, the LangChain middleware and `instrument_smolagents`, and the agent stops with `ActionBlocked`. A call's cost is only known once it returns, so a run can go over its budget by at most one model call. Local models cost nothing per token, so give them a price, or cap them with `max_tokens` or `max_llm_calls` ([Local and self-hosted models](local-models.md#5-costs-with-local-models)).

Other scenario fields, such as expected tools and order, can only be judged after a run, so the guard ignores them.

### Rate limits

A rate limit is `"N/second"`, `"N/minute"`, `"N/hour"`, `"N/day"`, `"N/5min"`, or a `(calls, seconds)` pair. `"*"` limits all tool calls together. Use one guard for all your runs, so the limit holds across users and requests:

```python
guard = Guard(rate_limits={"send_email": "10/minute", "*": "500/hour"})
```

### Approvals

A `requires_approval` tool runs only after an approval. There are two ways to give one:

- Record a person's decision with `recorder.approval("issue_refund", approved=True, by="alice")`.
- Give the guard an `approver(tool, args) -> bool` to ask at call time:

```python
guard = Guard({"requires_approval": ["issue_refund"]},
              approver=lambda tool, args: args["amount"] <= 200)  # a manager signs off on small refunds
```

The guard records the approver's decision as an approval event. A refused approval, or an approver that raises, blocks the call.

### Roll out a new rule safely

`Guard(scenario, warn_only=True)` lets every call run and only logs what it would have blocked. A scenario's own `warn_only` list does the same per check (`"policy"`, `"budget"`, `"human_approval"`, `"multi_agent"`). Each call that would have been blocked gets a `guard_warning` on its step, and the warning is exported.

### What CI makes of blocked calls

The tests still judge what the agent tried to do. A blocked attempt at a forbidden tool, a forbidden argument or an unmet prerequisite fails the Policy check, with `(blocked)` at the end of the message. A blocked attempt costs nothing. A call blocked for lack of approval isn't treated as running without approval. If the agent then claims the blocked action succeeded, the faithfulness check catches it. `report.details["blocked_actions"]` lists the blocked calls.

## Record SDK calls with no code changes

```python
import regression_shield as rs

rs.instrument()                              # once, at startup

with rs.TraceRecorder(guard=guard) as recorder:
    answer = run_my_agent(question)          # your own loop on the OpenAI, Anthropic or Gemini SDK
report = rs.evaluate_trace(scenario, recorder)
```

Inside a `with recorder:` block, every model call made through the SDKs is recorded with its token usage. This covers OpenAI chat completions and the Responses API, Anthropic messages, and Gemini `generate_content`, sync and async. Calls outside a block are left alone.

Tool calls are rebuilt from the conversation:

- **The call:** the tool the model asks for.
- **The result:** what your code sends back with the next request. That's OpenAI `tool` messages and `function_call_output` items, Anthropic `tool_result` blocks (`is_error` becomes an `ERROR:` observation) and Gemini `function_response` parts.
- **Gemini's automatic function calling:** each turn is recorded as well.
- **The final answer:** a reply without tool calls.

If the run ends while a requested call has no result, it is recorded with `"unconfirmed": true`.

Things to know:

- **Guard:** with a guard on the recorder, a reply that asks for a blocked call raises `ActionBlocked` from the SDK call. Your code never receives it, so none of that reply's calls run. A used-up budget stops the next request before it's sent.
- **Wrapped tools:** tools you wrap with `@recorder.tool` are guarded and recorded where they run, so they're never recorded twice. They also get the model's reasoning as their thought.
- **Streaming:** `stream=True` is recorded when the stream ends. For OpenAI chat, pass `stream_options={"include_usage": True}` to get token counts.
- **Not captured:** the `.stream()` helper methods. Use `stream=True`, or `recorder.llm_response(final_message)`.
- **Other recorders:** the LangChain handler and `instrument_smolagents` record model calls themselves, so `instrument()` leaves their recorders alone.
- **Async:** each asyncio task sees the recorder it entered. A thread you start yourself doesn't inherit it.
- **Undoing it:** `rs.uninstrument()` restores the SDKs.

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

From then on, every recorder streams its runs as they happen:

- `TraceRecorder`, the LangChain handler and `instrument_smolagents` all do it.
- So do SDK calls captured by `instrument()`.
- Recorders created with `TraceRecorder(export=False)` are left out.

**Exporters:**

| Exporter | Sends |
|---|---|
| `OpenTelemetryExporter` | Spans with the OpenTelemetry GenAI attributes: `invoke_agent` for the run, `execute_tool` per tool call and `chat` per model call, with token usage. Plus `regshield.*` attributes for cost, status and guards. Blocked and failed calls get an error status. It works with Grafana Tempo, Jaeger, Honeycomb, Datadog, Langfuse, Phoenix and any OTLP collector. Destination: `endpoint` (with `headers` for auth), the `OTEL_EXPORTER_OTLP_*` environment variables, your own `tracer_provider` or `span_exporter`, or the provider your app already set up. A run that starts inside one of your spans becomes its child. Needs `pip install "regression-shield[otel]"`. |
| `JSONLExporter(path)` | One JSON event per line, for log shippers. With `capture_content=True`, the `run_end` event carries the whole trace, so a production run can become a test case. |
| `HTTPExporter(url, headers=...)` | Batches of events as `{"events": [...]}` from a background thread. It retries failures. When its queue is full it drops events instead of slowing the agent (`exporter.dropped`). |
| Your own | Subclass `Exporter` and implement `export(event)`. |

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

Credentials stay out of the file. For OpenTelemetry, use `OTEL_EXPORTER_OTLP_HEADERS`; for `export_http_url`, use `REGSHIELD_EXPORT_HTTP_HEADERS` (`Authorization=Bearer <token>`). Both can go in the environment or your `.env`.

**Failures:** a failing exporter never breaks the agent; errors are counted. `rs.export_stats()` shows runs started, exported, sampled out, kept for errors and rate limited, plus events exported and dropped. `rs.stop_exporting()` flushes the exporters and stops. It also runs at exit.

## Keep prices current

Costs use a list of public list prices, bundled with RegShield and dated in `report.cost["prices_as_of"]`. Prices change often. Refresh them from LiteLLM's price list:

```bash
regshield pricing refresh                 # download the latest list prices
regshield pricing show gpt-4o my-model    # the price RegShield uses for each model
```

The refreshed list is saved in your user cache (`REGSHIELD_CACHE_DIR` moves it). RegShield then uses it whenever it's at least as new as the bundled list. `--from FILE` reads a downloaded copy instead, for machines without internet access. `--output PATH` saves the list elsewhere; point `REGSHIELD_PRICE_LIST` at it to use it, for example a list committed to your repository so CI and every laptop price runs the same. Your own prices (`pricing=` or `[tool.regshield.pricing]`) always come first.
