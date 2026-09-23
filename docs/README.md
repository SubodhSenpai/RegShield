# RegShield documentation

RegShield tests what your AI agent **does**, not just what it says. It checks the execution trace (which tools ran, in what order, with which arguments, what came back, and what the agent concluded) against rules you write once and run in CI.

| Guide | What's in it |
|---|---|
| [Getting started](getting-started.md) | Install, write your first scenario, evaluate a trace, add it to CI |
| [Agentic patterns](patterns.md) | Policy rules, human approval, plan-and-execute, multi-agent handoffs, routing, parallel calls, graph workflows, evaluator-optimizer loops |
| [Integrations](integrations.md) | LangChain, LangGraph, smolagents (`ToolCallingAgent` and `CodeAgent`), any framework via `TraceRecorder`, the `@shield` decorator, the REST API |
| [Reference](reference.md) | Every scenario field, the trace and report formats, scenario files, CLI, REST API, environment variables, logging |
| [Examples](../examples/README.md) | Nine real agents (LangChain, LangGraph, smolagents, a plain OpenAI loop) run against a local LLM |

New here? Start with [Getting started](getting-started.md), then jump to the pattern your agent uses.
