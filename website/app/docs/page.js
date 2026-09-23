'use client';

import { useState } from 'react';

const SECTIONS = [
  { id: 'quickstart',   label: 'Quickstart' },
  { id: 'scenario',     label: 'Scenario Spec' },
  { id: 'metrics',      label: 'Metrics' },
  { id: 'patterns',     label: 'Agentic Patterns' },
  { id: 'recorder',     label: 'TraceRecorder' },
  { id: 'langchain',    label: 'LangChain' },
  { id: 'langgraph',    label: 'LangGraph' },
  { id: 'smolagents',   label: 'smolagents' },
  { id: 'codeagent',    label: 'Code Agents' },
  { id: 'decorator',    label: '@shield' },
  { id: 'cicd',         label: 'CI/CD Gate' },
  { id: 'rest',         label: 'REST API' },
  { id: 'logging',      label: 'Logging (--verbose)' },
];

const CONTENT = {
  quickstart: {
    label: 'Getting Started',
    title: 'Install and evaluate in 2 minutes',
    code: `pip install regression-shield`,
    snippet: `from regression_shield import evaluate_trace

trace = [
    {"thought": "Run the security scan first.",
     "action": {"name": "security_scan", "args": {"target": "repo"}},
     "observation": "Vulnerabilities: 0"},
    {"thought": "Clean. Publishing the release.",
     "action": {"name": "publish_release", "args": {"tag": "v1.0.0"}},
     "observation": "Published"},
]

report = evaluate_trace(
    scenario={
        "scenario_id": "release_gate",
        "expected_tools": ["security_scan", "publish_release"],
        "expected_order": ["security_scan", "publish_release"],
    },
    trace=trace,
)

print(report.format())          # scores, pattern checks, every failure
print(report.passed)            # True
report.raise_for_failures()     # in pytest: fails the test with every reason`,
    lang: 'python',
  },
  scenario: {
    label: 'Scenario Spec',
    title: 'Describe what the agent should do',
    snippet: `# A Python dict, or a JSON object in a scenario file
scenario = {
    "scenario_id": "deploy_gate",                 # the only required field
    "title": "Cloud deploy pipeline",
    "expected_tools": ["run_unit_tests", "deploy_production"],
    "expected_order": ["run_unit_tests", "deploy_production"],
    "expected_arguments": {"deploy_production": {"env": "staging"}},
    "forbidden_tools": ["drop_database"],
    "metadata": {"owner": "platform-team"},       # your own data, not checked
}

# A misspelled field raises ValueError instead of silently skipping a check
report = evaluate_trace(scenario, trace)`,
    lang: 'python',
    fields: [
      { name: 'scenario_id',         type: 'str',        desc: 'Name used in reports and the dashboard. The only required field.' },
      { name: 'title / domain / goal', type: 'str',      desc: 'Labels. goal is also given to the LLM judge.' },
      { name: 'expected_tools',      type: 'list[str]',  desc: 'Tools that should run, scored as F1: missing and unexpected tools both lower it.' },
      { name: 'expected_order',      type: 'list',       desc: 'A sequence, or [before, after] pairs for a partial order.' },
      { name: 'expected_arguments',  type: 'dict',       desc: 'Expected argument values per tool. Numbers compare numerically; text ignores case, _ and -.' },
      { name: 'optimal_step_count',  type: 'int',        desc: 'Ideal number of tool calls (default: the number of expected_tools, or 3).' },
      { name: 'forbidden_tools',     type: 'list[str]',  desc: 'Tools the agent must never call. Any call fails the scenario.' },
      { name: 'max_tool_calls',      type: 'dict',       desc: 'Per-tool call caps, e.g. {"issue_refund": 1}.' },
      { name: 'requires_approval',   type: 'list[str]',  desc: 'Tools that need an approved human approval before each call.' },
      { name: 'require_plan',        type: 'bool',       desc: 'A plan must come before the first tool call.' },
      { name: 'expected_plan',       type: 'list[str]',  desc: 'Steps the first plan must contain, in order.' },
      { name: 'agent_tools',         type: 'dict',       desc: 'Which tools each agent may use, e.g. {"billing": ["issue_refund"]}.' },
      { name: 'expected_agents',     type: 'list[str]',  desc: 'Agents that should act, in this order.' },
      { name: 'max_handoffs',        type: 'int',        desc: 'Cap on handoffs between agents.' },
      { name: 'expected_route',      type: 'str | list', desc: 'Where a router should send the request.' },
      { name: 'expected_parallel',   type: 'list[list]', desc: 'Groups of tools that should run concurrently.' },
      { name: 'allowed_transitions', type: 'dict',       desc: 'Graph edges: node -> nodes it may move to.' },
      { name: 'max_node_visits',     type: 'int | dict', desc: 'How many times a graph node may be entered.' },
      { name: 'max_revision_rounds', type: 'int',        desc: 'Cap on critique rounds in an evaluator-optimizer loop.' },
      { name: 'metadata',            type: 'dict',       desc: 'Your own data, kept in the report and not checked.' },
    ],
  },
  metrics: {
    label: 'Scoring',
    title: 'Five deterministic metrics',
    metrics: [
      { name: 'Tool Selection F1',      weight: '25%', desc: 'Precision and recall over expected_tools: missing tools and unexpected ones both lower it. Threshold: 0.85.' },
      { name: 'Argument Correctness',   weight: '25%', desc: 'Share of expected argument values the best-matching call used. Threshold: 0.85.' },
      { name: 'Call Ordering',          weight: '20%', desc: 'Share of ordering constraints respected. A tool that ran before, or in parallel with, its prerequisite breaks one. Threshold: 1.00.' },
      { name: 'Step Efficiency',        weight: '15%', desc: 'optimal / actual tool calls, minus 0.25 per repeated identical call. Catches loops and wandering. Threshold: 0.70.' },
      { name: 'Reasoning Faithfulness', weight: '15%', desc: 'Rule-based: flags a thought or final answer claiming success right after a tool error or a denied approval. Add the LLM judge for claims rules cannot check, like a wrong amount. Threshold: 0.85.' },
    ],
  },
  patterns: {
    label: 'Agentic Patterns',
    title: 'Checks for plans, handoffs, approvals and more',
    snippet: `scenario = {
    "scenario_id": "support_refund",
    "expected_tools": ["lookup_order", "issue_refund"],
    "forbidden_tools": ["delete_customer"],                 # policy
    "requires_approval": ["issue_refund"],                  # human-in-the-loop
    "agent_tools": {"triage": ["lookup_order"],             # multi-agent
                    "billing": ["issue_refund"]},
    "expected_agents": ["triage", "billing"],
}

# A check runs when the scenario sets its fields or the trace has its events,
# and is reported only if it had something to check
report = evaluate_trace(scenario, trace)
print(report.patterns["human_approval"])
# {'label': 'Human Approval', 'passed': True, 'score': 1.0, 'violations': [], ...}`,
    lang: 'python',
    metrics: [
      { name: 'Policy rules', weight: 'forbidden_tools · max_tool_calls', desc: 'Forbidden tools and per-tool call caps. Tool selection is a score, so an agent can call every expected tool plus a dangerous one and still pass it; this makes it a hard failure.' },
      { name: 'Human approval', weight: 'requires_approval', desc: 'Guarded tools need an approval before each call. Running after a denial is always flagged, and so is telling the user a denied action happened.' },
      { name: 'Plan & execute', weight: 'require_plan · expected_plan', desc: 'A plan comes first, calls stay within the current plan, the final plan is completed in order, and a failed call is followed by a retry or a new plan.' },
      { name: 'Multi-agent handoffs', weight: 'agent_tools · expected_agents · max_handoffs', desc: 'Per-agent tool permissions, the order agents acted in, a handoff cap and loop detection. A handoff counts once its target acts.' },
      { name: 'Routing', weight: 'expected_route', desc: 'The first routing decision must match. The CLI reports routing accuracy across a scenario file.' },
      { name: 'Parallel calls', weight: 'expected_parallel', desc: 'Tools that should run concurrently must share a parallel group; a dependent call in the same group as its prerequisite is an ordering violation.' },
      { name: 'Graph workflows', weight: 'allowed_transitions · max_node_visits', desc: 'Moves must follow allowed edges, within per-node visit caps. Fan-out branches form one layer, so only real edges need listing.' },
      { name: 'Evaluator-optimizer', weight: 'max_revision_rounds', desc: 'Revisions must change after a rejection, and the loop must end on an approved draft, within the round budget.' },
    ],
  },
  recorder: {
    label: 'TraceRecorder',
    title: 'Record any agent, in any framework',
    snippet: `from regression_shield import TraceRecorder, evaluate_trace

recorder = TraceRecorder(agent="triage_agent")

@recorder.tool
def issue_refund(order_id: str, amount: float) -> dict:
    return {"status": "REFUNDED", "amount": amount}

recorder.handoff("billing_agent")
recorder.approval("issue_refund", approved=False, by="lead@example.com")
issue_refund("ORD-7731", 89.0)   # runs anyway, after a denial

report = evaluate_trace(
    scenario={
        "scenario_id": "refund_gate",
        "requires_approval": ["issue_refund"],
        "agent_tools": {"billing_agent": ["issue_refund"]},
    },
    trace=recorder,
)

print(report.passed)     # False
print(report.failures)   # ["Human Approval: Step 3: 'issue_refund' ran after its approval was denied"]`,
    lang: 'python',
    fields: [
      { name: '@recorder.tool / wrap(fn)', type: 'decorator', desc: 'Records each call: arguments, result, or error (then re-raises). Async functions work too. agent= credits calls to one agent.' },
      { name: 'tool_call(name, args, obs)', type: 'method', desc: 'Record a tool call you ran yourself.' },
      { name: 'thought(text)', type: 'method', desc: 'Reasoning attached to the next step.' },
      { name: 'plan(steps)', type: 'method', desc: 'A plan: tool names in the order the agent intends to run them.' },
      { name: 'handoff(to)', type: 'method', desc: 'Control passes to another agent; later steps belong to it.' },
      { name: 'approval(tool, approved)', type: 'method', desc: 'A person\'s approval decision for the next call to that tool.' },
      { name: 'route(to)', type: 'method', desc: "A router's decision." },
      { name: 'node(name)', type: 'method', desc: 'Entering a graph node; later steps are tagged with it.' },
      { name: 'parallel()', type: 'context', desc: 'Steps recorded inside the with-block ran concurrently.' },
      { name: 'draft / critique', type: 'method', desc: 'Evaluator-optimizer rounds.' },
      { name: 'final_answer(text)', type: 'method', desc: "The agent's answer, checked for success claims after a failure." },
    ],
  },
  langgraph: {
    label: 'LangGraph',
    title: 'Nodes, fan-out, sub-agents and approvals, automatically',
    snippet: `from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

handler = RegressionShieldCallbackHandler()
app.invoke(inputs, config={"callbacks": [handler]})   # app = graph.compile()

report = evaluate_trace({
    "scenario_id": "content_pipeline",
    "allowed_transitions": {"writer": ["reviewer"], "reviewer": ["writer", "publish"]},
    "max_node_visits": {"reviewer": 3},
}, handler)

print(report.patterns["graph"]["details"]["path"])
# ['writer', 'reviewer', 'writer', 'reviewer', 'publish']

# Also recorded with no extra code: fan-out branches as parallel groups,
# sub-agents (supervisor, swarm) and their transfer_to_* handoffs, and
# HumanInTheLoopMiddleware decisions as approvals.`,
    lang: 'python',
  },
  codeagent: {
    label: 'Code Agents',
    title: 'smolagents CodeAgent, recorded as tools run',
    snippet: `from smolagents import CodeAgent
from regression_shield import evaluate_trace, instrument_smolagents

agent = CodeAgent(tools=[run_unit_tests, deploy_production], model=model)
recorder = instrument_smolagents(agent)   # before the run
agent.run("Deploy to staging")

# Calls made from the agent's generated Python code are recorded with
# their arguments and results; each step's reasoning becomes the thought.
report = evaluate_trace(scenario, recorder)`,
    lang: 'python',
  },
  logging: {
    label: 'Logging',
    title: 'See every check with --verbose',
    snippet: `# CLI: every metric, pattern check and judge call, on stderr
regshield eval scenarios.json --verbose

# Python
report = evaluate_trace(scenario, trace, verbose=True)

# Or without code changes
REGSHIELD_LOG=debug python run_evals.py

[regshield] DEBUG   evaluator: Evaluating 'deploy_gate': 2 steps, 2 tool calls
[regshield] DEBUG   patterns:   pattern policy          PASSED (1.00)
[regshield] INFO    evaluator: 'deploy_gate' PASSED (composite 1.00) in 0.4 ms`,
    lang: 'bash',
    fields: [
      { name: '--verbose / -v', type: 'CLI flag', desc: 'Debug logs for that command. Works on eval, demo and serve.' },
      { name: 'verbose=True', type: 'evaluate_trace', desc: 'Debug logs on stderr from then on.' },
      { name: 'enable_logging(level)', type: 'function', desc: 'Turn on logs at a chosen level (DEBUG, INFO, WARNING).' },
      { name: 'REGSHIELD_LOG', type: 'env var', desc: 'debug, info or warning. Turns logs on without changing code.' },
    ],
  },
  langchain: {
    label: 'LangChain',
    title: 'One callback handler, no changes to the agent',
    snippet: `from langchain.agents import create_agent
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

agent = create_agent(model, tools=[lookup_customer, validate_policy, execute_refund])
handler = RegressionShieldCallbackHandler()
agent.invoke({"messages": [{"role": "user", "content": "Refund customer 99401"}]},
             config={"callbacks": [handler]})

# Tool calls, errors, reasoning, parallel calls and the final answer are recorded
report = evaluate_trace(
    scenario={
        "scenario_id": "refund_gate",
        "expected_order": ["lookup_customer", "validate_policy", "execute_refund"],
        "max_tool_calls": {"execute_refund": 1},
    },
    trace=handler,
)
print(report.format())`,
    lang: 'python',
  },
  smolagents: {
    label: 'smolagents',
    title: 'Hugging Face agents in two lines',
    snippet: `from smolagents import ToolCallingAgent
from regression_shield import evaluate_trace, instrument_smolagents

agent = ToolCallingAgent(tools=[...], model=model, managed_agents=[research_agent])
recorder = instrument_smolagents(agent)   # before the run
agent.run(task)

# Tool calls, parallel calls, the answer, and managed agents as handoffs
report = evaluate_trace(
    scenario={
        "scenario_id": "research_gate",
        "agent_tools": {"research_agent": ["web_search"]},
    },
    trace=recorder,
)
print(report.passed)

# Didn't instrument before the run? Rebuild the trace from memory:
# from regression_shield import extract_smolagents_trace
# report = evaluate_trace(scenario, extract_smolagents_trace(agent))`,
    lang: 'python',
  },
  decorator: {
    label: '@shield',
    title: 'Evaluate every run of a function',
    snippet: `from regression_shield import RegressionShieldCallbackHandler, shield

handler = RegressionShieldCallbackHandler()

@shield(
    scenario={
        "scenario_id": "pipeline_gate",
        "expected_order": ["run_unit_tests", "deploy_production"],
    },
    get_trace=handler.get_trace,   # omit if the function returns the trace itself
    raise_on_failure=True,         # raises EvaluationFailed when the evaluation fails
)
def run_pipeline(task: str):
    return agent.invoke({"messages": [{"role": "user", "content": task}]},
                        config={"callbacks": [handler]})

# The decorated function returns (output, report)
output, report = run_pipeline("Deploy v1.0.0")`,
    lang: 'python',
  },
  cicd: {
    label: 'CI/CD Gate',
    title: 'Block pull requests automatically',
    snippet: `# .github/workflows/agent-gate.yml
name: Agent quality gate
on: [pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install regression-shield
      # Exit 0: all passed. Exit 1: a scenario failed, or a known-bad
      # regression_trace passed. Exit 2: bad input.
      - run: regshield eval scenarios.json`,
    lang: 'yaml',
  },
  rest: {
    label: 'REST API',
    title: 'Evaluate from any language',
    snippet: `# Start the local server (listens on 127.0.0.1 only)
regshield serve

# POST a scenario and a trace; the response is the report
curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "scenario": {
      "scenario_id": "auth_gate",
      "expected_order": ["verify_auth", "fetch_data"]
    },
    "trace": [
      {"thought": "Verifying auth first.",
       "action": {"name": "verify_auth", "args": {"uid": "usr_992"}},
       "observation": "AUTHORIZED"},
      {"thought": "Auth confirmed. Fetching user data.",
       "action": {"name": "fetch_data", "args": {"uid": "usr_992"}},
       "observation": "Data returned."}
    ]
  }'`,
    lang: 'bash',
  },
};

