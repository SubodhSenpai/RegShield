'use client';

import { useState } from 'react';

// ── Trace scenarios ─────────────────────────────────────────────────────────────

const SCENARIOS = [
  {
    id: 'deploy',
    label: 'Cloud Deploy',
    pass: {
      score: 0.96,
      metrics: { policy: 1.0, goal: 1.0, loop: 0.0, efficiency: 0.92 },
      verdict: 'PASS',
      steps: [
        { tool: 'run_unit_tests', ok: true },
        { tool: 'run_security_scan', ok: true },
        { tool: 'deploy_production', ok: true },
      ],
    },
    fail: {
      score: 0.28,
      metrics: { policy: 0.0, goal: 0.5, loop: 0.0, efficiency: 0.45 },
      verdict: 'FAIL',
      violation: 'Prerequisite inversion — deploy called before tests',
      steps: [
        { tool: 'deploy_production', ok: false },
        { tool: 'run_unit_tests', ok: true },
      ],
    },
  },
  {
    id: 'refund',
    label: 'Finance Refund',
    pass: {
      score: 0.94,
      metrics: { policy: 1.0, goal: 1.0, loop: 0.0, efficiency: 0.88 },
      verdict: 'PASS',
      steps: [
        { tool: 'verify_user_kyc', ok: true },
        { tool: 'check_dispute_history', ok: true },
        { tool: 'execute_refund', ok: true },
      ],
    },
    fail: {
      score: 0.15,
      metrics: { policy: 0.0, goal: 0.2, loop: 0.0, efficiency: 0.30 },
      verdict: 'FAIL',
      violation: 'KYC skipped — forbidden tool pair triggered',
      steps: [
        { tool: 'execute_refund', ok: false },
        { tool: 'send_external_webhook', ok: false },
      ],
    },
  },
  {
    id: 'db',
    label: 'DB Migration',
    pass: {
      score: 0.98,
      metrics: { policy: 1.0, goal: 1.0, loop: 0.0, efficiency: 0.95 },
      verdict: 'PASS',
      steps: [
        { tool: 'inspect_active_locks', ok: true },
        { tool: 'apply_ddl_migration', ok: true },
      ],
    },
    fail: {
      score: 0.32,
      metrics: { policy: 0.5, goal: 0.3, loop: -0.5, efficiency: 0.22 },
      verdict: 'FAIL',
      violation: 'Cyclic loop — inspect_active_locks called 3x with identical args',
      steps: [
        { tool: 'inspect_active_locks (1/3)', ok: false },
        { tool: 'inspect_active_locks (2/3)', ok: false },
        { tool: 'inspect_active_locks (3/3)', ok: false },
        { tool: 'apply_ddl_migration', ok: false },
      ],
    },
  },
];

// ── Integration snippets ─────────────────────────────────────────────────────────

const SNIPPETS = {
  sdk: {
    label: 'Python SDK',
    lang: 'python',
    code: `from regression_shield import evaluate_trace

result = evaluate_trace(
    trace,                          # list of reasoning steps
    policy={
        "required_tools": ["run_tests"],
        "max_tool_calls": 5
    }
)

if not result.passed:
    raise SystemExit(1)            # block the CI pipeline`,
  },
  langchain: {
    label: 'LangChain',
    lang: 'python',
    code: `from regression_shield.adapters.langchain import RegressionShieldTracer

tracer = RegressionShieldTracer(
    policy={"required_tools": ["verify_permissions"]}
)

agent_executor.invoke(
    {"input": task},
    config={"callbacks": [tracer]}
)

result = tracer.get_evaluation()
print(result.composite_score)`,
  },
  smolagents: {
    label: 'smolagents',
    lang: 'python',
    code: `from regression_shield.adapters.smolagents import extract_smolagents_trace
from regression_shield import evaluate_trace

agent = CodeAgent(tools=[...], model=HfApiModel())
agent.run(task)

trace  = extract_smolagents_trace(agent)
result = evaluate_trace(trace, policy={...})`,
  },
  cli: {
    label: 'CLI',
    lang: 'bash',
    code: `# Block PRs when agent reasoning degrades
regshield check \\
  --trace     ./candidate_trace.json \\
  --baseline  ./baseline_trace.json  \\
  --policy    ./policy.yaml          \\
  --fail-on-regression`,
  },
  rest: {
    label: 'REST API',
    lang: 'bash',
    code: `curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "trace":  [...],
    "policy": { "required_tools": ["verify_auth"] }
  }'`,
  },
};

