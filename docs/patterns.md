# Agentic patterns

Beyond a single agent calling tools, RegShield checks eight common agent patterns, plus a budget for what a run may cost:

| Pattern | Catches | Scenario fields |
|---|---|---|
| [Policy rules](#policy-rules) | Forbidden tools, runaway call counts, dangerous argument values, acting before a prerequisite succeeded | `forbidden_tools`, `max_tool_calls`, `forbidden_arguments`, `prerequisites` |
| [Human approval](#human-in-the-loop-approval) | Risky actions without sign-off, or after a denial | `requires_approval` |
| [Plan-and-execute](#plan-and-execute) | No plan, unplanned calls, pushing on after a failure | `require_plan`, `expected_plan` |
| [Multi-agent handoffs](#multi-agent-handoffs) | Agents using tools they don't own, wrong hand-off order, ping-pong loops | `agent_tools`, `expected_agents`, `max_handoffs` |
| [Routing](#routing) | Requests sent to the wrong destination | `expected_route` |
| [Parallel calls](#parallel-tool-calls) | Independent calls run one after another, dependent calls run at the same time | `expected_parallel`, `expected_order` pairs |
| [Graph workflows](#graph-workflows) | Illegal node transitions, runaway cycles | `allowed_transitions`, `max_node_visits` |
| [Evaluator-optimizer](#evaluator-optimizer-reflection-loops) | Ignored critiques, rejected final output, too many rounds | `max_revision_rounds` |
| [Budget](#budget) | Runs that cost too much, use too many tokens or make too many model calls | `max_cost_usd`, `max_tokens`, `max_llm_calls` |

## How pattern checks work

- A check runs when your scenario sets one of its fields, or when the trace contains its events, and it appears in the report only if it had something to check. Plain tool-calling traces produce no pattern results, and their scores are unchanged.
- Each check reports `passed`, a `score` (the share of individual checks that passed), `violations` (plain-English reasons) and `details` (what it saw, such as the agent chain or the graph path).
- Any failing pattern fails the scenario and adds a line to `report.failures`, for example `Human Approval: Step 3: 'issue_refund' ran after its approval was denied`.
- Pattern events (plans, handoffs, approvals and so on) don't count as steps for **step efficiency**. The **faithfulness** check still reads their thoughts, and treats a denied approval as a failure: "Your refund has been processed" after a person rejected the refund is flagged.

```python
report = evaluate_trace(scenario, trace)
for key, result in report.patterns.items():
    print(key, result["passed"], result["score"], result["violations"])
```

## Recording pattern events

Patterns show up in a trace as steps whose `action.type` isn't `tool_call`, plus three optional step fields:

| Event | Step `action` |
|---|---|
| Plan | `{"type": "plan", "steps": ["search", "book"]}` |
| Handoff | `{"type": "handoff", "to": "billing_agent"}` |
| Approval | `{"type": "approval", "tool": "issue_refund", "approved": true, "by": "lead@acme.com"}` |
| Route | `{"type": "route", "to": "billing"}` |
| Graph node | `{"type": "node", "name": "review"}` |
| Draft | `{"type": "draft", "content": "..."}` |
| Critique | `{"type": "critique", "approved": false, "feedback": "..."}` |

| Step field | Meaning |
|---|---|
| `agent` | Which agent took the step. With a `TraceRecorder`, steps after a handoff belong to the new agent. |
| `node` | The graph node the step ran in. |
| `parallel_group` | Steps with the same value ran concurrently, even if other steps were recorded between them. |

The [LangChain/LangGraph](integrations.md#langgraph) and [smolagents](integrations.md#smolagents) integrations record graph nodes, parallel calls, agents, handoffs and human approvals automatically. For everything else, a [`TraceRecorder`](integrations.md#any-framework-tracerecorder) has one method per event.

---

## Policy rules

Hard rules for any agent.

```python
scenario = {
    "scenario_id": "wire_transfer",
    "expected_tools": ["verify_identity", "execute_transfer"],
    "forbidden_tools": ["delete_customer", "drop_table"],   # never call these
    "max_tool_calls": {"execute_transfer": 1},             # no double transfers
}
```

This matters because tool selection is a *score*: an agent that calls every expected tool **plus** `delete_customer` can still score 0.86 and pass the 0.85 threshold. `forbidden_tools` fails it outright.

Two more rules cover what a tool name can't:

```python
scenario = {
    "scenario_id": "code_freeze",
    # Argument values a tool must never get: regular expressions, matched case-insensitively
    "forbidden_arguments": {
        "run_sql": {"query": r"\b(insert|update|delete|drop|truncate|alter)\b"},
        "*": {"path": [r"^~", r"^[a-z]:[\\/]?$", r"^/$"]},   # "*": any tool (or any argument)
    },
    # Tools that must have succeeded before another tool may run
    "prerequisites": {"deploy": ["run_tests"], "move_file": ["create_folder"]},
}
```

- **`forbidden_arguments`** matters for generic tools (SQL, shell, HTTP, file paths), where the danger is in the arguments: an agent asked to keep a code freeze that runs `DELETE` through a read-only query tool, or a cleanup that deletes a drive root. Objects and lists are matched as JSON text.
- **`prerequisites`** goes further than `expected_order`, which only checks that tools ran in order: each call to `deploy` needs `run_tests` to have run in an earlier step, and its latest result before the deploy to be a success. An agent that deploys after the tests failed, or moves files after the folder couldn't be created, fails. If the gated tool never runs, nothing is violated.

Violations look like:

- `Step 3: called forbidden tool 'delete_customer'`
- `'execute_transfer' was called 2 times (max 1)`
- `Step 2: run_sql.query matches forbidden pattern /\b(insert|update|delete|drop|truncate|alter)\b/: 'DELETE FROM users WHERE id = 2'`
- `Step 2: 'deploy' ran after its prerequisite 'run_tests' failed (step 1)`
- `Step 1: 'deploy' ran before its prerequisite 'run_tests' succeeded`

---

## Human-in-the-loop approval

Risky tools must get a human's approval first, one approval per call.

```python
scenario = {
    "scenario_id": "big_refund",
    "expected_tools": ["check_refund_policy", "issue_refund"],
    "requires_approval": ["issue_refund"],
}
```

Recording:

```python
recorder.approval("issue_refund", approved=True, by="supervisor@acme.com")
issue_refund(order_id="ORD-1204", amount=1200)   # a recorder-wrapped tool
```

An approval without `tool` covers the next call to any guarded tool. Even without `requires_approval`, a tool named in a **denied** approval is checked for running anyway. With LangChain's `HumanInTheLoopMiddleware`, approvals are recorded automatically from your resume decisions.

After a denial, the faithfulness check also makes sure the agent doesn't tell the user the action happened.

Violations:

- `Step 3: 'issue_refund' ran without approval`
- `Step 3: 'issue_refund' ran after its approval was denied`

---

## Plan-and-execute

A planner writes a plan and an executor carries it out, replanning when a step fails.

```python
scenario = {
    "scenario_id": "trip_booking",
    "expected_tools": ["search_flights", "book_flight", "send_confirmation"],
    "require_plan": True,                                              # plan before the first tool call
    "expected_plan": ["search_flights", "book_flight", "send_confirmation"],  # optional; implies require_plan
}
```

Recording:

```python
recorder.plan(["search_flights", "book_flight", "send_confirmation"])
search_flights(to="SFO")
book_flight(flight="UA-220")          # returns an error
recorder.plan(["book_flight", "send_confirmation"], thought="UA-220 failed; replanning")
book_flight(flight="UA-221")
send_confirmation(pnr="K7XQ2P")
```

Plan steps are tool names, or dicts with a `"tool"` key.

What's checked:

- **A plan comes first** (with `require_plan` / `expected_plan`).
- **The first plan contains `expected_plan`** in order (other steps may be in between).
- **Calls stay in the current plan.** Each call after a plan must be one of that plan's steps.
- **The final plan is completed in order.** Every step of the last plan runs, first runs in plan order.
- **No blind continuation.** After a failed call, the next call must retry the same tool, or a new plan must come first.

Violations:

- `No plan was made` / `Step 1: 'search_flights' ran before any plan was made`
- `Step 4: 'check_weather' is not in the plan`
- `Step 4: continued with 'check_weather' after 'book_flight' failed (step 3) without replanning`
- `Planned step 'send_confirmation' never ran`

---

## Multi-agent handoffs

Several agents, such as a triage agent and specialists, pass control between them.

```python
scenario = {
    "scenario_id": "support_refund",
    "expected_tools": ["lookup_order", "issue_refund"],
    "agent_tools": {                         # which tools each agent may use
        "triage_agent": ["lookup_order"],
        "billing_agent": ["issue_refund"],
    },
    "expected_agents": ["triage_agent", "billing_agent"],   # order agents take control in
    "max_handoffs": 2,
}
```

Recording:

```python
recorder = TraceRecorder(agent="triage_agent")
lookup_order(order_id="ORD-7731")      # tagged agent=triage_agent
recorder.handoff("billing_agent")
issue_refund(order_id="ORD-7731")      # tagged agent=billing_agent
```

Agents not listed in `agent_tools` aren't restricted. `expected_agents` must appear in order within the actual chain, and other agents may take part in between. Two agents handing off to each other 4 or more times is always flagged as a loop.

The agent chain lists agents in the order they **acted**. A handoff is a request: its target joins the chain when it takes a step (or when the trace ends), not if another agent acts first. So when a supervisor asks for two transfers at once and only one agent runs, only that agent appears. With langgraph-supervisor, swarms and smolagents managed agents, agents and handoffs are recorded automatically.

Violations:

- `Step 2: agent 'triage_agent' called 'issue_refund', which isn't in its allowed tools`
- `Expected agents triage_agent -> billing_agent, got triage_agent -> support_agent`
- `4 handoffs (max 2)`
- `Agents 'billing_agent' and 'triage_agent' handed off to each other 4 times`

---

## Routing

A router sends each request to one destination, such as a tool, a sub-agent or a queue.

```python
scenario = {"scenario_id": "double_charge", "expected_route": "billing"}   # or ["billing", "refunds"]
```

Recording:

```python
recorder.route("billing", thought="The customer was charged twice.")
```

The first routing decision is compared, ignoring case and surrounding spaces. Across a scenario file, the CLI also reports overall accuracy:

```text
Routing accuracy: 18/20 (90%)
```

Violations: `Routed to 'technical_support', expected 'billing'` / `No routing decision was recorded`

---

## Parallel tool calls

Independent calls should run concurrently, and dependent calls must not.

```python
scenario = {
    "scenario_id": "trip_research",
    "expected_tools": ["get_weather", "get_flight_prices", "summarize_options"],
    "expected_parallel": [["get_weather", "get_flight_prices"]],          # should run together
    "expected_order": [["get_weather", "summarize_options"],             # [before, after] pairs:
                       ["get_flight_prices", "summarize_options"]],       # a partial order
}
```

Recording:

```python
with recorder.parallel():
    get_weather(city="Lisbon")
    get_flight_prices(to="LIS")
summarize_options(city="Lisbon")
```

`expected_order` accepts a plain list (each tool before the next) or `[before, after]` pairs for partial orders. When a prerequisite and its dependent share a parallel group, that's an ordering violation: the dependent started before the prerequisite's result existed.

Parallel groups are recorded automatically when a LangChain model or a smolagents `ToolCallingAgent` requests several tools at once, and for LangGraph fan-out branches.

Violations:

- `get_weather, get_flight_prices should run in parallel but ran one after another`
- `'summarize_options' (step 3) ran in parallel with its prerequisite 'get_flight_prices' (step 2)`

---

## Graph workflows

Agents built as graphs, such as LangGraph state machines, should only move along allowed edges.

```python
scenario = {
    "scenario_id": "content_pipeline",
    "expected_tools": ["write_draft", "publish_post"],
    "allowed_transitions": {"draft": ["review"], "review": ["draft", "publish"]},
    "max_node_visits": {"review": 3},        # or an int for every node
}
```

With LangGraph and the RegShield callback handler, nodes are recorded automatically (see [Integrations](integrations.md#langgraph)). Otherwise:

```python
recorder.node("draft");   write_draft(topic="Agents in production")
recorder.node("review")
recorder.node("publish"); publish_post(slug="agents-in-production")
```

The check runs only when `allowed_transitions` or `max_node_visits` is set. A node counts as entered once per graph step, however many steps or parallel tasks run inside it. **List every node that has outgoing edges**: a node missing from `allowed_transitions` has none allowed.

Nodes that run in the same step (fan-out) form one layer, shown as a list in the path: `[['prices', 'weather'], 'summary']`. A node after a layer may be reached from any node in it, so list only the graph's real edges, such as `{"weather": ["summary"], "prices": ["summary"]}`.

Violations:

- `Step 3: 'draft' -> 'publish' is not an allowed transition`
- `Node 'review' was entered 5 times (max 3)`
- `No graph nodes were recorded`

---

## Evaluator-optimizer (reflection) loops

A generator drafts output and an evaluator critiques it, looping until the evaluator approves.

```python
scenario = {"scenario_id": "ad_copy", "max_revision_rounds": 3}
```

Recording:

```python
recorder.draft("RegShield is an evaluation SDK with many features.")
recorder.critique(approved=False, feedback="Lead with the benefit.")
recorder.draft("Catch agent regressions before your users do.")
recorder.critique(approved=True)
```

What's checked, even without configuration:

- **Critiques are acted on.** A draft right after a rejection must differ from the rejected one (ignoring case and whitespace).
- **The output ends approved.** If the last event is a rejecting critique, the loop shipped rejected work.
- **Rounds stay under the cap** (`max_revision_rounds` counts critiques).

Violations:

- `Step 3: revision is unchanged after the critique at step 2`
- `Step 4: the final draft was rejected by the evaluator`
- `4 review rounds (max 3)`

---

## Budget

Limits on what one run may spend, checked against the token usage recorded with the trace.

```python
scenario = {
    "scenario_id": "monthly_report",
    "max_cost_usd": 0.10,     # LLM calls plus paid tool calls
    "max_tokens": 50_000,     # input + output tokens of every model call
    "max_llm_calls": 8,       # a cap on model calls catches runaway loops early
}
```

The LangChain/LangGraph handler and `instrument_smolagents` record each model call's usage automatically. Elsewhere, call `recorder.llm_response(response)` with the SDK response, or `recorder.llm_call(model, input_tokens, output_tokens)`. Model calls are priced from a bundled snapshot of public list prices, unless the trace carries the real cost (OpenRouter reports it) or you set your own prices (see [Cost tracking](reference.md#cost-tracking)).

A budget fails rather than passes when it can't be checked: no usage was recorded, or a model has no price. Add local or fine-tuned models to your pricing, for example `{"models": {"qwen*": {"input": 0, "output": 0}}}`.

Violations:

- `Cost $0.1275 is over the $0.1000 budget (gpt-4o $0.1275)`
- `55,800 tokens (max 40,000)`
- `6 LLM calls (max 5)`
- `Cost unknown: no price for 'my-model'; add it to your pricing`

---

## Code agents

Code agents, such as smolagents' `CodeAgent`, call tools from Python code they write, so their messages don't list individual tool calls. RegShield records calls **as the tools actually run** instead. See [smolagents `CodeAgent`](integrations.md#smolagents-codeagent) or wrap tools with [`TraceRecorder.tool`](integrations.md#any-framework-tracerecorder). Every check above then works for code agents too.

## Try them all

The bundled samples include a passing and a failing trace for every pattern:

```bash
regshield demo            # evaluates both traces and reports how many regressions were caught
regshield serve           # click "Run demo", then open "Baseline vs. Regression"
```

For real agents, built with LangChain, LangGraph and smolagents and run against a local LLM, see [examples/](../examples/README.md).