export default function DocsPage() {
  const [active, setActive] = useState('quickstart');
  const [copied, setCopied] = useState(false);

  const sec = CONTENT[active];

  function copyCode() {
    const text = sec.snippet || sec.code || '';
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', minHeight: '100vh' }}>
        {/* Sidebar */}
        <aside style={{
          position: 'sticky',
          top: 56,
          height: 'calc(100vh - 56px)',
          borderRight: '1px solid var(--border)',
          background: 'var(--surface)',
          padding: '32px 0',
          overflowY: 'auto',
        }}>
          <div style={{ padding: '0 20px', marginBottom: 24 }}>
            <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text3)', fontSize: 13, textDecoration: 'none', marginBottom: 20, fontWeight: 500 }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5M12 5l-7 7 7 7"/>
              </svg>
              Back to product
            </a>
            <span className="label">Documentation</span>
          </div>

          <nav style={{ display: 'flex', flexDirection: 'column' }}>
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '9px 20px',
                  fontSize: 13,
                  fontFamily: 'var(--font)',
                  fontWeight: active === s.id ? 600 : 400,
                  color: active === s.id ? 'var(--text)' : 'var(--text3)',
                  background: active === s.id ? 'var(--surface2)' : 'transparent',
                  borderLeft: active === s.id ? '2px solid var(--text)' : '2px solid transparent',
                  borderRight: 'none',
                  borderTop: 'none',
                  borderBottom: 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <article style={{ padding: '56px 64px 120px', maxWidth: 840 }}>
          <div className="label" style={{ marginBottom: 12 }}>{sec.label}</div>
          <h1 className="h2" style={{ marginBottom: 32 }}>{sec.title}</h1>

          {/* Install command for quickstart */}
          {sec.code && (
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 16px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              boxShadow: 'var(--shadow-xs)',
              marginBottom: 32,
            }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text3)' }}>$</span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)', fontWeight: 500 }}>{sec.code}</span>
            </div>
          )}

          {/* Snippet */}
          {sec.snippet && (
            <div className="code-block" style={{ marginBottom: 40 }}>
              <div className="code-bar">
                <span>{sec.lang}</span>
                <button
                  onClick={copyCode}
                  style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                    padding: '3px 10px',
                    fontFamily: 'var(--mono)',
                    fontSize: 11,
                    color: 'var(--text2)',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  {copied ? 'copied' : 'copy'}
                </button>
              </div>
              <div className="code-body">
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  <code>{sec.snippet}</code>
                </pre>
              </div>
            </div>
          )}

          {/* Policy fields table */}
          {sec.fields && (
            <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--surface)', boxShadow: 'var(--shadow-xs)' }}>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1.4fr 0.7fr 2fr',
                padding: '12px 20px',
                background: '#f8fafc',
                borderBottom: '1px solid var(--border)',
              }}>
                {['Field', 'Type', 'Description'].map((h) => (
                  <span key={h} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>{h}</span>
                ))}
              </div>
              {sec.fields.map(({ name, type, desc }, i) => (
                <div
                  key={name}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1.4fr 0.7fr 2fr',
                    padding: '13px 20px',
                    borderBottom: i < sec.fields.length - 1 ? '1px solid var(--border)' : 'none',
                    background: i % 2 === 0 ? 'var(--surface)' : 'var(--bg)',
                    alignItems: 'start',
                  }}
                >
                  <code style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>{name}</code>
                  <code style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)' }}>{type}</code>
                  <span className="body-sm">{desc}</span>
                </div>
              ))}
            </div>
          )}

          {/* Metrics list */}
          {sec.metrics && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {sec.metrics.map(({ name, weight, desc }) => (
                <div key={name} className="card" style={{ padding: '20px 24px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <h3 className="h3" style={{ fontSize: 15 }}>{name}</h3>
                    <span className="tag">{weight}</span>
                  </div>
                  <p className="body-sm">{desc}</p>
                </div>
              ))}
            </div>
          )}
        </article>
      </div>
  );
}
