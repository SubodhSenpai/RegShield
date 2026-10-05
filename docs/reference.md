# Reference

- [Scenario fields](#scenario-fields)
- [Trace format](#trace-format)
- [Report](#report)
- [Algorithms](#algorithms)
- [Scenario files](#scenario-files)
- [CLI](#cli)
- [REST API](#rest-api)
- [Configuration file](#configuration-file)
- [Environment variables](#environment-variables)
- [Cost tracking](#cost-tracking)
- [Logging](#logging)
- [Python API](#python-api)

## Scenario fields

A dict or a `ScenarioSpec`. Only `scenario_id` is required; leave a field out to skip its check. Unknown fields raise `ValueError`.

### Core

| Field | Type | Meaning |
|---|---|---|
| `scenario_id` | str | Name used in reports |
| `title`, `domain` | str | Labels for reports and the dashboard |
| `goal` | str | What the agent should achieve; given to the LLM judge |
| `expected_tools` | list[str] | Tools that should run. Scored as F1: missing and unexpected tools both count |
| `expected_arguments` | dict[tool, dict] | Expected values, against the best-matching call. Numbers compare numerically; text ignores case, `_` and `-`; objects and lists item by item; booleans match only booleans or `"true"`/`"false"` |
| `expected_order` | list[str] or list[[before, after]] | A sequence (each tool before the next), or pairs forming a partial order |
| `optimal_step_count` | int | Ideal number of tool calls for step efficiency (default: the number of `expected_tools`, or 3) |
| `warn_only` | list[str] | Checks reported as `warnings` instead of failures: metric names, pattern keys (`policy`, `budget`...) or `llm_judge` |
| `metadata` | dict | Your own data, kept in the report and not checked |

A limit of `0` is a real limit (for example `"max_handoffs": 0` allows no handoffs).

### Agentic patterns

Details and examples: [Agentic patterns](patterns.md).

| Field | Type | Pattern |
|---|---|---|
| `forbidden_tools` | list[str] | Policy |
| `max_tool_calls` | dict[tool, int] | Policy |
| `forbidden_arguments` | dict[tool or `"*"`, dict[argument or `"*"`, regex or list]] | Policy: argument values a tool must never get (case-insensitive regular expressions) |
| `prerequisites` | dict[tool, list[str]] | Policy: tools whose latest result must be a success before the tool runs |
| `requires_approval` | list[str] | Human approval |
| `require_plan` | bool | Plan-and-execute |
| `expected_plan` | list[str] | Plan-and-execute (implies `require_plan`) |
| `agent_tools` | dict[agent, list[str]] | Multi-agent |
| `expected_agents` | list[str] | Multi-agent |
| `max_handoffs` | int | Multi-agent |
| `expected_route` | str or list[str] | Routing |
| `expected_parallel` | list[list[str]] | Parallel calls |
| `allowed_transitions` | dict[node, list[node]] | Graph |
| `max_node_visits` | int or dict[node, int] | Graph |
| `max_revision_rounds` | int | Evaluator-optimizer |
| `max_cost_usd` | float | Budget: cost of the run's LLM calls and paid tool calls |
| `max_tokens` | int | Budget: input plus output tokens of every model call |
| `max_llm_calls` | int | Budget: number of model calls |

Invalid rules raise `ValueError` when the scenario is read: a regular expression that doesn't compile, a negative budget, an unknown `warn_only` check, or ordering rules that contradict each other (`a` before `b` and `b` before `a`, in `expected_order` or `prerequisites`).

## Trace format

A trace is a list of steps, a dict `{"steps": [...], "final_response": "...", "llm_calls": [...]}`, or any object with `get_trace()` (the LangChain handler, a `TraceRecorder`).

```json
{
  "step_index": 1,
  "agent": "billing_agent",
  "node": "refunds",
  "parallel_group": "p1",
  "thought": "The order is refundable.",
  "action": {"type": "tool_call", "name": "issue_refund", "args": {"order_id": "A-1"}},
  "observation": "{\"status\": \"REFUNDED\"}"
}
```

Only `action` is required. `type` defaults to `tool_call`; `arguments` works instead of `args`. A tool step may carry `cost_usd`. Other action types: [Recording pattern events](patterns.md#recording-pattern-events).

Steps recorded in [production](production.md) can carry:

| Field | Meaning |
|---|---|
| `blocked` | `{"rule", "reason"}`: a guard stopped this call |
| `guard_warning` | `{"rule", "reason"}`: the call broke a `warn_only` rule and ran anyway |
| `unconfirmed` | `true`: the model asked for this call, but no result came back |

A call counts as **failed** when its observation:

| Signal | Examples |
|---|---|
| starts with an error | `ERROR: timeout`, `Exception: ...`, `Traceback ...` |
| is JSON reporting one | a set `error`/`errors` field, `"success": false`, `"ok": false`, a `status` like `failed`, `declined` or `timeout`, an HTTP 4xx/5xx code, a non-zero `exit_code` |
| says so in plain text | "failed", "declined", "permission denied", "timed out", "503 Service Unavailable" |

`"error": null`, "0 errors" and `error_rate` aren't failures. The simplest way to record one is an observation starting with `ERROR:`.

`llm_calls` holds each model call's token usage, apart from the steps:

```json
{"model": "gpt-4o-mini", "input_tokens": 1200, "output_tokens": 85, "cached_input_tokens": 1024,
 "cache_write_tokens": 0, "cost_usd": 0.00021, "agent": "billing"}
```

`input_tokens` includes cached tokens. `prompt_tokens` and `completion_tokens` work as names. `cost_usd` (optional) is the provider's real cost. See [Cost tracking](#cost-tracking).

## Report

`evaluate_trace` returns an `EvaluationReport`:

| Attribute | Contents |
|---|---|
| `passed`, `status` | `True` / `"PASSED"` when nothing failed |
| `composite_score` | Weighted average of the five metrics, 0 to 1 |
| `metrics` | `tool_selection`, `argument_correctness`, `call_ordering`, `step_efficiency`, `reasoning_faithfulness` |
| `patterns` | One entry per pattern check that ran: `label`, `passed`, `score`, `violations`, `details` |
| `failures` | Every reason the scenario failed, in plain English |
| `warnings` | Failures of the checks listed in `warn_only`; they don't fail the scenario |
| `cost` | Tokens and cost (`total_usd`, `llm_calls`, `total_tokens`, per `models` and `tools`, `unpriced_models`), or None |
| `judge_audit` | The LLM judge's verdict (`score`, `passed`, `reasoning`, `model`, `error`, its own `usage` and `cost_usd`) |
| `details` | Tool calls, metric findings, steps, final response, cost and `blocked_actions` |

| Method | Does |
|---|---|
| `format()` | The report as readable text |
| `raise_for_failures()` | Raises `EvaluationFailed` (an `AssertionError`) listing every failure |
| `to_dict()` | JSON-ready data |
| `save(path=None)` | Adds the report to `reports/latest_report.json` for the dashboard |
| `sync_to_dashboard(url)` | Sends the report to a running `regshield serve` |

`evaluate_trace(..., save_report=True)` saves the report; `save_reports(reports, path)` saves several.

### Metrics and thresholds

| Metric | Weight | Default | Python | CLI |
|---|:---:|:---:|---|---|
| Tool selection (F1) | 25% | 0.85 | `min_tool_selection` | `--min-tool-selection` |
| Argument correctness | 25% | 0.85 | `min_argument_correctness` | `--min-argument-correctness` |
| Call ordering | 20% | 1.00 | `min_call_ordering` | `--min-call-ordering` |
| Step efficiency | 15% | 0.70 | `min_step_efficiency` | `--min-step-efficiency` |
| Reasoning faithfulness | 15% | 0.85 | `min_reasoning_faithfulness` | `--min-reasoning-faithfulness` |

**Step efficiency** is `optimal / max(optimal, steps)`, minus 0.25 per repeated identical call (at most 0.6). Pattern events don't count as steps.

**Reasoning faithfulness** reads each thought, the final response and messages the agent sent (email, reply, notify, sms, slack... tools). A success claim ("has been refunded", "I sent", "all set") is flagged when it:

- comes right after a failed call or denied approval, unless it's about another tool that succeeded;
- is about a tool whose last call failed or was denied;
- says a tool did something when it never ran.

Details:

- Claims are found per clause: "there was an error, but it was processed" counts.
- Negations, questions, conditionals and partial results ("97 of 100 imported") don't.
- A claim naming one call's argument ("order A-1 was cancelled") is judged by that call.
- Claims backed by another tool's success (a lookup returning "SHIPPED") pass the last two rules.
- Failure words returned by data-reading tools (`list_*`, `search_*`, `get_*`...) are data, not failures.
- It reads wording, not meaning; use the LLM judge for that.

## Algorithms

Every check is a deterministic, classical algorithm: no model, no API key, milliseconds per trace. Only the optional LLM judge calls a model.

| Check | Algorithm |
|---|---|
| Tool selection | F1 score over the sets of expected and invoked tools |
| Argument correctness | Recursive structural matching (numbers, text, objects, lists) against each tool's best-matching call |
| Call ordering | Each `[before, after]` edge of the dependency graph checked against first calls and parallel batches |
| Contradictory rules | Depth-first search with three colours finds a cycle in `expected_order` or `prerequisites`, in O(tools + edges), when the scenario loads |
| Handoff loops | Loop erasure over the handoff path: coming back to an agent already on the path cuts out the loop and counts it, so repeated cycles of any length are found in one pass |
| Step efficiency | Repeated calls found by hashing each call's name and key-sorted arguments |
| Parallel calls | Steps grouped into concurrent batches by `parallel_group` |
| Graph workflows | The node path as layers (fan-out is one layer), each edge checked against the adjacency list; visits counted |
| Plans, agent order | Greedy in-order subsequence matching |
| Reasoning faithfulness | Clause-level rule matching of claims against each tool's own results |
| Rate limits (guard) | A sliding time window per tool |
| Pricing | Exact name, then the longest matching `*` pattern |
| Meaning (optional) | LLM-as-judge on the whole trace |

The graph algorithms live in `regression_shield/core/graphs.py`.

## Scenario files

`regshield eval` reads a JSON list of items:

```json
[
  {"scenario": {...}, "trace": [...], "regression_trace": [...]}
]
```

- `trace`: the recorded run that should pass.
- `regression_trace` (optional): a known-bad trace that must fail. If it passes, the run fails.
- `traces`: several runs instead of `trace`. The item passes when the pass rate reaches `--min-pass-rate` (default 1.0). Runs show as `<scenario_id> [run 2/5]`.

Save a `TraceRecorder`'s `to_dict()` as a trace. `regression_shield/data/sample_scenarios.json` has one item per pattern.

## CLI

```text
regshield eval FILE [options]     Evaluate a scenario file
regshield demo [options]          Evaluate the bundled sample scenarios
regshield serve [options]         Start the local dashboard
regshield pricing refresh         Download the latest model list prices
regshield pricing show MODEL...   Show the price RegShield uses for each model
regshield config show            Every setting in effect, and where it comes from
regshield config init            Write regshield.toml (every setting) and .env.example
regshield --version
```

| Option | Commands | Meaning |
|---|---|---|
| `-v`, `--verbose` | all | Debug logs on stderr |
| `--min-tool-selection` and the other `--min-*` | `eval`, `demo` | Metric thresholds (see above) |
| `--min-pass-rate RATE` | `eval`, `demo` | For items with `traces`: share of runs that must pass (default 1.0) |
| `--report PATH` | `eval`, `demo` | Where to save the report (default `reports/latest_report.json`) |
| `--llm-judge`, `--no-llm-judge` | all | Have the LLM judge score each trace, or not (overrides the config file) |
| `--api-key`, `--model`, `--base-url` | all | Judge settings (default: the environment variables below) |
| `--judge-timeout SECONDS` | all | How long to wait for each judge reply (default 30) |
| `--judge-on-error {fail,pass}` | all | When the judge can't give a verdict (default `fail`) |
| `--host`, `--port`, `--no-open` | `serve` | Interface (default `127.0.0.1`), port (default `8000`), don't open a browser |
| `--from FILE_OR_URL` | `pricing refresh` | Read a copy of LiteLLM's `model_prices_and_context_window.json` instead of downloading it |
| `--output PATH` | `pricing refresh` | Save the list there instead of your user cache; set `REGSHIELD_PRICE_LIST` to use it |
| `--dir PATH`, `--force` | `config init` | Where to write the files (default: the current directory); overwrite existing ones |

Flags left out take their value from the [configuration file](#configuration-file), then the defaults.

- `eval` prints `PASS` or `FAIL` per scenario with reasons, then a summary: regressions caught, routing accuracy and cost.
- `pricing refresh` prints which prices changed.
- `pricing show` exits with `1` for an unpriced model, so CI can check them.

Exit codes: `0` everything passed, `1` a scenario failed or a `regression_trace` passed, `2` bad input (unreadable file, unknown scenario field, `--llm-judge` without a key).

## REST API

`regshield serve` exposes a JSON API on the dashboard's port. Requests must send `Content-Type: application/json`.

| Endpoint | Body | Returns |
|---|---|---|
| `GET /api/status` | | Version and LLM judge status |
| `GET /api/latest-report` | | The saved report file |
| `POST /api/evaluate-trace` | `{"scenario": {...}, "trace": [...]}`, optionally `use_llm_judge` and `min_*` thresholds | The report (as `EvaluationReport.to_dict()`); also saved for the dashboard |
| `POST /api/reports` | A report from `EvaluationReport.to_dict()` | `{"saved": scenario_id}` |
| `POST /api/run-demo` | `{}` | `{"evaluated": 10, "passed": 10}` |

Other fields are rejected. The judge always uses the server's own settings, never a key or endpoint from a request.

## Configuration file

One file for every setting: `regshield.toml`, or `[tool.regshield]` in `pyproject.toml`. pytest, `regshield eval` and production code all read it. `regshield config init` writes one with every setting commented out; `regshield config show` lists what's in effect.

```toml
[tool.regshield]
env_file = ".env"                 # API keys live there, never in this file
min_tool_selection = 0.9          # any of the five min_* thresholds
min_pass_rate = 0.8               # for repeated runs
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
judge_timeout = 120               # seconds
export_otlp_endpoint = "http://localhost:4318"

[tool.regshield.pricing.models]   # USD per 1M tokens; * patterns allowed
"my-finetune*" = { input = 1.0, output = 4.0, cached_input = 0.25 }

[tool.regshield.pricing.tools]    # USD per call
web_search = 0.005
```

Every setting can also come from `REGSHIELD_<SETTING>`:

| Setting | Environment variable | Default | What it does |
|---|---|---|---|
| `min_tool_selection`, `min_argument_correctness`, `min_call_ordering`, `min_step_efficiency`, `min_reasoning_faithfulness` | `REGSHIELD_MIN_TOOL_SELECTION`... | 0.85, 0.85, 1.0, 0.70, 0.85 | [Metric thresholds](#metrics-and-thresholds) |
| `min_pass_rate` | `REGSHIELD_MIN_PASS_RATE` | 1.0 | Share of repeated runs (`traces`) that must pass |
| `llm_judge` | `REGSHIELD_LLM_JUDGE` | `false` | Have the LLM judge score every trace |
| `judge_base_url` | `REGSHIELD_JUDGE_BASE_URL` (or `OPENAI_BASE_URL`, `OPENROUTER_BASE_URL`) | OpenRouter | The judge's OpenAI-compatible endpoint; your own server needs no key |
| `judge_model` | `REGSHIELD_JUDGE_MODEL` (or `JUDGE_MODEL`) | a free OpenRouter model, or `gpt-4.1-mini` with an OpenAI key | The judge's model |
| `judge_timeout` | `REGSHIELD_JUDGE_TIMEOUT` (or `JUDGE_TIMEOUT`) | 30 | Seconds to wait for each verdict |
| `judge_on_error` | `REGSHIELD_JUDGE_ON_ERROR` | `fail` | `fail` or `pass` when the judge can't answer |
| `pricing` | the file only | | Your prices, as the tables above |
| `price_list` | `REGSHIELD_PRICE_LIST` | the bundled or refreshed list | A list prices file ([Keep prices current](production.md#keep-prices-current)) |
| `log_level` | `REGSHIELD_LOG_LEVEL` (or `REGSHIELD_LOG`) | quiet | Print logs: `debug`, `info` or `warning` |
| `env_file` | `REGSHIELD_ENV_FILE` | | A `.env` file to load (below) |
| `export_otlp_endpoint` | `REGSHIELD_EXPORT_OTLP_ENDPOINT` | | `export_traces()`: an OpenTelemetry OTLP/HTTP collector |
| `export_jsonl_path` | `REGSHIELD_EXPORT_JSONL_PATH` | | `export_traces()`: a JSON-lines file |
| `export_http_url` | `REGSHIELD_EXPORT_HTTP_URL` | | `export_traces()`: a URL that receives JSON events |
| `export_service_name` | `REGSHIELD_EXPORT_SERVICE_NAME` | `regshield-agent` | The OpenTelemetry service name |
| `export_sample_rate` | `REGSHIELD_EXPORT_SAMPLE_RATE` | 1.0 | Share of healthy runs exported |
| `export_keep_errors` | `REGSHIELD_EXPORT_KEEP_ERRORS` | `true` | Always export runs where something went wrong |
| `export_max_runs_per_minute` | `REGSHIELD_EXPORT_MAX_RUNS_PER_MINUTE` | no limit | Cap on exported runs |
| `export_capture_content` | `REGSHIELD_EXPORT_CAPTURE_CONTENT` | `false` | Include prompts, arguments and results in exports |

| Source | Priority |
|---|---|
| Arguments and command-line flags | highest |
| Environment variables, including those loaded from `env_file` | |
| The configuration file | |
| Built-in defaults | lowest |

**Keys and `.env` files.** RegShield refuses a configuration file with API keys. Keep keys in the environment (CI secrets) or an uncommitted `.env` named by `env_file`:

```bash
# .env
OPENROUTER_API_KEY=sk-or-...
REGSHIELD_JUDGE_MODEL=qwen2.5:7b    # any setting, for this machine only
```

- The environment wins over `.env`. A missing `.env` is skipped, so CI works with secrets.
- `.env` lines are `NAME=value`, with optional `export`, quotes and `#` comments.
- Paths in the file (`env_file`, `price_list`, `export_jsonl_path`) are relative to it.
- A judge on your own server needs only `judge_base_url` and `judge_model` ([local models](local-models.md)).
- RegShield searches the current directory, then parents, stopping at the first `regshield.toml` or `pyproject.toml`.
- `REGSHIELD_CONFIG=path` picks a file; `REGSHIELD_CONFIG=` (empty) ignores config files.
- Unknown settings raise an error.

## Environment variables

Besides `REGSHIELD_<SETTING>`, RegShield reads these (from the environment or `env_file`):

| Variable | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | Judge key, sent to OpenRouter (takes priority) |
| `OPENAI_API_KEY` | Judge key, sent to OpenAI when `OPENROUTER_API_KEY` isn't set |
| `JUDGE_MODEL`, `JUDGE_TIMEOUT` | Older names for `REGSHIELD_JUDGE_MODEL` and `REGSHIELD_JUDGE_TIMEOUT` |
| `OPENROUTER_BASE_URL`, `OPENAI_BASE_URL` | Judge endpoint, e.g. `http://127.0.0.1:11434/v1` for Ollama ([no key needed](local-models.md)) |
| `REGSHIELD_CONFIG` | The configuration file to use, or empty for none |
| `REGSHIELD_LOG` | Older name for `REGSHIELD_LOG_LEVEL` (any value other than a level means `debug`) |
| `REGSHIELD_CACHE_DIR` | Where `regshield pricing refresh` saves prices (default: your user cache folder) |
| `REGSHIELD_EXPORT_HTTP_HEADERS` | Headers for `export_http_url`, such as `Authorization=Bearer <token>,X-Team=ai`; kept out of the configuration file |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` | Where `OpenTelemetryExporter()` sends spans when you don't pass `endpoint`, and its auth headers |

Arguments (`api_key=`, `--model`...) override the environment.

## Cost tracking

When a trace has `llm_calls` (or tool steps with `cost_usd`), `report.cost` shows usage and cost, and budgets can be checked.

Usage is recorded:

- automatically by the LangChain handler, `instrument_smolagents` and `instrument()`;
- with `recorder.llm_response(response)` or `recorder.llm_call(model, input_tokens, output_tokens)`;
- for paid tools, with `cost_usd=0.005` on `tool_call` or `@recorder.tool`, or `pricing["tools"]`.

Each model call is priced from, in order:

1. a `cost_usd` recorded with the call (the provider's real cost);
2. your pricing: `pricing=` (Python) or `[tool.regshield.pricing]`, by exact name, then the longest matching `*` pattern;
3. the list prices: the bundled snapshot from [LiteLLM's price list](https://github.com/BerriAI/litellm), or a newer one from `regshield pricing refresh` (dated in `report.cost["prices_as_of"]`). Dated names, provider prefixes and Bedrock ids are matched; `report.cost["models"][name]["priced_as"]` shows which entry was used.

Things to know:

- **Local models are free** (`price_source: "local"`): Ollama-style names (`qwen2.5:7b`, `gemma3:latest`), the `ollama/`, `ollama_chat/`, `lm_studio/`, `llamafile/` and `hosted_vllm/` prefixes, and OpenRouter's `:free` variants.
- **Unpriced models** go in `unpriced_models`, mark the total `complete: false`, and fail a `max_cost_usd` budget.
- **Prompt-cache** reads and writes use their own rates when known.
- **Estimates only:** batch discounts, long-context tiers and negotiated prices aren't modelled.
- `scripts/build_pricing.py` regenerates the bundled snapshot before a release ([Keep prices current](production.md#keep-prices-current)).

## Logging

RegShield logs to the `regression_shield` logger, and is quiet by default.

| How | Effect |
|---|---|
| `regshield ... --verbose` | Debug logs for that command |
| `evaluate_trace(..., verbose=True)` | Debug logs from then on |
| `enable_logging("INFO")` | Choose a level |
| `REGSHIELD_LOG=debug` | Turn logs on without changing code |
| `logging.getLogger("regression_shield")` | Configure like any other logger |

`DEBUG` shows steps, metrics, pattern checks, recorder events and judge requests (never the key). `INFO` prints one line per scenario:

```text
[regshield] DEBUG   evaluator: Evaluating 'deploy_gate': 2 steps, 2 tool calls
[regshield] DEBUG   evaluator:   step_efficiency        1.00  2 steps for an optimal 3, 0 repeated call(s)
[regshield] DEBUG   patterns:   pattern policy          PASSED (1.00)
[regshield] INFO    evaluator: 'deploy_gate' PASSED (composite 1.00) in 0.4 ms
```

Logs go to stderr, so stdout stays clean.

## Python API

| Name | Purpose |
|---|---|
| `evaluate_trace(scenario, trace, **options)` | Evaluate one trace; returns an `EvaluationReport` |
| `evaluate_runs(scenario, traces, min_pass_rate=None, **options)` | Evaluate several runs of the same task; returns a `RunsReport` (`pass_rate`, `passed`, `failure_counts`, `reports`, `cost`, `format()`, `raise_for_failures()`) |
| `AgentTraceEvaluator(**options).evaluate(scenario, trace)` | The same, with options set once for many traces (`.evaluate_runs(...)` too) |
| `TraceRecorder(agent=None, guard=None, export=True)` | Record tool calls, pattern events and LLM usage. `with recorder:` makes it active for `instrument()`; `start_run`/`end_run` mark runs; `check`/`check_llm` ask the guard |
| `Guard(scenario, rate_limits=None, warn_only=None, approver=None, pricing=None)` | Enforce a scenario's rules before each action runs (see [In production](production.md)) |
| `ActionBlocked` | Raised for a blocked call: `tool`, `rule`, `reason`, `arguments` |
| `instrument(openai=True, anthropic=True, gemini=True)`, `uninstrument()` | Record SDK calls inside `with recorder:` blocks, and undo it |
| `export_traces(*exporters, sample_rate=1.0, keep_errors=True, max_runs_per_minute=None, max_events_per_run=None)` | Stream runs to exporters; `stop_exporting()` flushes and stops; `export_stats()` counts |
| `OpenTelemetryExporter`, `JSONLExporter`, `HTTPExporter`, `Exporter` | Where exported runs go; subclass `Exporter` for your own |
| `RegressionShieldCallbackHandler(agent=None, guard=None)` | LangChain / LangGraph callback handler (a `TraceRecorder`); `middleware()` and `wrap_tool_call` apply its guard |
| `instrument_smolagents(agent)` | Record a smolagents agent's tool calls as they run |
| `extract_smolagents_trace(agent)` | Rebuild a trace from a finished `ToolCallingAgent`'s memory |
| `shield(scenario, ...)` | Decorator that evaluates each run of a function |
| `run_pattern_checks(scenario, steps)` | Run only the pattern checks |
| `save_reports(reports, path=None)` | Save reports for the dashboard |
| `LLMJudge` | The LLM judge on its own |
| `enable_logging(level)` | Turn on logs |
| `ScenarioSpec`, `StepTrace`, `EvaluationReport`, `EvaluationFailed` | Types |

`evaluate_trace` options: the `min_*` thresholds, `use_llm_judge`, `api_key`, `model`, `base_url`, `judge_on_error`, `judge_timeout`, `pricing`, `save_report`, `dashboard_url` and `verbose`. Unset options come from the [configuration file](#configuration-file), then the defaults.
