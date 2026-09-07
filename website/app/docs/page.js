'use client';

import { useState } from 'react';

const SECTIONS = [
  { id: 'quickstart',   label: 'Quickstart' },
  { id: 'scenario',     label: 'Scenario Spec' },
  { id: 'metrics',      label: 'Metrics' },
  { id: 'langchain',    label: 'LangChain' },
  { id: 'smolagents',   label: 'smolagents' },
  { id: 'decorator',    label: '@shield' },
  { id: 'cicd',         label: 'CI/CD Gate' },
  { id: 'rest',         label: 'REST API' },
];

const CONTENT = {
  quickstart: {
    label: 'Getting Started',
    title: 'Install and evaluate in 2 minutes',
    code: `pip install regression-shield`,
    snippet: `from regression_shield import evaluate_trace

trace = [
    {
        "thought": "I will run security audit first.",
        "action": {"type": "tool_call", "name": "security_scan", "args": {"target": "repo"}},
        "observation": "Vulnerabilities: 0"
    },
    {
        "thought": "Clean. Proceeding to publish release.",
        "action": {"type": "tool_call", "name": "publish_release", "args": {"tag": "v1.0.0"}},
        "observation": "Published"
    }
]

result = evaluate_trace(
    scenario={
        "scenario_id": "release_gate",
        "expected_tools":    ["security_scan", "publish_release"],
        "expected_order":    ["security_scan", "publish_release"],
        "optimal_step_count": 2,
    },
    trace=trace
)

result.print_diagnostics()     # per-metric breakdown
print(result.passed)           # True
print(result.composite_score)  # 1.00`,
    lang: 'python',
  },
  scenario: {
    label: 'Scenario Spec',
    title: 'Describe what the agent should do',
    snippet: `# Pass as a Python dict or load from JSON/YAML
scenario = {
    "scenario_id":       "deploy_gate",          # unique identifier
    "title":            "Cloud Deploy Pipeline",  # human-readable label
    "domain":           "DevOps",                 # grouping tag
    "expected_tools":   ["run_unit_tests", "deploy_production"],  # required tools
    "expected_order":   ["run_unit_tests", "deploy_production"],  # prerequisite order
    "expected_arguments": {
        "deploy_production": {"env": "staging"}   # optional arg schema check
    },
    "optimal_step_count": 2,                      # ideal trace length for efficiency scoring
}

result = evaluate_trace(scenario=scenario, trace=agent_trace)`,
    lang: 'python',
    fields: [
      { name: 'scenario_id',         type: 'str',       desc: 'Unique identifier for this evaluation gate. Used in reports and dashboards.' },
      { name: 'expected_tools',      type: 'list[str]', desc: 'Tools that must appear in the trace. Missing any drops Tool Selection F1 below threshold.' },
      { name: 'expected_order',      type: 'list[str]', desc: 'Enforces prerequisite ordering. Any inversion zeroes the Call Ordering score.' },
      { name: 'expected_arguments',  type: 'dict',      desc: 'Optional per-tool argument schema. Mismatches reduce Argument Correctness score.' },
      { name: 'optimal_step_count',  type: 'int',       desc: 'Target trace length. Excess steps (including redundant/looping calls) penalise Step Efficiency.' },
    ],
  },
  metrics: {
    label: 'Scoring',
    title: 'Four deterministic dimensions',
    metrics: [
      { name: 'Tool Selection F1',     weight: '30%', desc: 'Precision and recall over expected_tools. Missing a required tool or calling unexpected tools lowers this score. Threshold: 0.85.' },
      { name: 'Call Ordering',         weight: '30%', desc: 'Strict enforcement of expected_order prerequisites. Any inversion (e.g. deploy before test) zeros this score. Threshold: 1.00.' },
      { name: 'Step Efficiency',       weight: '25%', desc: 'Ratio of optimal_step_count to actual steps taken. Repeated identical calls (loop thrashing) are counted as redundant and penalised. Threshold: 0.70.' },
      { name: 'Reasoning Faithfulness', weight: '15%', desc: 'Verifies each thought is grounded in the preceding observation. Contradictions or fabricated state are flagged as hallucination. Threshold: 0.85.' },
    ],
  },
  langchain: {
    label: 'LangChain',
    title: 'Zero-config callback handler',
    snippet: `from regression_shield.adapters.langchain import RegressionShieldCallbackHandler
from regression_shield import evaluate_trace

# 1. Attach the callback — no changes to your agent code
handler = RegressionShieldCallbackHandler()

agent_executor.invoke(
    {"input": "Cancel renewal for customer 99401"},
    config={"callbacks": [handler]}
)

# 2. Evaluate the captured trace
result = evaluate_trace(
    scenario={
        "scenario_id": "refund_gate",
        "expected_tools": ["lookup_customer", "validate_policy", "execute_refund"],
        "expected_order": ["lookup_customer", "validate_policy", "execute_refund"],
        "optimal_step_count": 3,
    },
    trace=handler.get_trace()   # list of StepTrace dicts
)

print(result.composite_score)  # e.g. 0.96
print(result.passed)           # True`,
    lang: 'python',
  },
  smolagents: {
    label: 'smolagents',
    title: 'Hugging Face agents in two lines',
    snippet: `from smolagents import CodeAgent, HfApiModel
from regression_shield.adapters.smolagents import extract_smolagents_trace
from regression_shield import evaluate_trace

agent = CodeAgent(tools=[...], model=HfApiModel())
agent.run(task)

# Normalise agent.logs into standard StepTrace format
trace = extract_smolagents_trace(agent)

result = evaluate_trace(
    scenario={
        "scenario_id": "smol_gate",
        "expected_tools":    ["run_tests"],
        "expected_order":    ["run_tests"],
        "optimal_step_count": 1,
    },
    trace=trace
)

print(result.passed)
result.print_diagnostics()`,
    lang: 'python',
  },
  decorator: {
    label: '@shield',
    title: 'Decorator — zero boilerplate',
    snippet: `from regression_shield import shield

@shield(
    scenario={
        "scenario_id":    "pipeline_gate",
        "expected_tools": ["run_unit_tests", "deploy_production"],
        "expected_order": ["run_unit_tests", "deploy_production"],
        "optimal_step_count": 2,
    },
    on_violation="raise"   # or "warn" / "log"
)
def run_pipeline(task: str):
    return my_agent.execute(task)`,
    lang: 'python',
  },
  cicd: {
    label: 'CI/CD Gate',
    title: 'Block PRs automatically',
    snippet: `# .github/workflows/agent_gate.yml
name: Agent Quality Gate
on: [pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install regression-shield

      - name: Run agent evals
        run: python run_evals.py --output candidate_trace.json

      - name: Enforce quality gate
        run: |
          regshield check \\
            --trace    ./candidate_trace.json \\
            --scenario ./scenario.json        \\
            --baseline ./baselines/approved.json \\
            --fail-on-regression
          # Exit 0 = PASSED  |  Exit 1 = REGRESSION BLOCKED`,
    lang: 'yaml',
  },
  rest: {
    label: 'REST API',
    title: 'Language-agnostic ingestion',
    snippet: `# Start the local server (air-gapped, no cloud required)
regshield serve --port 8000

# Evaluate from any language — send scenario + trace in one payload
curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "scenario_id":        "auth_gate",
    "expected_tools":     ["verify_auth", "fetch_data"],
    "expected_order":     ["verify_auth", "fetch_data"],
    "optimal_step_count": 2,
    "trace": [
      {
        "thought":     "Verifying auth before proceeding.",
        "action":      {"type": "tool_call", "name": "verify_auth", "args": {"uid": "usr_992"}},
        "observation": "AUTHORIZED"
      },
      {
        "thought":     "Auth confirmed. Fetching user data.",
        "action":      {"type": "tool_call", "name": "fetch_data", "args": {"uid": "usr_992"}},
        "observation": "Data returned."
      }
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
    <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', minHeight: '100vh' }}>
      {/* Sidebar */}
      <aside style={{
        position: 'sticky',
        top: 56,
        height: 'calc(100vh - 56px)',
        borderRight: '1px solid #1a1a1a',
        padding: '32px 0',
        overflowY: 'auto',
      }}>
        <div style={{ padding: '0 20px', marginBottom: 24 }}>
          <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#555', fontSize: 13, marginBottom: 24 }}>
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
                fontFamily: active === s.id ? 'var(--font)' : 'var(--font)',
                fontWeight: active === s.id ? 500 : 400,
                color: active === s.id ? '#f5f5f5' : '#555',
                background: active === s.id ? '#141414' : 'transparent',
                borderLeft: active === s.id ? '1px solid #2a2a2a' : '1px solid transparent',
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
      <article style={{ padding: '56px 64px 120px', maxWidth: 760 }}>
        <div className="label" style={{ marginBottom: 12 }}>{sec.label}</div>
        <h1 className="h2" style={{ marginBottom: 32 }}>{sec.title}</h1>

        {/* Install command for quickstart */}
        {sec.code && (
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 16px',
            background: '#000',
            border: '1px solid #1f1f1f',
            borderRadius: 8,
            marginBottom: 32,
          }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: '#888' }}>$</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{sec.code}</span>
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
                  background: 'none',
                  border: '1px solid #2a2a2a',
                  borderRadius: 4,
                  padding: '3px 10px',
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  color: '#555',
                  cursor: 'pointer',
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
          <div style={{ border: '1px solid #1a1a1a', borderRadius: 10, overflow: 'hidden' }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1.4fr 0.7fr 2fr',
              padding: '12px 20px',
              background: '#0d0d0d',
              borderBottom: '1px solid #1a1a1a',
            }}>
              {['Field', 'Type', 'Description'].map((h) => (
                <span key={h} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#444', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</span>
              ))}
            </div>
            {sec.fields.map(({ name, type, desc }, i) => (
              <div
                key={name}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1.4fr 0.7fr 2fr',
                  padding: '13px 20px',
                  borderBottom: i < sec.fields.length - 1 ? '1px solid #0f0f0f' : 'none',
                  alignItems: 'start',
                }}
              >
                <code style={{ fontFamily: 'var(--mono)', fontSize: 12, color: '#79c0ff' }}>{name}</code>
                <code style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#555' }}>{type}</code>
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