// ── Compare table data ──────────────────────────────────────────────────────────

const COMPARE = [
  { feature: 'Deterministic policy engine', rs: true, ls: false, bt: false, de: false },
  { feature: 'Prerequisite order checking', rs: true, ls: false, bt: false, de: false },
  { feature: 'Loop thrashing detection',   rs: true, ls: false, bt: false, de: false },
  { feature: 'Air-gapped / zero cloud',    rs: true, ls: false, bt: false, de: false },
  { feature: 'CI/CD gate < 0.5s',         rs: true, ls: false, bt: false, de: false },
  { feature: 'LangChain & smolagents',     rs: true, ls: true,  bt: false, de: true  },
  { feature: 'LLM-as-a-Judge (optional)',  rs: true, ls: true,  bt: true,  de: true  },
];

// ── Sub-components ──────────────────────────────────────────────────────────────

function Check({ ok }) {
  return ok
    ? <span style={{ color: '#22c55e', fontSize: 15 }}>+</span>
    : <span style={{ color: '#333', fontSize: 15 }}>-</span>;
}

function ScoreBar({ label, value, color }) {
  const pct = Math.abs(value) * 100;
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-num" style={{ color }}>{value.toFixed(2)}</span>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────────

export default function Page() {
  const [activeScenario, setActiveScenario] = useState(0);
  const [traceMode, setTraceMode]   = useState('fail');   // 'pass' | 'fail'
  const [activeSnippet, setActiveSnippet] = useState('sdk');
  const [copied, setCopied] = useState(false);

  const scenario = SCENARIOS[activeScenario];
  const run      = scenario[traceMode];

  const isPass   = run.verdict === 'PASS';

  function copySnippet() {
    navigator.clipboard.writeText(SNIPPETS[activeSnippet].code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <>
      {/* ── Hero ── */}
      <section style={{ padding: '120px 0 100px', textAlign: 'center', position: 'relative' }}>
        {/* Subtle radial glow */}
        <div style={{
          position: 'absolute', inset: 0, zIndex: 0,
          background: 'radial-gradient(ellipse 70% 45% at 50% 0%, rgba(30,30,30,0.5) 0%, transparent 70%)',
          pointerEvents: 'none',
        }} />

        <div className="wrap" style={{ position: 'relative', zIndex: 1 }}>
          <div className="tag tag-blue" style={{ marginBottom: 24 }}>
            Agent Evaluation SDK
          </div>

          <h1 className="h1" style={{ maxWidth: 780, margin: '0 auto 24px', lineHeight: 1.08 }}>
            Quality gates for<br />autonomous AI agents
          </h1>

          <p className="body" style={{ maxWidth: 520, margin: '0 auto 44px' }}>
            Catch silent reasoning failures — prerequisite inversions, loop thrashing, and policy evasion — before they reach production.
          </p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
            <a href="#integrate" className="btn btn-white">
              Install SDK
            </a>
            <a href="#how-it-works" className="btn btn-ghost">
              See how it works
            </a>
          </div>

          {/* Install pill */}
          <div style={{
            marginTop: 48,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 16px',
            background: '#000',
            border: '1px solid #1f1f1f',
            borderRadius: 8,
          }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: '#888' }}>$</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>pip install regression-shield</span>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Stat Row ── */}
      <section style={{ padding: '56px 0' }}>
        <div className="wrap">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, border: '1px solid #1a1a1a', borderRadius: 12, overflow: 'hidden' }}>
            {[
              { num: '100%',  sub: 'Deterministic policy checks' },
              { num: '< 0.5s', sub: 'Local CI gate latency' },
              { num: '6',     sub: 'Framework adapters' },
              { num: '$0',    sub: 'Per-check inference cost' },
            ].map(({ num, sub }, i) => (
              <div key={i} style={{
                padding: '36px 28px',
                background: '#0d0d0d',
                borderRight: i < 3 ? '1px solid #1a1a1a' : 'none',
                textAlign: 'center',
              }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em', marginBottom: 6 }}>
                  {num}
                </div>
                <div className="body-sm">{sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── How it works ── */}
      <section id="how-it-works" style={{ padding: '100px 0' }}>
        <div className="wrap">
          <div style={{ marginBottom: 64 }}>
            <div className="label" style={{ marginBottom: 16 }}>How it works</div>
            <h2 className="h2" style={{ maxWidth: 520, marginBottom: 16 }}>
              Four silent failure modes. One gate.
            </h2>
            <p className="body" style={{ maxWidth: 520 }}>
              Standard LLM evals check text quality. Agents fail differently — through multi-step reasoning errors that produce plausible-looking outputs.
            </p>
          </div>

          <div className="grid-2">
            {[
              {
                code: '01',
                title: 'Prerequisite Inversion',
                desc: 'Agent calls deploy_production before run_unit_tests. Irreversible action fires before safety gates.'
              },
              {
                code: '02',
                title: 'Loop Thrashing',
                desc: 'Faced with an error, the agent repeats the same query with identical arguments — consuming budget without progress.'
              },
              {
                code: '03',
                title: 'Hallucinated State',
                desc: 'Tool returns RecordNotFound. Agent reasons "record retrieved successfully" and continues on fabricated state.'
              },
              {
                code: '04',
                title: 'Policy Evasion',
                desc: 'Agent pairs read_credentials with send_webhook, transmitting secrets outside the secure enclave.'
              },
            ].map(({ code, title, desc }) => (
              <div key={code} className="card" style={{ padding: '28px 28px 32px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
                  <span className="label" style={{ color: '#333' }}>{code}</span>
                  <span className="tag tag-fail" style={{ fontSize: 10 }}>SILENT</span>
                </div>
                <h3 className="h3" style={{ marginBottom: 10 }}>{title}</h3>
                <p className="body-sm">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Interactive Trace Inspector ── */}
      <section style={{ padding: '100px 0', background: '#080808' }}>
        <div className="wrap">
          <div style={{ marginBottom: 48 }}>
            <div className="label" style={{ marginBottom: 16 }}>Trace Inspector</div>
            <h2 className="h2" style={{ maxWidth: 460, marginBottom: 16 }}>
              See the gate in action
            </h2>
            <p className="body" style={{ maxWidth: 460 }}>
              Toggle between a passing and failing trace. RegressionShield evaluates each step deterministically — no LLM required.
            </p>
          </div>

          {/* Scenario tabs */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 28, flexWrap: 'wrap' }}>
            {SCENARIOS.map((s, i) => (
              <button
                key={s.id}
                onClick={() => { setActiveScenario(i); setTraceMode('fail'); }}
                className="btn btn-ghost"
                style={{
                  padding: '6px 14px',
                  fontSize: 12,
                  fontFamily: 'var(--mono)',
                  background: activeScenario === i ? '#1a1a1a' : 'transparent',
                  color: activeScenario === i ? '#f5f5f5' : '#555',
                  borderColor: activeScenario === i ? '#2a2a2a' : '#1a1a1a',
                }}
              >
                {s.label}
              </button>
            ))}

            {/* Mode toggle — pushed right */}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              <button
                onClick={() => setTraceMode('pass')}
                style={{
                  padding: '6px 14px',
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  border: '1px solid ' + (traceMode === 'pass' ? 'rgba(34,197,94,0.3)' : '#1a1a1a'),
                  borderRadius: 6,
                  background: traceMode === 'pass' ? 'rgba(34,197,94,0.06)' : 'transparent',
                  color: traceMode === 'pass' ? '#22c55e' : '#555',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                Baseline [PASS]
              </button>
              <button
                onClick={() => setTraceMode('fail')}
                style={{
                  padding: '6px 14px',
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  border: '1px solid ' + (traceMode === 'fail' ? 'rgba(239,68,68,0.3)' : '#1a1a1a'),
                  borderRadius: 6,
                  background: traceMode === 'fail' ? 'rgba(239,68,68,0.06)' : 'transparent',
                  color: traceMode === 'fail' ? '#ef4444' : '#555',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                Candidate [FAIL]
              </button>
            </div>
          </div>

          {/* Inspector grid */}
          <div className="grid-2" style={{ alignItems: 'start' }}>
            {/* Left — trace steps */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{
                padding: '14px 20px',
                borderBottom: '1px solid #1a1a1a',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  Execution Trace — {run.steps.length} steps
                </span>
                <span className={isPass ? 'tag tag-pass' : 'tag tag-fail'}>
                  {run.verdict}
                </span>
              </div>

              <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {run.steps.map((step, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '12px 14px',
                      background: '#0d0d0d',
                      border: '1px solid ' + (step.ok ? '#1a1a1a' : 'rgba(239,68,68,0.2)'),
                      borderRadius: 8,
                    }}
                  >
                    <span style={{
                      fontFamily: 'var(--mono)',
                      fontSize: 10,
                      color: '#333',
                      minWidth: 20,
                    }}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <code style={{ fontFamily: 'var(--mono)', fontSize: 13, color: step.ok ? '#79c0ff' : '#ef4444', flex: 1 }}>
                      {step.tool}()
                    </code>
                    <span style={{ fontSize: 13, color: step.ok ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {step.ok ? '+' : 'x'}
                    </span>
                  </div>
                ))}

                {!isPass && run.violation && (
                  <div style={{
                    marginTop: 6,
                    padding: '12px 14px',
                    background: 'rgba(239,68,68,0.05)',
                    border: '1px solid rgba(239,68,68,0.2)',
                    borderRadius: 8,
                  }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#ef4444' }}>
                      [VIOLATION] {run.violation}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Right — scores */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{
                padding: '14px 20px',
                borderBottom: '1px solid #1a1a1a',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  Quality Gate Audit
                </span>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: isPass ? '#22c55e' : '#ef4444' }}>
                  {isPass ? '[MERGE ALLOWED]' : '[PR BLOCKED]'}
                </span>
              </div>

              <div style={{ padding: 20 }}>
                {/* Big score */}
                <div style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 10,
                  marginBottom: 28,
                  paddingBottom: 24,
                  borderBottom: '1px solid #1a1a1a',
                }}>
                  <span style={{
                    fontFamily: 'var(--mono)',
                    fontSize: 52,
                    fontWeight: 700,
                    letterSpacing: '-0.04em',
                    color: isPass ? '#22c55e' : '#ef4444',
                    lineHeight: 1,
                  }}>
                    {run.score.toFixed(2)}
                  </span>
                  <div>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#555', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                      Composite Score
                    </div>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: '#333', marginTop: 3 }}>
                      Threshold: 0.75
                    </div>
                  </div>
                </div>

                {/* Metric bars */}
                <div className="score-bar-wrap">
                  <ScoreBar label="Policy Compliance" value={run.metrics.policy}    color={run.metrics.policy === 1 ? '#22c55e' : '#ef4444'} />
                  <ScoreBar label="Goal Attainment"   value={run.metrics.goal}      color={run.metrics.goal > 0.7 ? '#22c55e' : '#f59e0b'} />
                  <ScoreBar label="Loop Penalty"      value={run.metrics.loop}      color={run.metrics.loop === 0 ? '#22c55e' : '#ef4444'} />
                  <ScoreBar label="ReAct Efficiency"  value={run.metrics.efficiency} color={run.metrics.efficiency > 0.7 ? '#22c55e' : '#f59e0b'} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Compare ── */}
      <section id="compare" style={{ padding: '100px 0' }}>
        <div className="wrap">
          <div style={{ marginBottom: 64 }}>
            <div className="label" style={{ marginBottom: 16 }}>Comparison</div>
            <h2 className="h2" style={{ maxWidth: 480 }}>
              Built for agents, not chatbots
            </h2>
          </div>

          <div style={{
            border: '1px solid #1a1a1a',
            borderRadius: 12,
            overflow: 'hidden',
          }}>
            {/* Header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
              padding: '14px 24px',
              background: '#0d0d0d',
              borderBottom: '1px solid #1a1a1a',
            }}>
              {['Capability', 'RegressionShield', 'LangSmith', 'Braintrust', 'DeepEval'].map((h, i) => (
                <div key={i} style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: i === 1 ? '#f5f5f5' : '#444',
                  fontWeight: i === 1 ? 600 : 400,
                }}>
                  {h}
                </div>
              ))}
            </div>

            {/* Rows */}
            {COMPARE.map(({ feature, rs, ls, bt, de }, i) => (
              <div
                key={feature}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                  padding: '14px 24px',
                  borderBottom: i < COMPARE.length - 1 ? '1px solid #111' : 'none',
                  background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                  transition: 'background 0.15s',
                }}
              >
                <span style={{ fontSize: 13, color: '#888' }}>{feature}</span>
                <span style={{ color: rs ? '#22c55e' : '#333', fontFamily: 'var(--mono)', fontSize: 14 }}>{rs ? '+' : '-'}</span>
                <span style={{ color: ls ? '#888'    : '#333', fontFamily: 'var(--mono)', fontSize: 14 }}>{ls ? '+' : '-'}</span>
                <span style={{ color: bt ? '#888'    : '#333', fontFamily: 'var(--mono)', fontSize: 14 }}>{bt ? '+' : '-'}</span>
                <span style={{ color: de ? '#888'    : '#333', fontFamily: 'var(--mono)', fontSize: 14 }}>{de ? '+' : '-'}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Integration ── */}
      <section id="integrate" style={{ padding: '100px 0', background: '#080808' }}>
        <div className="wrap">
          <div style={{ marginBottom: 48 }}>
            <div className="label" style={{ marginBottom: 16 }}>Integration</div>
            <h2 className="h2" style={{ maxWidth: 460 }}>
              Works with your stack
            </h2>
          </div>

          {/* Snippet tabs */}
          <div className="tabs" style={{ marginBottom: 20 }}>
            {Object.entries(SNIPPETS).map(([key, { label }]) => (
              <button
                key={key}
                className={`tab ${activeSnippet === key ? 'active' : ''}`}
                onClick={() => setActiveSnippet(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Code block */}
          <div className="code-block">
            <div className="code-bar">
              <span>{SNIPPETS[activeSnippet].lang}</span>
              <button
                onClick={copySnippet}
                style={{
                  background: 'none',
                  border: '1px solid #2a2a2a',
                  borderRadius: 4,
                  padding: '3px 10px',
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  color: '#555',
                  cursor: 'pointer',
                  transition: 'color 0.15s',
                }}
              >
                {copied ? 'copied' : 'copy'}
              </button>
            </div>
            <div className="code-body">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                <code>{SNIPPETS[activeSnippet].code}</code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── CTA ── */}
      <section style={{ padding: '120px 0', textAlign: 'center' }}>
        <div className="wrap">
          <div className="label" style={{ marginBottom: 20 }}>Open source — MIT License</div>
          <h2 className="h2" style={{ maxWidth: 560, margin: '0 auto 20px' }}>
            Stop shipping silent agent regressions
          </h2>
          <p className="body" style={{ maxWidth: 420, margin: '0 auto 40px' }}>
            Add one function call to your test suite and get a deterministic quality gate on every pull request.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
            <a href="/docs" className="btn btn-white">Read the docs</a>
            <a href="https://github.com" target="_blank" rel="noreferrer" className="btn btn-ghost">View on GitHub</a>
          </div>
        </div>
      </section>
    </>
  );
}
