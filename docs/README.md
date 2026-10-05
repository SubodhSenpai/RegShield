# RegShield documentation

RegShield checks an AI agent's execution trace (which tools ran, in what order, with which arguments, what came back and what the agent concluded) against rules you write once and run in CI.

| Guide | What's in it |
|---|---|
| [Getting started](getting-started.md) | Install, write your first scenario, evaluate a trace, add it to CI |
| [Cookbook](cookbook.md) | Short recipes for common checks, each with the output it produces |
| [Agentic patterns](patterns.md) | Policy rules, human approval, plan-and-execute, multi-agent handoffs, routing, parallel calls, graph workflows, evaluator-optimizer loops |
| [Integrations](integrations.md) | LangChain, LangGraph, smolagents (`ToolCallingAgent` and `CodeAgent`), any framework via `TraceRecorder`, raw OpenAI/Anthropic/Gemini SDK loops, the `@shield` decorator, the REST API |
| [In production](production.md) | Block risky actions as they happen, record SDK calls with no code changes, send runs to OpenTelemetry or a webhook with sampling, keep prices current |
| [Local and self-hosted models](local-models.md) | Install Ollama, and run your agent and the LLM judge on your own GPU or servers (vLLM, LM Studio, llama.cpp); how local models are priced |
| [Reference](reference.md) | Every scenario field, the trace and report formats, scenario files, CLI, REST API, environment variables, logging |
| [Examples](../examples/README.md) | Nine real agents (LangChain, LangGraph, smolagents, a plain OpenAI loop) run against a local LLM |

New here? Start with [Getting started](getting-started.md), or find your problem in the [Cookbook](cookbook.md).
