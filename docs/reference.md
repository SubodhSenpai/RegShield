# Reference

- [Scenario fields](#scenario-fields)
- [Trace format](#trace-format)
- [Report](#report)
- [Scenario files](#scenario-files)
- [CLI](#cli)
- [REST API](#rest-api)
- [Configuration file](#configuration-file)
- [Environment variables](#environment-variables)
- [Cost tracking](#cost-tracking)
- [Logging](#logging)
- [Python API](#python-api)

## Scenario fields

Pass a dict or a `ScenarioSpec`. Every field is optional except `scenario_id`; leave a field out to skip its check. An unknown field name raises `ValueError`, so typos don't silently disable a check.

### Core

| Field | Type | Meaning |
|---|---|---|
| `scenario_id` | str | Name used in reports |
| `title`, `domain` | str | Labels for reports and the dashboard |
| `goal` | str | What the agent should achieve; given to the LLM judge |
| `expected_tools` | list[str] | Tools that should run. Scored as F1: missing and unexpected tools both count |
| `expected_arguments` | dict[tool, dict] | Expected argument values, scored against the tool's best-matching call. Numbers compare numerically; text ignores case, `_` and `-`; objects and lists compare item by item (key order doesn't matter); booleans only match booleans or `"true"`/`"false"` |
| `expected_order` | list[str] or list[[before, after]] | A sequence (each tool before the next), or pairs forming a partial order |
| `optimal_step_count` | int | Ideal number of tool calls for step efficiency (default: the number of `expected_tools`, or 3) |
| `warn_only` | list[str] | Checks whose failures are reported as `warnings` and don't fail the scenario: metric names, pattern keys (`policy`, `budget`...) or `llm_judge` |
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

Invalid rules (a regular expression that doesn't compile, a negative budget, an unknown `warn_only` check) raise `ValueError` when the scenario is read.

## Trace format

A trace is a list of steps, a dict `{"steps": [...], "final_response": "...", "llm_calls": [...]}`, or any object with a `get_trace()` method (the LangChain handler, a `TraceRecorder`; their `llm_calls` and `final_response` are read too).

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

Only `action` is required. `type` defaults to `tool_call`, and `arguments` is accepted instead of `args`. Steps sharing a `parallel_group` ran concurrently. A tool step may carry `cost_usd`, what that call cost (paid APIs). The other action types (`plan`, `handoff`, `approval`, `route`, `node`, `draft`, `critique`) are described in [Recording pattern events](patterns.md#recording-pattern-events).

Steps recorded in production can carry three more fields (see [In production](production.md)):

| Field | Meaning |
|---|---|
| `blocked` | `{"rule", "reason"}`: a guard stopped this call, so it didn't run. The observation says why. |
| `guard_warning` | `{"rule", "reason"}`: the call broke a `warn_only` rule and ran anyway. |
| `unconfirmed` | `true`: `instrument()` saw a model ask for this call, but its result never came back. |

A call counts as **failed** when its observation:

| Signal | Examples |
|---|---|
| starts with an error | `ERROR: timeout`, `Exception: ...`, `Traceback ...` |
| is a JSON object (or dict) that reports one | an `error`/`errors` field that is set, `"success": false` or `"ok": false`, a `status` such as `failed`, `declined`, `denied`, `rejected`, `timeout`, `unauthorized`, `not_found`, an HTTP status code from 400 to 599, a non-zero `exit_code` |
| says so in plain text | "failed", "declined", "permission denied", "timed out", "503 Service Unavailable" |

Results reporting the absence of errors (`"error": null`, "0 errors", "0 failed") and metrics named after errors (`error_rate`) aren't failures. The simplest way to record a failure is still an observation starting with `ERROR:`.

`llm_calls` records each model call's token usage, kept apart from the steps so it never changes step numbers:

```json
{"model": "gpt-4o-mini", "input_tokens": 1200, "output_tokens": 85, "cached_input_tokens": 1024,
 "cache_write_tokens": 0, "cost_usd": 0.00021, "agent": "billing"}
```

`input_tokens` counts all input tokens, including cached ones. `prompt_tokens` and `completion_tokens` are accepted as names. `cost_usd` (optional) is the real cost when the provider reports it. See [Cost tracking](#cost-tracking).

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
| `cost` | Tokens and cost of the run (`total_usd`, `llm_calls`, `total_tokens`, per `models` and `tools`, `unpriced_models`), or None when nothing was recorded |
| `judge_audit` | The LLM judge's verdict (`score`, `passed`, `reasoning`, `model`, `error` if it couldn't run, and its own `usage` and `cost_usd` when the API reports usage) |
| `details` | The tool calls, each metric's findings, the steps, the final response, the cost, and `blocked_actions` (calls a guard stopped) when there were any |

| Method | Does |
|---|---|
| `format()` | The report as readable text |
| `raise_for_failures()` | Raises `EvaluationFailed` (an `AssertionError`) listing every failure |
| `to_dict()` | JSON-ready data |
| `save(path=None)` | Adds the report to `reports/latest_report.json` for the dashboard |
| `sync_to_dashboard(url)` | Sends the report to a running `regshield serve` |

`evaluate_trace(..., save_report=True)` saves the report (pass a path to choose the file). `save_reports(reports, path)` saves several at once.

### Metrics and thresholds

| Metric | Weight | Default | Python | CLI |
|---|:---:|:---:|---|---|
| Tool selection (F1) | 25% | 0.85 | `min_tool_selection` | `--min-tool-selection` |
| Argument correctness | 25% | 0.85 | `min_argument_correctness` | `--min-argument-correctness` |
| Call ordering | 20% | 1.00 | `min_call_ordering` | `--min-call-ordering` |
| Step efficiency | 15% | 0.70 | `min_step_efficiency` | `--min-step-efficiency` |
| Reasoning faithfulness | 15% | 0.85 | `min_reasoning_faithfulness` | `--min-reasoning-faithfulness` |

Step efficiency is `optimal / max(optimal, steps)`, minus 0.25 per repeated identical call (at most 0.6). Pattern events such as plans and handoffs don't count as steps.

Reasoning faithfulness checks each thought, the final response, and the text of messages the agent sent (tools named like email, reply, notify, sms, slack...). A success claim ("has been refunded", "I sent", "completed", "all set") is flagged when:

- it comes right after a failed call or a denied approval, unless it's about another tool, one that succeeded;
- it's about a tool whose last call failed or was denied, even with other calls after it;
- it says an action was done by a tool that never ran ("your order has been refunded", "I called export_data"), for tools the trace or scenario names.

Claims are found per clause, so "there was an error, but it was processed" still counts, while negations ("has not been processed"), questions, conditionals and partial results ("97 of 100 records were imported") don't. A claim that names one call's argument ("order A-1 was cancelled") is judged by that call when the same tool also failed for another one. The last two rules skip claims backed by another tool's successful result (a lookup that returned "SHIPPED"). Failure words in the results of data-reading tools (`list_*`, `search_*`, `get_*`...) are treated as data, not as a failed call. The check reads wording, not meaning; use the LLM judge for that.

## Scenario files

`regshield eval` reads a JSON list of items:

```json
[
  {"scenario": {...}, "trace": [...], "regression_trace": [...]}
]
```

`trace` is the recorded run that should pass. `regression_trace` is optional: a known-bad trace that must fail. If it passes, the scenario can't catch that regression and the run fails. The bundled `regression_shield/data/sample_scenarios.json` has one item per pattern.

Instead of `trace`, an item can have `traces`: several recorded runs of the same task. The item passes when the share of passing runs reaches `--min-pass-rate` (default 1.0: every run). Each run is saved to the report as `<scenario_id> [run 2/5]`. A `TraceRecorder`'s `to_dict()` (steps, final response and LLM usage) can be saved as a trace.

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

`pricing refresh` prints how many models are priced, and which prices changed since the list in use. `pricing show` exits with `1` when a model has no price, so a CI step can check that every model you use is priced.

For each scenario, `eval` prints `PASS` or `FAIL` with the reasons, then a summary with the number of regressed traces caught and, for routing scenarios, the routing accuracy. When traces record usage, it also prints what the runs cost, and what the LLM judge's own calls cost.

Exit codes: `0` everything passed, `1` a scenario failed or a `regression_trace` passed, `2` bad input (unreadable file, unknown scenario field, `--llm-judge` without a key).

## REST API

`regshield serve` exposes a JSON API on the same port as the dashboard. Requests must send `Content-Type: application/json`.

| Endpoint | Body | Returns |
|---|---|---|
| `GET /api/status` | | Version and LLM judge status |
| `GET /api/latest-report` | | The saved report file |
| `POST /api/evaluate-trace` | `{"scenario": {...}, "trace": [...]}`, optionally `use_llm_judge` and `min_*` thresholds | The report (as `EvaluationReport.to_dict()`); also saved for the dashboard |
| `POST /api/reports` | A report from `EvaluationReport.to_dict()` | `{"saved": scenario_id}` |
| `POST /api/run-demo` | `{}` | `{"evaluated": 10, "passed": 10}` |

Other fields in `evaluate-trace` requests are rejected. The judge always uses the server's own settings, never a key or endpoint from a request.

## Configuration file

Every setting can live in one file: a `regshield.toml`, or `[tool.regshield]` in `pyproject.toml`. pytest, `regshield eval` and your production code all read it. `regshield config init` writes a `regshield.toml` that lists every setting, commented out, plus a `.env.example` for keys. `regshield config show` lists the settings in effect and where each one comes from.

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

Every setting can also come from an environment variable named `REGSHIELD_` followed by the setting's name in capitals:

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

**Keys and `.env` files.** API keys never go in the configuration file, and RegShield refuses one that has them. Keep keys in the environment (CI secrets), or in a `.env` file you don't commit, named by `env_file = ".env"`:

```bash
# .env
OPENROUTER_API_KEY=sk-or-...
REGSHIELD_JUDGE_MODEL=qwen2.5:7b    # any setting, for this machine only
```

Variables already set in the environment win over the file. A missing `.env` is skipped, so the same configuration works in CI, where keys come from secrets. Lines are `NAME=value`, with optional `export`, quotes and `#` comments. Paths in the configuration file (`env_file`, `price_list`, `export_jsonl_path`) are relative to the file.

For a judge on your own server, `judge_base_url` and `judge_model` are all it needs: a server on your machine or private network gets no key ([Local and self-hosted models](local-models.md)).

RegShield looks for the file in the current directory, then each parent, and stops at the first directory with a `regshield.toml` or a `pyproject.toml` (a `pyproject.toml` without `[tool.regshield]` means no settings). `REGSHIELD_CONFIG=path` uses that file instead; `REGSHIELD_CONFIG=` (empty) ignores config files. Unknown settings raise an error.

## Environment variables

Besides `REGSHIELD_<SETTING>` for every setting above, RegShield reads these, from the environment or from the `env_file` your configuration names:

| Variable | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | Judge key, sent to OpenRouter (takes priority) |
| `OPENAI_API_KEY` | Judge key, sent to OpenAI when `OPENROUTER_API_KEY` isn't set |
| `JUDGE_MODEL`, `JUDGE_TIMEOUT` | Older names for `REGSHIELD_JUDGE_MODEL` and `REGSHIELD_JUDGE_TIMEOUT` |
| `OPENROUTER_BASE_URL`, `OPENAI_BASE_URL` | Judge endpoint, e.g. `http://127.0.0.1:11434/v1` for Ollama. A server on your machine or private network needs no key (see [Local and self-hosted models](local-models.md)) |
| `REGSHIELD_CONFIG` | The configuration file to use, or empty for none |
| `REGSHIELD_LOG` | Older name for `REGSHIELD_LOG_LEVEL` (any value other than a level means `debug`) |
| `REGSHIELD_CACHE_DIR` | Where `regshield pricing refresh` saves prices (default: your user cache folder) |
| `REGSHIELD_EXPORT_HTTP_HEADERS` | Headers for `export_http_url`, such as `Authorization=Bearer <token>,X-Team=ai`; kept out of the configuration file |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` | Where `OpenTelemetryExporter()` sends spans when you don't pass `endpoint`, and its auth headers |

Arguments (`api_key=`, `--model`...) override the environment.

## Cost tracking

When a trace has `llm_calls` (or tool steps with `cost_usd`), the report's `cost` shows what the run used and cost, and the `max_cost_usd`, `max_tokens` and `max_llm_calls` budgets can be checked.

Usage is recorded:

- automatically by the LangChain/LangGraph handler (each model call's `usage_metadata`, model name and, with OpenRouter, the reported cost), by `instrument_smolagents` (each step's `token_usage`), and by `instrument()` for OpenAI, Anthropic and Gemini SDK calls inside a `with recorder:` block;
- with `recorder.llm_response(response)` for an OpenAI, Anthropic or Gemini SDK response or a LangChain message, or `recorder.llm_call(model, input_tokens, output_tokens)`;
- for paid tools, with `recorder.tool_call(..., cost_usd=0.005)`, `@recorder.tool(cost_usd=0.005)`, or a price per call in `pricing["tools"]`.

Each model call is priced from, in order:

1. a `cost_usd` recorded with the call (the provider's real cost);
2. your pricing: `pricing=` (Python) or `[tool.regshield.pricing]`, by exact name, then the longest matching `*` pattern;
3. the list prices in use: the snapshot bundled in `regression_shield/data/pricing.json`, generated from [LiteLLM's price list](https://github.com/BerriAI/litellm), or a newer list saved by `regshield pricing refresh` (the date is in `report.cost["prices_as_of"]`). Dated names (`gpt-4o-2024-08-06`), provider prefixes (`openai/gpt-4o`, `meta-llama/...` on OpenRouter) and Bedrock ids are matched to their entry. When the snapshot lists a model only at other providers, the closest listing is used: the model maker's own first, then OpenRouter, then other resellers. `report.cost["models"][name]["priced_as"]` shows which entry priced each model; set your own price when you need your provider's exact numbers.

Local and self-hosted models cost nothing per token (`price_source: "local"`). This covers Ollama-style names with a size or variant tag (`qwen2.5:7b`, `gemma3:latest`) and the `ollama/`, `ollama_chat/`, `lm_studio/`, `llamafile/` and `hosted_vllm/` prefixes; give them your own price to count GPU cost. OpenRouter's `:free` variants are free as well. A model without a price is listed in `unpriced_models` and leaves `total_usd` incomplete (`complete: false`); a `max_cost_usd` budget then fails. Prompt-cache reads and writes are priced at their own rates when the snapshot has them. Batch discounts, long-context tiers and negotiated prices aren't modelled, so treat the cost as a list-price estimate. `regshield pricing refresh` downloads the latest list prices (see [Keep prices current](production.md#keep-prices-current)); `scripts/build_pricing.py` regenerates the bundled snapshot before a release.

## Logging

RegShield logs through Python's `logging` module under the `regression_shield` logger, and is quiet by default.

| How | Effect |
|---|---|
| `regshield ... --verbose` | Debug logs for that command |
| `evaluate_trace(..., verbose=True)` | Debug logs from then on |
| `enable_logging("INFO")` | Choose a level |
| `REGSHIELD_LOG=debug` | Turn logs on without changing code |
| `logging.getLogger("regression_shield")` | Configure like any other logger |

At `DEBUG` you see each scenario's steps, every metric with its findings, each pattern check, recorder events, judge requests (model, endpoint and timing, never the key) and dashboard requests. At `INFO`, one line per scenario:

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
| `TraceRecorder(agent=None, guard=None, export=True)` | Record tool calls, pattern events and LLM usage (`llm_call`, `llm_response`) from any code; `to_dict()` exports the whole run. `with recorder:` makes it the active recorder for `instrument()` and one exported run; `start_run(name, **attributes)` and `end_run()` mark runs; `check(name, args)` and `check_llm()` ask the guard |
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

`evaluate_trace` options: the five `min_*` thresholds, `use_llm_judge`, `api_key`, `model`, `base_url`, `judge_on_error`, `judge_timeout` (seconds), `pricing` (see [Cost tracking](#cost-tracking)), `save_report`, `dashboard_url` (send the report to a running dashboard) and `verbose`. Options left as `None` come from the [configuration file](#configuration-file), then the defaults.
