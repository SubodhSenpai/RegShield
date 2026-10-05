# RegShield documentation

RegShield checks what your AI agent did (tools, order, arguments, results, claims) against rules you write once.

| Guide | What's in it |
|---|---|
| [Getting started](getting-started.md) | Install, write your first scenario, evaluate a trace, add it to CI |
| [Cookbook](cookbook.md) | Short recipes for common checks, each with the output it produces |
| [Agentic patterns](patterns.md) | Policy, approval, planning, multi-agent, routing, parallel calls, graphs, reflection loops |
| [Integrations](integrations.md) | LangChain, LangGraph, smolagents, `TraceRecorder`, raw SDK loops, `@shield`, REST |
| [In production](production.md) | Block risky actions, record SDK calls, export runs, keep prices current |
| [Local and self-hosted models](local-models.md) | Ollama, vLLM and friends for your agent and the judge |
| [Reference](reference.md) | Scenario fields, formats, the algorithm behind each check, CLI, configuration |
| [Examples](../examples/README.md) | Nine real agents on a local LLM |

New here? Start with [Getting started](getting-started.md), or find your problem in the [Cookbook](cookbook.md).
