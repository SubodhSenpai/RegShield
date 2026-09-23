# Reference

- [Scenario fields](#scenario-fields)
- [Trace format](#trace-format)
- [Report](#report)
- [Scenario files](#scenario-files)
- [CLI](#cli)
- [REST API](#rest-api)
- [Environment variables](#environment-variables)
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
| `expected_arguments` | dict[tool, dict] | Expected argument values, scored against the tool's best-matching call. Numbers compare numerically; text ignores case, `_` and `-` |
| `expected_order` | list[str] or list[[before, after]] | A sequence (each tool before the next), or pairs forming a partial order |
| `optimal_step_count` | int | Ideal number of tool calls for step efficiency (default: the number of `expected_tools`, or 3) |
| `metadata` | dict | Your own data, kept in the report and not checked |

### Agentic patterns

Details and examples: [Agentic patterns](patterns.md).

| Field | Type | Pattern |
|---|---|---|
| `forbidden_tools` | list[str] | Policy |
| `max_tool_calls` | dict[tool, int] | Policy |
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

## Trace format

A trace is a list of steps, a dict `{"steps": [...], "final_response": "..."}`, or any object with a `get_trace()` method (the LangChain handler, a `TraceRecorder`).

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

Only `action` is required. `type` defaults to `tool_call`, and `arguments` is accepted instead of `args`. Record a failed call with an observation starting with `ERROR:`. Steps sharing a `parallel_group` ran concurrently. The other action types (`plan`, `handoff`, `approval`, `route`, `node`, `draft`, `critique`) are described in [Recording pattern events](patterns.md#recording-pattern-events).

## Report

`evaluate_trace` returns an `EvaluationReport`:

| Attribute | Contents |
|---|---|
| `passed`, `status` | `True` / `"PASSED"` when nothing failed |
| `composite_score` | Weighted average of the five metrics, 0 to 1 |
| `metrics` | `tool_selection`, `argument_correctness`, `call_ordering`, `step_efficiency`, `reasoning_faithfulness` |
| `patterns` | One entry per pattern check that ran: `label`, `passed`, `score`, `violations`, `details` |
| `failures` | Every reason the scenario failed, in plain English |
| `judge_audit` | The LLM judge's verdict (`score`, `passed`, `reasoning`, `model`, and `error` if it couldn't run) |
| `details` | The tool calls, each metric's findings, the steps and the final response |

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

## Scenario files

`regshield eval` reads a JSON list of items:

```json
[
  {"scenario": {...}, "trace": [...], "regression_trace": [...]}
]
```

`trace` is the recorded run that should pass. `regression_trace` is optional: a known-bad trace that must fail. If it passes, the scenario can't catch that regression and the run fails. The bundled `regression_shield/data/sample_scenarios.json` has one item per pattern.

## CLI

```text
regshield eval FILE [options]     Evaluate a scenario file
regshield demo [options]          Evaluate the bundled sample scenarios
regshield serve [options]         Start the local dashboard
regshield --version
```

| Option | Commands | Meaning |
|---|---|---|
| `-v`, `--verbose` | all | Debug logs on stderr |
| `--min-tool-selection` and the other `--min-*` | `eval`, `demo` | Metric thresholds (see above) |
| `--report PATH` | `eval`, `demo` | Where to save the report (default `reports/latest_report.json`) |
| `--llm-judge` | all | Also have the LLM judge score each trace |
| `--api-key`, `--model`, `--base-url` | all | Judge settings (default: the environment variables below) |
| `--judge-on-error {fail,pass}` | all | When the judge can't give a verdict (default `fail`) |
| `--host`, `--port`, `--no-open` | `serve` | Interface (default `127.0.0.1`), port (default `8000`), don't open a browser |

For each scenario, `eval` prints `PASS` or `FAIL` with the reasons, then a summary with the number of regressed traces caught and, for routing scenarios, the routing accuracy.

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

## Environment variables

RegShield reads these from the environment and does not load `.env` files. Use your shell, CI secrets, or a tool like `dotenv run`.

| Variable | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | Judge key, sent to OpenRouter (takes priority) |
| `OPENAI_API_KEY` | Judge key, sent to OpenAI when `OPENROUTER_API_KEY` isn't set |
| `JUDGE_MODEL` | Judge model (default: a free OpenRouter model, or `gpt-4.1-mini` with an OpenAI key) |
| `OPENROUTER_BASE_URL`, `OPENAI_BASE_URL` | Judge endpoint for the matching key, e.g. `http://127.0.0.1:11434/v1` for Ollama |
| `REGSHIELD_LOG` | Log level: `debug`, `info` or `warning` |

Arguments (`api_key=`, `--model`...) override the environment.

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
| `AgentTraceEvaluator(**options).evaluate(scenario, trace)` | The same, with options set once for many traces |
| `TraceRecorder` | Record tool calls and pattern events from any code |
| `RegressionShieldCallbackHandler` | LangChain / LangGraph callback handler (a `TraceRecorder`) |
| `instrument_smolagents(agent)` | Record a smolagents agent's tool calls as they run |
| `extract_smolagents_trace(agent)` | Rebuild a trace from a finished `ToolCallingAgent`'s memory |
| `shield(scenario, ...)` | Decorator that evaluates each run of a function |
| `run_pattern_checks(scenario, steps)` | Run only the pattern checks |
| `save_reports(reports, path=None)` | Save reports for the dashboard |
| `LLMJudge` | The LLM judge on its own |
| `enable_logging(level)` | Turn on logs |
| `ScenarioSpec`, `StepTrace`, `EvaluationReport`, `EvaluationFailed` | Types |

`evaluate_trace` options: the five `min_*` thresholds, `use_llm_judge`, `api_key`, `model`, `base_url`, `judge_on_error`, `save_report`, `dashboard_url` (send the report to a running dashboard) and `verbose`.
