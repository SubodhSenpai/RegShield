# Examples

Real agents, built with real frameworks and a real LLM, tested with RegShield. Each example
runs an agent, evaluates its trace against a scenario and prints the report.

| File | Framework | What it checks |
|---|---|---|
| [`quickstart.py`](quickstart.py) | none (no LLM) | A good trace and a regressed one, side by side |
| [`01_react_agent_policy.py`](01_react_agent_policy.py) | LangChain `create_agent` | Tool order, arguments, forbidden tools, call caps |
| [`02_human_approval.py`](02_human_approval.py) | LangChain `HumanInTheLoopMiddleware` | Approvals and denials; no success claims after a denial |
| [`03_plan_and_execute.py`](03_plan_and_execute.py) | LangGraph | A plan first, replanning after a failure, graph transitions |
| [`04_multi_agent_supervisor.py`](04_multi_agent_supervisor.py) | `langgraph-supervisor` | Which agent may use which tool, delegation order, data passed between agents |
| [`05_router.py`](05_router.py) | LangChain chat model | Routing accuracy across a set of requests |
| [`06_parallel_calls.py`](06_parallel_calls.py) | LangGraph fan-out | Independent lookups run in parallel; the summary waits for both |
| [`07_graph_and_reflection.py`](07_graph_and_reflection.py) | LangGraph | Writer/reviewer loop: allowed transitions, review rounds, approved output |
| [`08_custom_agent_loop.py`](08_custom_agent_loop.py) | OpenAI SDK, no framework | `TraceRecorder` in your own tool-calling loop |
| [`09_smolagents.py`](09_smolagents.py) | smolagents `CodeAgent`, managed agents | Tool calls from generated code; a manager and a sub-agent |

Only the LangChain, LangGraph and smolagents integrations record things automatically. Plans (03),
routes (05) and drafts and critiques (07) are recorded with one `TraceRecorder` call each.

## Run them

The examples talk to any OpenAI-compatible API. By default they use a local model through
[Ollama](https://ollama.com), so no API key is needed:

```bash
ollama pull qwen2.5:3b
pip install "regression-shield[all]" langchain-openai langgraph-supervisor "smolagents[openai]"
cd examples
python quickstart.py
python 01_react_agent_policy.py
python 02_human_approval.py reject      # or: approve
```

To use a hosted model instead, set three variables (read by [`_llm.py`](_llm.py)):

```bash
export EXAMPLES_BASE_URL=https://api.openai.com/v1
export EXAMPLES_MODEL=gpt-4.1-mini
export EXAMPLES_API_KEY=sk-...
```

Each run saves `reports/latest_report.json`; run `regshield serve` in the same folder to browse it.

## What to expect

LLM agents aren't deterministic, so a report can pass on one run and fail on the next. That is what
RegShield is for. With `qwen2.5:3b`, our runs caught these real mistakes:

| Example | What the agent did wrong | How RegShield reported it |
|---|---|---|
| 01 | Sent the wire in the same batch as the identity check | `'send_wire' (step 5) ran in parallel with its prerequisite 'verify_identity' (step 4)` |
| 02 approve | Chose the refund amount before looking up the policy | `issue_refund.amount was 150, expected 1200` |
| 02 reject | Told the customer the refund was processed after a person rejected it | `Final response claims success right after a denied approval` |
| 03 | Re-ran a search that had already succeeded after replanning | `5 steps for an optimal 3, 1 repeated call(s)` |
| 04 | The billing agent refunded the order twice, for $0 | `'issue_refund' was called 2 times (max 1)` |
| 05 | Sent a login problem to billing | `Routed to 'billing', expected 'technical'` |
| 07 | Published copy the reviewer had rejected three times | `the final draft was rejected by the evaluator` |
| 08 | Answered without tracking the package | `missing ['track_package']` |
| 09 | Converted $1 to GBP instead of the stock price | `convert_currency.amount was 1, expected 431.2` |

A bigger model makes fewer of these mistakes. Keep the scenario the same and compare runs.
