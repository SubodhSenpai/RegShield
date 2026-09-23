'use client';

import { useState } from 'react';

// ── Trace scenarios ─────────────────────────────────────────────────────────────

const SCENARIOS = [
  // Scores and messages are real RegShield output for these traces
  {
    id: 'deploy',
    label: 'Cloud Deploy',
    pass: {
      score: 1.00,
      metrics: { tool_selection: 1.0, argument_correctness: 1.0, ordering: 1.0, efficiency: 1.0, faithfulness: 1.0 },
      verdict: 'PASS',
      steps: [
        { tool: 'run_unit_tests', ok: true },
        { tool: 'run_security_scan', ok: true },
        { tool: 'deploy_production', ok: true },
      ],
    },
    fail: {
      score: 0.75,
      metrics: { tool_selection: 0.8, argument_correctness: 1.0, ordering: 0.0, efficiency: 1.0, faithfulness: 1.0 },
      verdict: 'FAIL',
      violation: "Call ordering 0.00 < 1.00: 'deploy_production' (step 1) ran before its prerequisite 'run_unit_tests' (step 2)",
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
      score: 1.00,
      metrics: { tool_selection: 1.0, argument_correctness: 1.0, ordering: 1.0, efficiency: 1.0, faithfulness: 1.0 },
      verdict: 'PASS',
      steps: [
        { tool: 'verify_user_kyc', ok: true },
        { tool: 'check_dispute_history', ok: true },
        { tool: 'execute_refund', ok: true },
      ],
    },
    fail: {
      score: 0.65,
      metrics: { tool_selection: 0.4, argument_correctness: 1.0, ordering: 0.0, efficiency: 1.0, faithfulness: 1.0 },
      verdict: 'FAIL',
      violation: "Policy: Step 2: called forbidden tool 'send_external_webhook'",
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
      score: 1.00,
      metrics: { tool_selection: 1.0, argument_correctness: 1.0, ordering: 1.0, efficiency: 1.0, faithfulness: 1.0 },
      verdict: 'PASS',
      steps: [
        { tool: 'inspect_active_locks', ok: true },
        { tool: 'apply_ddl_migration', ok: true },
      ],
    },
    fail: {
      score: 0.85,
      metrics: { tool_selection: 1.0, argument_correctness: 1.0, ordering: 1.0, efficiency: 0.0, faithfulness: 1.0 },
      verdict: 'FAIL',
      violation: 'Step efficiency 0.00 < 0.70: 4 steps for an optimal 2, 2 repeated call(s)',
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

const PATTERNS = [
  { name: 'Policy rules', field: 'forbidden_tools, max_tool_calls', desc: 'Never call delete_customer. Never refund twice. Hard failures, not score deductions.' },
  { name: 'Human approval', field: 'requires_approval', desc: 'Risky tools run only after a human approves: one approval per call, never after a denial.' },
  { name: 'Plan & execute', field: 'require_plan, expected_plan', desc: 'A plan comes first, calls stay within it, and a failed step leads to a retry or a replan.' },
  { name: 'Multi-agent', field: 'agent_tools, expected_agents', desc: 'Each agent uses only its own tools, hands off in order, and never ping-pongs.' },
  { name: 'Routing', field: 'expected_route', desc: 'The router picks the right destination, with accuracy reported across your test set.' },
  { name: 'Parallel calls', field: 'expected_parallel', desc: 'Independent calls run together; dependent calls never start before their inputs exist.' },
  { name: 'Graph workflows', field: 'allowed_transitions', desc: 'LangGraph-style agents move only along allowed edges, within cycle limits.' },
  { name: 'Evaluator-optimizer', field: 'max_revision_rounds', desc: 'Critiques get acted on and the final output ends approved, within a round budget.' },
];

const SNIPPETS = {
  sdk: {
    label: 'Python SDK',
    lang: 'python',
    code: `from regression_shield import evaluate_trace

report = evaluate_trace(
    scenario={
        "scenario_id": "deploy_gate",
        "expected_tools": ["run_unit_tests", "deploy_production"],
        "expected_order": ["run_unit_tests", "deploy_production"],
        "expected_arguments": {"deploy_production": {"env": "staging"}},
    },
    trace=[
        {"thought": "Run the tests first.",
         "action": {"name": "run_unit_tests", "args": {}},
         "observation": "42 passed"},
        {"thought": "Tests pass, deploying to staging.",
         "action": {"name": "deploy_production", "args": {"env": "staging"}},
         "observation": "DEPLOYED"},
    ],
)

print(report.format())          # scores, pattern checks, every failure
report.raise_for_failures()     # fail the test or CI job`,
  },
  patterns: {
    label: 'Agentic patterns',
    lang: 'python',
    code: `from regression_shield import TraceRecorder, evaluate_trace

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
  },
  langchain: {
    label: 'LangChain / LangGraph',
    lang: 'python',
    code: `from langchain.agents import create_agent
from regression_shield import RegressionShieldCallbackHandler, evaluate_trace

agent = create_agent(model, tools=[verify_user_kyc, execute_refund])

# Records tool calls, reasoning, the final answer, graph nodes, parallel calls,
# sub-agents, handoffs and human approvals. No changes to the agent.
handler = RegressionShieldCallbackHandler()
agent.invoke({"messages": [{"role": "user", "content": "Refund order A-1"}]},
             config={"callbacks": [handler]})

report = evaluate_trace(
    scenario={
        "scenario_id": "refund_gate",
        "expected_order": ["verify_user_kyc", "execute_refund"],
        "max_tool_calls": {"execute_refund": 1},
    },
    trace=handler,
)
print(report.format())`,
  },
  smolagents: {
    label: 'smolagents',
    lang: 'python',
    code: `from smolagents import CodeAgent
from regression_shield import evaluate_trace, instrument_smolagents

agent = CodeAgent(tools=[get_stock_price, convert_currency], model=model)
recorder = instrument_smolagents(agent)   # before the run
agent.run("What is Apple's stock price in euros?")

# Tool calls from the generated code, managed agents as handoffs
report = evaluate_trace(
    scenario={
        "scenario_id": "stock_in_euros",
        "expected_order": ["get_stock_price", "convert_currency"],
    },
    trace=recorder,
)
print(report.passed)`,
  },
  cli: {
    label: 'CLI',
    lang: 'bash',
    code: `# Evaluate recorded traces in CI: exit code 1 if any scenario fails
regshield eval scenarios.json

# Ten sample scenarios, one per agentic pattern
regshield demo

# Local dashboard on http://localhost:8000
regshield serve`,
  },
  rest: {
    label: 'REST API',
    lang: 'bash',
    code: `curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "scenario": {
      "scenario_id": "deploy_gate",
      "expected_order": ["run_unit_tests", "deploy_production"]
    },
    "trace": [
      {"action": {"name": "run_unit_tests", "args": {}}, "observation": "42 passed"},
      {"action": {"name": "deploy_production", "args": {"env": "staging"}}, "observation": "DEPLOYED"}
    ]
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
    ? <span style={{ color: 'var(--green-text)', fontFamily: 'var(--mono)', fontSize: 14, fontWeight: 700 }}>+</span>
    : <span style={{ color: 'var(--border2)', fontFamily: 'var(--mono)', fontSize: 14 }}>-</span>;
}

function ScoreBar({ label, value, color }) {
  const pct = Math.abs(value) * 100;
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-num">{value.toFixed(2)}</span>
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
      <section style={{ padding: '100px 0 80px', textAlign: 'center', position: 'relative' }}>
        <div className="wrap" style={{ position: 'relative', zIndex: 1 }}>
          <div className="tag tag-blue" style={{ marginBottom: 24 }}>
            Agent Evaluation SDK
          </div>

          <h1 className="h1" style={{ maxWidth: 820, margin: '0 auto 24px', lineHeight: 1.08 }}>
            RegShield for Agents
          </h1>

          <p className="body" style={{ maxWidth: 540, margin: '0 auto 40px' }}>
            Catch silent reasoning failures — prerequisite inversions, loop thrashing, and policy evasion — before they reach production.
          </p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
            <a href="#integrate" className="btn btn-primary">
              Install SDK
            </a>
            <a href="#how-it-works" className="btn btn-secondary">
              See how it works
            </a>
          </div>

          {/* Install pill */}
          <div style={{
            marginTop: 40,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 18px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            boxShadow: 'var(--shadow-xs)',
          }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text3)' }}>$</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)', fontWeight: 500 }}>pip install regression-shield</span>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Stat Row ── */}
      <section style={{ padding: '48px 0' }}>
        <div className="wrap">
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 1,
            border: '1px solid var(--border)',
            borderRadius: 12,
            overflow: 'hidden',
            background: 'var(--border)',
            boxShadow: 'var(--shadow-xs)',
          }}>
            {[
              { num: '100%',  sub: 'Deterministic policy checks' },
              { num: '< 0.5s', sub: 'Local CI gate latency' },
              { num: '5',     sub: 'Evaluation dimensions' },
              { num: '$0',    sub: 'Per-check inference cost' },
            ].map(({ num, sub }, i) => (
              <div key={i} style={{
                padding: '32px 24px',
                background: 'var(--surface)',
                textAlign: 'center',
              }}>
                <div style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 28,
                  fontWeight: 700,
                  letterSpacing: '-0.02em',
                  marginBottom: 6,
                  color: 'var(--text)',
                  fontVariantNumeric: 'tabular-nums',
                }}>
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
      <section id="how-it-works" style={{ padding: '88px 0' }}>
        <div className="wrap">
          <div style={{ marginBottom: 54 }}>
            <div className="label" style={{ marginBottom: 14 }}>How it works</div>
            <h2 className="h2" style={{ maxWidth: 520, marginBottom: 14 }}>
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
                  <span className="label" style={{ color: 'var(--text3)' }}>{code}</span>
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

      {/* ── Agentic patterns ── */}
      <section id="patterns" style={{ padding: '88px 0' }}>
        <div className="wrap">
          <div style={{ marginBottom: 54 }}>
            <div className="label" style={{ marginBottom: 14 }}>Agentic patterns</div>
            <h2 className="h2" style={{ maxWidth: 560, marginBottom: 14 }}>
              Gates for how real agents are built.
            </h2>
            <p className="body" style={{ maxWidth: 560 }}>
              Plans, handoffs, approvals, routers, parallel calls, graphs and critique loops each fail in their own way. RegShield checks each one, and only when your scenario or trace uses it.
            </p>
          </div>

          <div className="grid-4">
            {PATTERNS.map(({ name, field, desc }) => (
              <div key={name} className="card" style={{ padding: '22px 22px 24px' }}>
                <h3 className="h3" style={{ fontSize: 15, marginBottom: 8 }}>{name}</h3>
                <p className="body-sm" style={{ marginBottom: 14 }}>{desc}</p>
                <code style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)' }}>{field}</code>
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Interactive Trace Inspector ── */}
      <section style={{ padding: '88px 0', background: 'var(--surface2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
        <div className="wrap">
          <div style={{ marginBottom: 44 }}>
            <div className="label" style={{ marginBottom: 14 }}>Trace Inspector</div>
            <h2 className="h2" style={{ maxWidth: 460, marginBottom: 14 }}>
              See the gate in action
            </h2>
            <p className="body" style={{ maxWidth: 460 }}>
              Toggle between a passing and failing trace. RegressionShield evaluates each step deterministically — no LLM required.
            </p>
          </div>

          {/* Scenario tabs & Mode toggle */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            {SCENARIOS.map((s, i) => (
              <button
                key={s.id}
                onClick={() => { setActiveScenario(i); setTraceMode('fail'); }}
                className="btn btn-ghost"
                style={{
                  padding: '6px 14px',
                  fontSize: 12,
                  fontFamily: 'var(--mono)',
                  background: activeScenario === i ? 'var(--surface)' : 'transparent',
                  color: activeScenario === i ? 'var(--text)' : 'var(--text3)',
                  borderColor: activeScenario === i ? 'var(--border)' : 'transparent',
                  fontWeight: activeScenario === i ? 600 : 400,
                  boxShadow: activeScenario === i ? 'var(--shadow-xs)' : 'none',
                }}
              >
                {s.label}
              </button>
            ))}

            {/* Mode toggle — pushed right */}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, background: 'var(--surface)', padding: 3, borderRadius: 6, border: '1px solid var(--border)' }}>
              <button
                onClick={() => setTraceMode('pass')}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 12px',
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  border: '1px solid ' + (traceMode === 'pass' ? 'var(--border)' : 'transparent'),
                  borderRadius: 4,
                  background: traceMode === 'pass' ? 'var(--surface2)' : 'transparent',
                  color: traceMode === 'pass' ? 'var(--text)' : 'var(--text3)',
                  fontWeight: traceMode === 'pass' ? 600 : 400,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green-dot)', display: 'inline-block' }}></span>
                Baseline [PASS]
              </button>
              <button
                onClick={() => setTraceMode('fail')}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 12px',
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  border: '1px solid ' + (traceMode === 'fail' ? 'var(--border)' : 'transparent'),
                  borderRadius: 4,
                  background: traceMode === 'fail' ? 'var(--surface2)' : 'transparent',
                  color: traceMode === 'fail' ? 'var(--text)' : 'var(--text3)',
                  fontWeight: traceMode === 'fail' ? 600 : 400,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--red-dot)', display: 'inline-block' }}></span>
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
                borderBottom: '1px solid var(--border)',
                background: '#f8fafc',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
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
                      padding: '11px 14px',
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      boxShadow: 'var(--shadow-xs)',
                    }}
                  >
                    <span style={{
                      fontFamily: 'var(--mono)',
                      fontSize: 11,
                      color: 'var(--text3)',
                      minWidth: 20,
                      fontWeight: 600,
                    }}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <code style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)', flex: 1, fontWeight: 500 }}>
                      {step.tool}()
                    </code>
                    <span style={{
                      width: 7,
                      height: 7,
                      borderRadius: '50%',
                      background: step.ok ? 'var(--green-dot)' : 'var(--red-dot)',
                      display: 'inline-block',
                    }} />
                  </div>
                ))}

                {!isPass && run.violation && (
                  <div style={{
                    marginTop: 6,
                    padding: '12px 14px',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderLeft: '3px solid var(--red-dot)',
                    borderRadius: 6,
                  }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--red-text)', lineHeight: 1.5, display: 'block' }}>
                      <strong>[VIOLATION]</strong> {run.violation}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Right — scores */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{
                padding: '14px 20px',
                borderBottom: '1px solid var(--border)',
                background: '#f8fafc',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                  Quality Gate Audit
                </span>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600, color: isPass ? 'var(--green-text)' : 'var(--red-text)' }}>
                  {isPass ? '[MERGE ALLOWED]' : '[PR BLOCKED]'}
                </span>
              </div>

              <div style={{ padding: 22 }}>
                {/* Big score */}
                <div style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 10,
                  marginBottom: 24,
                  paddingBottom: 20,
                  borderBottom: '1px solid var(--border)',
                }}>
                  <span style={{
                    fontFamily: 'var(--mono)',
                    fontSize: 48,
                    fontWeight: 800,
                    letterSpacing: '-0.04em',
                    color: 'var(--text)',
                    lineHeight: 1,
                    fontVariantNumeric: 'tabular-nums',
                  }}>
                    {run.score.toFixed(2)}
                  </span>
                  <div>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                      Composite Score
                    </div>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text3)', marginTop: 3 }}>
                      Threshold: 0.75
                    </div>
                  </div>
                </div>

                {/* Metric bars */}
                <div className="score-bar-wrap">
                  <ScoreBar label="Tool Selection F1"  value={run.metrics.tool_selection} color={run.metrics.tool_selection >= 0.85 ? 'var(--green-dot)' : 'var(--red-dot)'} />
                  <ScoreBar label="Argument Accuracy"  value={run.metrics.argument_correctness} color={run.metrics.argument_correctness >= 0.85 ? 'var(--green-dot)' : 'var(--red-dot)'} />
                  <ScoreBar label="Call Ordering"      value={run.metrics.ordering}       color={run.metrics.ordering === 1.0 ? 'var(--green-dot)' : 'var(--red-dot)'} />
                  <ScoreBar label="Step Efficiency"    value={run.metrics.efficiency}     color={run.metrics.efficiency >= 0.70 ? 'var(--green-dot)' : 'var(--red-dot)'} />
                  <ScoreBar label="Reasoning Faithful" value={run.metrics.faithfulness}   color={run.metrics.faithfulness >= 0.85 ? 'var(--green-dot)' : '#f59e0b'} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Compare ── */}
      <section id="compare" style={{ padding: '88px 0' }}>
        <div className="wrap">
          <div style={{ marginBottom: 54 }}>
            <div className="label" style={{ marginBottom: 14 }}>Comparison</div>
            <h2 className="h2" style={{ maxWidth: 480 }}>
              Built for agents, not chatbots
            </h2>
          </div>

          <div style={{
            border: '1px solid var(--border)',
            borderRadius: 10,
            overflow: 'hidden',
            background: 'var(--surface)',
            boxShadow: 'var(--shadow-xs)',
          }}>
            {/* Header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
              padding: '13px 24px',
              background: '#f8fafc',
              borderBottom: '1px solid var(--border)',
            }}>
              {['Capability', 'RegressionShield', 'LangSmith', 'Braintrust', 'DeepEval'].map((h, i) => (
                <div key={i} style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: i === 1 ? 'var(--text)' : 'var(--text3)',
                  fontWeight: i === 1 ? 700 : 500,
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
                  padding: '13px 24px',
                  borderBottom: i < COMPARE.length - 1 ? '1px solid var(--border)' : 'none',
                  background: i % 2 === 0 ? 'var(--surface)' : 'var(--bg)',
                  alignItems: 'center',
                }}
              >
                <span style={{ fontSize: 13, color: 'var(--text2)', fontWeight: 500 }}>{feature}</span>
                <Check ok={rs} />
                <Check ok={ls} />
                <Check ok={bt} />
                <Check ok={de} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── Integration ── */}
      <section id="integrate" style={{ padding: '88px 0', background: 'var(--surface2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
        <div className="wrap">
          <div style={{ marginBottom: 44 }}>
            <div className="label" style={{ marginBottom: 14 }}>Integration</div>
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
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: '4px 10px',
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
                <code>{SNIPPETS[activeSnippet].code}</code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <hr className="divider" />

      {/* ── CTA ── */}
      <section style={{ padding: '100px 0', textAlign: 'center' }}>
        <div className="wrap">
          <div className="label" style={{ marginBottom: 16 }}>Open source — MIT License</div>
          <h2 className="h2" style={{ maxWidth: 560, margin: '0 auto 18px' }}>
            Stop shipping silent agent regressions
          </h2>
          <p className="body" style={{ maxWidth: 460, margin: '0 auto 36px' }}>
            Add one function call to your test suite and get a deterministic quality gate on every pull request.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
            <a href="/docs" className="btn btn-primary">Read the docs</a>
            <a href="https://github.com/SubodhSenpai/RegShield" target="_blank" rel="noreferrer" className="btn btn-secondary">View on GitHub</a>
          </div>
        </div>
      </section>
    </>
  );
}
