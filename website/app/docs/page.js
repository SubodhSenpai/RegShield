'use client';

import { useState } from 'react';

const SECTIONS = [
  { id: 'quickstart',   label: 'Quickstart' },
  { id: 'policy',       label: 'Policy Schema' },
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
        "tool": "security_scan",
        "tool_input": {"target": "repo"},
        "observation": "Vulnerabilities: 0"
    },
    {
        "thought": "Clean. Proceeding to publish release.",
        "tool": "publish_release",
        "tool_input": {"tag": "v1.0.0"},
        "observation": "Published"
    }
]

result = evaluate_trace(
    trace,
    policy={"required_tools": ["security_scan"], "max_tool_calls": 4}
)

print(result.passed)           # True
print(result.composite_score)  # 0.94`,
    lang: 'python',
  },
  policy: {
    label: 'Policy-as-Code',
    title: 'Declare rules in YAML or Python',
    snippet: `# policy.yaml
required_tools:
  - run_unit_tests
  - verify_security_credentials

forbidden_tools:
  - force_push_to_main

forbidden_tool_pairs:
  - [read_user_secrets, send_external_webhook]

max_tool_calls: 6
min_thought_length: 20
allow_duplicate_tool_calls: false`,
    lang: 'yaml',
    fields: [
      { name: 'required_tools',          type: 'list[str]', desc: 'Tools that must be called at least once. Missing any drops policy score to 0.' },
      { name: 'forbidden_tools',         type: 'list[str]', desc: 'Blacklisted tools. Any call triggers an immediate rejection.' },
      { name: 'forbidden_tool_pairs',    type: 'list[list]', desc: 'Sequence constraints that disallow pairing tool A with tool B.' },
      { name: 'max_tool_calls',          type: 'int',       desc: 'Budget ceiling. Exceeding it applies heavy efficiency penalties.' },
      { name: 'allow_duplicate_tool_calls', type: 'bool',   desc: 'When false, repeated identical calls are flagged as loop thrashing.' },
    ],
  },
  metrics: {
    label: 'Scoring',
    title: 'Four deterministic dimensions',
    metrics: [
      { name: 'Policy Compliance', weight: '40%', desc: 'Strict adherence to required, forbidden, and sequenced tool rules. Any security violation zeros this score.' },
      { name: 'Loop Penalty',      weight: '20%', desc: 'Negative score applied when identical tool calls repeat without state change.' },
      { name: 'Goal Attainment',   weight: '25%', desc: 'Verifies the agent reached a terminal success state with verified artifacts.' },
      { name: 'ReAct Efficiency',  weight: '15%', desc: 'Ratio of purposeful tool calls to total budget. Penalises erratic step generation.' },
    ],
  },
  langchain: {
    label: 'LangChain',
    title: 'Zero-config callback handler',
    snippet: `from regression_shield.adapters.langchain import RegressionShieldTracer

tracer = RegressionShieldTracer(
    policy={
        "required_tools": ["lookup_customer", "validate_policy"],
        "max_tool_calls": 6
    }
)

# Attach to any AgentExecutor or LangGraph workflow
agent_executor.invoke(
    {"input": "Cancel renewal for customer 99401"},
    config={"callbacks": [tracer]}
)

result = tracer.get_evaluation()
print(result.composite_score)   # 0.96
print(result.passed)            # True`,
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

trace  = extract_smolagents_trace(agent)
result = evaluate_trace(trace, policy={"required_tools": ["run_tests"]})

print(result.passed)`,
    lang: 'python',
  },
  decorator: {
    label: '@shield',
    title: 'Decorator — zero boilerplate',
    snippet: `from regression_shield import shield

@shield(
    policy={
        "forbidden_tool_pairs": [["access_credentials", "send_external_webhook"]],
        "max_tool_calls": 5
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
            --baseline ./baselines/approved.json \\
            --policy   ./policy.yaml \\
            --fail-on-regression`,
    lang: 'yaml',
  },
  rest: {
    label: 'REST API',
    title: 'Language-agnostic ingestion',
    snippet: `# Start the local server (air-gapped, no cloud required)
regshield serve --port 8000

# Evaluate from any language
curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "trace": [
      {
        "thought": "Verifying auth before proceeding.",
        "tool": "verify_auth",
        "tool_input": {"uid": "usr_992"},
        "observation": "AUTHORIZED"
      }
    ],
    "policy": {
      "required_tools": ["verify_auth"],
      "max_tool_calls": 3
    }
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
