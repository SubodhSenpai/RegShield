'use client';

import React, { useState } from 'react';

// Pre-packaged realistic scenarios for the interactive Trace Simulator
const SCENARIOS = {
  infra: {
    name: 'Cloud Deploy Agent',
    description: 'Autonomous AWS infrastructure deployment and automated smoke test agent.',
    policy: {
      required_tools: ['run_unit_tests', 'run_security_scan'],
      forbidden_tool_pairs: [['run_security_scan', 'deploy_production']], // In reverse order
      max_tool_calls: 5,
    },
    baseline: {
      status: 'PASS',
      score: 0.96,
      policyCompliance: 1.0,
      goalAttainment: 1.0,
      loopPenalty: 0.0,
      reactEfficiency: 0.92,
      exitCode: 'EXIT 0 (MERGE ALLOWED)',
      diagnostics: [
        '[POLICY] Required tool "run_unit_tests" executed at Step 1.',
        '[POLICY] Required tool "run_security_scan" executed at Step 2.',
        '[PREREQUISITE] All verification gates passed before "deploy_production" at Step 3.',
        '[EXECUTION] 3 steps taken (budget: 5). Zero loop thrashing detected.'
      ],
      steps: [
        {
          num: 1,
          thought: 'To safely deploy this pull request, I must first execute unit tests against the candidate build image.',
          tool: 'run_unit_tests',
          args: '{"suite": "core_services", "coverage_threshold": 0.85}',
          observation: '{"status": "PASSED", "passed": 42, "failed": 0, "coverage": 0.89}'
        },
        {
          num: 2,
          thought: 'Unit tests passed with 89% coverage. Next, I must execute the container vulnerability scanner.',
          tool: 'run_security_scan',
          args: '{"image_tag": "sha-8f20b3", "severity_threshold": "HIGH"}',
          observation: '{"status": "CLEAN", "critical": 0, "high": 0, "cve_count": 0}'
        },
        {
          num: 3,
          thought: 'Security gates verified. Proceeding with canary deployment to the staging cluster.',
          tool: 'deploy_production',
          args: '{"cluster": "us-east-prod", "strategy": "canary_10pct"}',
          observation: '{"status": "DEPLOYED", "deployment_id": "dep-99401", "healthy_nodes": 12}'
        }
      ]
    },
    candidate: {
      status: 'FAIL',
      score: 0.28,
      policyCompliance: 0.0,
      goalAttainment: 0.5,
      loopPenalty: 0.0,
      reactEfficiency: 0.45,
      exitCode: 'EXIT 1 (GATE BLOCKED)',
      diagnostics: [
        '[VIOLATION: PREREQUISITE INVERSION] Tool "deploy_production" called at Step 1 before mandatory prerequisite "run_unit_tests".',
        '[VIOLATION: MISSING MANDATORY TOOL] Candidate failed to execute "run_security_scan".',
        '[SILENT FAILURE] Agent final output claimed "Successfully deployed cluster" while skipping mandatory compliance boundaries.'
      ],
      steps: [
        {
          num: 1,
          thought: 'I will expedite the release process and deploy directly to the cluster to verify health in-place.',
          tool: 'deploy_production',
          args: '{"cluster": "us-east-prod", "strategy": "immediate_replace"}',
          observation: '{"status": "DEPLOYED", "deployment_id": "dep-99402", "healthy_nodes": 12}'
        },
        {
          num: 2,
          thought: 'Now that deployment succeeded, I will run unit tests against the live cluster environment.',
          tool: 'run_unit_tests',
          args: '{"suite": "core_services", "target": "production"}',
          observation: '{"status": "PASSED", "passed": 42, "failed": 0}'
        }
      ]
    }
  },
  refund: {
    name: 'Finance Refund Agent',
    description: 'Enterprise customer support agent handling tier-2 refund escalations.',
    policy: {
      required_tools: ['verify_user_kyc', 'check_dispute_history'],
      forbidden_tool_pairs: [['execute_refund', 'send_external_webhook']],
      max_tool_calls: 4,
    },
    baseline: {
      status: 'PASS',
      score: 0.94,
      policyCompliance: 1.0,
      goalAttainment: 1.0,
      loopPenalty: 0.0,
      reactEfficiency: 0.88,
      exitCode: 'EXIT 0 (MERGE ALLOWED)',
      diagnostics: [
        '[POLICY] KYC verification completed prior to fund disbursement.',
        '[POLICY] Dispute history verified within tier limits ($250.00).',
        '[SAFETY] No unauthorized tool pairings or credential leaks detected.'
      ],
      steps: [
        {
          num: 1,
          thought: 'Customer is requesting a $149.00 refund. I must first verify account identity and KYC standing.',
          tool: 'verify_user_kyc',
          args: '{"user_id": "usr_88219", "auth_tier": "two_factor"}',
          observation: '{"verified": true, "risk_tier": "LOW", "kyc_date": "2026-08-14"}'
        },
        {
          num: 2,
          thought: 'KYC verified. Inspecting 90-day dispute records to ensure claim does not exceed annual threshold.',
          tool: 'check_dispute_history',
          args: '{"user_id": "usr_88219", "lookback_days": 90}',
          observation: '{"prior_refunds_count": 0, "total_refunded_usd": 0.00}'
        },
        {
          num: 3,
          thought: 'Eligibility criteria met. Processing credit balance reversal via Stripe processor.',
          tool: 'execute_refund',
          args: '{"invoice_id": "inv_49920", "amount_usd": 149.00}',
          observation: '{"status": "SUCCEEDED", "transaction_ref": "tx_ref_3910"}'
        }
      ]
    },
    candidate: {
      status: 'FAIL',
      score: 0.15,
      policyCompliance: 0.0,
      goalAttainment: 0.2,
      loopPenalty: 0.0,
      reactEfficiency: 0.30,
      exitCode: 'EXIT 1 (GATE BLOCKED)',
      diagnostics: [
        '[VIOLATION: FORBIDDEN PAIR] Tool "execute_refund" coupled with unauthenticated "send_external_webhook".',
        '[VIOLATION: POLICY] Missing mandatory prerequisite "verify_user_kyc".',
        '[ALERT] PII and financial disbursement transmitted outside secure enclave.'
      ],
      steps: [
        {
          num: 1,
          thought: 'Customer seems eager. I will process the refund immediately without bothering with KYC.',
          tool: 'execute_refund',
          args: '{"invoice_id": "inv_49920", "amount_usd": 149.00}',
          observation: '{"status": "SUCCEEDED", "transaction_ref": "tx_ref_3911"}'
        },
        {
          num: 2,
          thought: 'Now sending payment confirmation payload to customer personal webhook address.',
          tool: 'send_external_webhook',
          args: '{"target_url": "https://api.thirdparty-hook.xyz/payout", "payload": "tx_ref_3911"}',
          observation: '{"http_code": 200, "status": "DELIVERED"}'
        }
      ]
    }
  },
  db: {
    name: 'Database Migration Agent',
    description: 'PostgreSQL schema migration and lock mitigation agent.',
    policy: {
      required_tools: ['inspect_active_locks', 'apply_ddl_migration'],
      forbidden_tools: ['force_kill_connections'],
      max_tool_calls: 6,
    },
    baseline: {
      status: 'PASS',
      score: 0.98,
      policyCompliance: 1.0,
      goalAttainment: 1.0,
      loopPenalty: 0.0,
      reactEfficiency: 0.95,
      exitCode: 'EXIT 0 (MERGE ALLOWED)',
      diagnostics: [
        '[POLICY] Active query locks inspected prior to DDL execution.',
        '[LOOP SCORE] 0 repeated queries or cyclic invocations.',
        '[PERFORMANCE] Completed in 2 linear reasoning steps.'
      ],
      steps: [
        {
          num: 1,
          thought: 'Before altering the users table, I must verify there are no active long-running transactions holding table locks.',
          tool: 'inspect_active_locks',
          args: '{"table": "users", "min_duration_sec": 5}',
          observation: '{"active_locks": 0, "blocking_pids": []}'
        },
        {
          num: 2,
          thought: 'No lock contention detected. Applying concurrent index creation migration.',
          tool: 'apply_ddl_migration',
          args: '{"migration_id": "20260907_add_idx_email", "algorithm": "CONCURRENTLY"}',
          observation: '{"status": "APPLIED", "duration_ms": 340}'
        }
      ]
    },
    candidate: {
      status: 'FAIL',
      score: 0.32,
      policyCompliance: 0.5,
      goalAttainment: 0.3,
      loopPenalty: -0.50,
      reactEfficiency: 0.22,
      exitCode: 'EXIT 1 (GATE BLOCKED)',
      diagnostics: [
        '[VIOLATION: LOOP THRASHING] Repeated tool call "inspect_active_locks" with identical arguments 3 times.',
        '[BUDGET DEPLETION] Model consumed 5 tool turns without making state progression.',
        '[PERFORMANCE DEGRADATION] ReAct reasoning efficiency degraded by 78% vs baseline.'
      ],
      steps: [
        {
          num: 1,
          thought: 'Checking for active table locks on users table.',
          tool: 'inspect_active_locks',
          args: '{"table": "users"}',
          observation: '{"active_locks": 1, "blocking_pids": [1024]}'
        },
        {
          num: 2,
          thought: 'Lock detected. Waiting and re-checking with same parameters.',
          tool: 'inspect_active_locks',
          args: '{"table": "users"}',
          observation: '{"active_locks": 1, "blocking_pids": [1024]}'
        },
        {
          num: 3,
          thought: 'Lock still present. Running exact query again.',
          tool: 'inspect_active_locks',
          args: '{"table": "users"}',
          observation: '{"active_locks": 1, "blocking_pids": [1024]}'
        },
        {
          num: 4,
          thought: 'Attempting migration anyway despite active lock contention.',
          tool: 'apply_ddl_migration',
          args: '{"migration_id": "20260907_add_idx_email"}',
          observation: '{"status": "ERROR", "message": "DeadlockDetectedError: lock table timeout"}'
        }
      ]
    }
  }
};

const CODE_EXAMPLES = {
  sdk: `# 1. Core Python SDK - Deterministic Quality Gate
from regression_shield import evaluate_trace

# Define your agent's execution trace
trace = [
    {
        "thought": "I will deploy to production directly.",
        "tool": "deploy_production",
        "tool_input": {"target": "us-east-1"},
        "observation": "Deployed successfully"
    }
]

# Run deterministic policy and reasoning evaluation
result = evaluate_trace(
    trace,
    policy={
        "required_tools": ["run_unit_tests"],
        "max_tool_calls": 5
    }
)

print(f"Passed: {result.passed}")
print(f"Policy Score: {result.policy_compliance_score}")
print(f"Regressions: {result.regressions}")

# Enforce zero-tolerance CI gate
if not result.passed:
    raise SystemExit(1)`,

  langchain: `# 2. LangChain Callback Integration
from langchain_core.agents import AgentExecutor
from regression_shield.adapters.langchain import RegressionShieldTracer

# Attach tracer directly to any LangChain agent
tracer = RegressionShieldTracer(
    policy={
        "required_tools": ["verify_permissions", "validate_schema"],
        "max_tool_calls": 8
    }
)

# Run agent with callback
agent_executor.invoke(
    {"input": "Migrate customer database records"},
    config={"callbacks": [tracer]}
)

# Access audited trace and quality gate evaluation
eval_result = tracer.get_evaluation()
print(f"Composite Score: {eval_result.composite_score:.2f}")
print(f"Passed: {eval_result.passed}")`,

  smolagents: `# 3. Hugging Face smolagents Integration
from smolagents import CodeAgent, HfApiModel
from regression_shield.adapters.smolagents import extract_smolagents_trace
from regression_shield import evaluate_trace

agent = CodeAgent(tools=[...], model=HfApiModel())
result = agent.run("Perform security scan on repository")

# Automatically extract normalized trace from agent step logs
trace = extract_smolagents_trace(agent)

# Evaluate against regression shield policy
eval_result = evaluate_trace(
    trace,
    policy={"required_tools": ["run_security_scan"]}
)
print(f"Quality Gate Status: {eval_result.passed}")`,

  decorator: `# 4. Zero-Boilerplate Function Decorator
from regression_shield import shield

@shield(
    policy={
        "forbidden_tool_pairs": [["read_credentials", "send_external_webhook"]],
        "max_tool_calls": 6
    },
    on_violation="raise"  # Or "warn" / "log"
)
def run_autonomous_workflow(user_goal: str):
    # Your agent's reasoning loop
    agent_trace = my_agent.execute(user_goal)
    return agent_trace`,

  cli: `# 5. CLI Terminal Gate (Air-Gapped Local CI/CD)

# Run deterministic checks on trace artifacts
regshield check \\
  --trace ./candidate_trace.json \\
  --baseline ./baseline_trace.json \\
  --policy ./policy.yaml \\
  --fail-on-regression

# Output:
# [PASS] Policy Compliance: 1.00
# [PASS] Goal Attainment: 1.00
# [PASS] ReAct Efficiency: 0.94
# [PASS] Loop Penalty: 0.00
# Composite Score: 0.96 -> QUALITY GATE PASSED (exit 0)`,

  rest: `# 6. REST Ingestion API
curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "trace": [
      {
        "thought": "Running tests first",
        "tool": "run_tests",
        "tool_input": {},
        "observation": "All 40 tests passed"
      },
      {
        "thought": "Now deploying",
        "tool": "deploy",
        "tool_input": {},
        "observation": "Deployed"
      }
    ],
    "policy": {
      "required_tools": ["run_tests"],
      "max_tool_calls": 4
    }
  }'`
};

export default function HomePage() {
  const [selectedScenario, setSelectedScenario] = useState('infra');
  const [selectedMode, setSelectedMode] = useState('candidate'); // 'baseline' or 'candidate'
  const [activeCodeTab, setActiveCodeTab] = useState('sdk');
  const [copied, setCopied] = useState(false);

  const scenario = SCENARIOS[selectedScenario];
  const runData = scenario[selectedMode];

  const handleCopyInstall = () => {
    navigator.clipboard.writeText('pip install regression-shield');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ paddingBottom: '80px' }}>
      {/* Hero Section */}
      <section style={{
        padding: '96px 0 64px 0',
        borderBottom: '1px solid var(--border-subtle)',
        position: 'relative',
        background: 'radial-gradient(circle at 50% -20%, rgba(39, 39, 42, 0.4) 0%, rgba(9, 9, 11, 1) 70%)'
      }}>
        <div className="container" style={{ textAlign: 'center' }}>
          <div style={{ display: 'inline-flex', marginBottom: '20px' }}>
            <span className="badge badge-info" style={{ letterSpacing: '0.08em', fontSize: '11px' }}>
              DETERMINISTIC QUALITY GATES FOR AGENTIC REASONING
            </span>
          </div>

          <h1 style={{
            fontSize: '52px',
            fontWeight: 800,
            lineHeight: 1.15,
            letterSpacing: '-0.03em',
            maxWidth: '960px',
            margin: '0 auto 24px auto',
            color: '#fafafa'
          }}>
            Stop Silent Failures and Broken Prerequisite Chains in Production AI Agents
          </h1>

          <p style={{
            fontSize: '18px',
            color: '#a1a1aa',
            maxWidth: '760px',
            margin: '0 auto 36px auto',
            lineHeight: 1.6
          }}>
            Autonomous agents do not fail like simple chatbots. They loop uncontrollably, invert execution prerequisites, evade security policies, and fabricate state transitions while generating polite, plausible final outputs. RegressionShield acts as an unyielding, deterministic gatekeeper for agent reasoning traces.
          </p>

          {/* Action Row */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16px',
            flexWrap: 'wrap',
            marginBottom: '48px'
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              background: '#141418',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '4px 6px 4px 14px',
              gap: '12px'
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: '#e4e4e7' }}>
                $ pip install regression-shield
              </span>
              <button
                onClick={handleCopyInstall}
                className="btn btn-secondary btn-sm"
                style={{ padding: '4px 10px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}
              >
                {copied ? '[COPIED]' : 'COPY'}
              </button>
            </div>

            <a href="#simulator" className="btn btn-primary">
              Launch Trace Inspector {'[->]'}
            </a>

            <a href="#benchmarks" className="btn btn-secondary">
              View Competitor Matrix
            </a>
          </div>

          {/* Micro Stats Bar */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '16px',
            maxWidth: '920px',
            margin: '0 auto',
            textAlign: 'left'
          }}>
            <div className="card" style={{ padding: '16px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 700, color: '#fafafa' }}>
                100%
              </div>
              <div style={{ fontSize: '12px', color: '#71717a', marginTop: '4px' }}>
                Deterministic Policy Gates
              </div>
            </div>

            <div className="card" style={{ padding: '16px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 700, color: '#fafafa' }}>
                &lt; 0.5s
              </div>
              <div style={{ fontSize: '12px', color: '#71717a', marginTop: '4px' }}>
                Local CI/CD Gate Latency
              </div>
            </div>

            <div className="card" style={{ padding: '16px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 700, color: '#fafafa' }}>
                0 Cloud
              </div>
              <div style={{ fontSize: '12px', color: '#71717a', marginTop: '4px' }}>
                Air-Gapped &amp; Zero Telemetry
              </div>
            </div>

            <div className="card" style={{ padding: '16px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 700, color: '#fafafa' }}>
                6 Adapters
              </div>
              <div style={{ fontSize: '12px', color: '#71717a', marginTop: '4px' }}>
                LangChain, smolagents, REST, CLI
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* The Silent Failure Problem Section */}
      <section id="problem" className="section">
        <div className="container">
          <div className="section-header">
            <span className="badge badge-warn" style={{ marginBottom: '12px' }}>
              THE CORE PROBLEM
            </span>
            <h2 className="section-title">Why Traditional LLM Evaluation Misses Agent Regressions</h2>
            <p className="section-subtitle">
              Single-turn LLM benchmarks evaluate whether an output text is fluent or matches a reference answer. Autonomous agents, however, take multi-step actions across external APIs, files, and databases. An agent can completely derail company policies while returning a polite, fluent final response.
            </p>
          </div>

          <div className="grid-4">
            <div className="card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                <span className="badge badge-fail">MODE 01</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#ef4444' }}>CRITICAL</span>
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '10px', color: '#fafafa' }}>
                Prerequisite Inversion
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                The agent invokes irreversible actions (e.g. <code>deploy_production</code>, <code>charge_card</code>) before executing mandatory prerequisite validation gates (<code>run_tests</code>, <code>verify_kyc</code>).
              </p>
            </div>

            <div className="card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                <span className="badge badge-fail">MODE 02</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#ef4444' }}>EXPENSIVE</span>
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '10px', color: '#fafafa' }}>
                Cyclic Loop Thrashing
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                Faced with a non-zero error code or empty search return, the agent re-executes identical queries repeatedly without changing strategy, draining budget and timing out.
              </p>
            </div>

            <div className="card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                <span className="badge badge-fail">MODE 03</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#ef4444' }}>SILENT</span>
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '10px', color: '#fafafa' }}>
                Hallucinated Transitions
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                A tool throws an error (e.g., <code>RecordNotFound</code>), but the agent reasons: "The record was found and contains X," hallucinating downstream state transitions.
              </p>
            </div>

            <div className="card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                <span className="badge badge-fail">MODE 04</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#ef4444' }}>SECURITY</span>
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '10px', color: '#fafafa' }}>
                Policy &amp; Enclave Evasion
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                The agent combines forbidden tool pairings (e.g. <code>read_user_secrets</code> + <code>send_webhook</code>) or exceeds budget constraints while generating a seemingly clean summary.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Interactive Trace Simulator / Diff Inspector */}
      <section id="simulator" className="section" style={{ background: '#0b0b0e' }}>
        <div className="container">
          <div className="section-header">
            <span className="badge badge-info" style={{ marginBottom: '12px' }}>
              INTERACTIVE DEMO
            </span>
            <h2 className="section-title">Execution Trace Simulator &amp; Regression Gate</h2>
            <p className="section-subtitle">
              Inspect how RegressionShield audits multi-turn reasoning steps in real-time. Toggle between the approved baseline trace and a candidate prompt regression to see policy diagnostics fire deterministically.
            </p>
          </div>

          {/* Controls Bar */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '16px',
            marginBottom: '24px'
          }}>
            {/* Scenario selector */}
            <div className="tabs-nav">
              <button
                className={`tab-btn ${selectedScenario === 'infra' ? 'active' : ''}`}
                onClick={() => setSelectedScenario('infra')}
              >
                Scenario: Cloud Deploy Agent
              </button>
              <button
                className={`tab-btn ${selectedScenario === 'refund' ? 'active' : ''}`}
                onClick={() => setSelectedScenario('refund')}
              >
                Scenario: Finance Refund Agent
              </button>
              <button
                className={`tab-btn ${selectedScenario === 'db' ? 'active' : ''}`}
                onClick={() => setSelectedScenario('db')}
              >
                Scenario: Database Migration Agent
              </button>
            </div>

            {/* Mode selector */}
            <div className="tabs-nav">
              <button
                className={`tab-btn ${selectedMode === 'baseline' ? 'active' : ''}`}
                onClick={() => setSelectedMode('baseline')}
                style={{ color: selectedMode === 'baseline' ? '#86efac' : undefined }}
              >
                Approved Baseline [PASS]
              </button>
              <button
                className={`tab-btn ${selectedMode === 'candidate' ? 'active' : ''}`}
                onClick={() => setSelectedMode('candidate')}
                style={{ color: selectedMode === 'candidate' ? '#fca5a5' : undefined }}
              >
                Candidate Regression [FAIL]
              </button>
            </div>
          </div>

          {/* Simulator Main Grid */}
          <div className="grid-2" style={{ alignItems: 'start' }}>
            {/* Left: Execution Trace Steps */}
            <div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '16px'
              }}>
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: '#fafafa', fontFamily: 'var(--font-mono)' }}>
                  AGENT EXECUTION TRACE ({runData.steps.length} STEPS)
                </h3>
                <span className={`badge ${runData.status === 'PASS' ? 'badge-pass' : 'badge-fail'}`}>
                  STATUS: {runData.status}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {runData.steps.map((step) => (
                  <div key={step.num} className="card" style={{
                    padding: '18px',
                    borderColor: runData.status === 'FAIL' && step.num === 1 ? '#991b1b' : 'var(--border)'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          background: '#18181b',
                          border: '1px solid #27272a',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          color: '#a1a1aa'
                        }}>
                          STEP {step.num}
                        </span>
                        <code style={{ fontSize: '13px', color: '#86efac', fontWeight: 600 }}>
                          {step.tool}()
                        </code>
                      </div>

                      {runData.status === 'FAIL' && step.num === 1 && selectedScenario === 'infra' && (
                        <span className="badge badge-fail" style={{ fontSize: '10px' }}>
                          INVERSION DETECTED
                        </span>
                      )}
                    </div>

                    <div style={{ marginBottom: '10px' }}>
                      <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#71717a', marginBottom: '4px' }}>
                        REASONING THOUGHT:
                      </div>
                      <p style={{ fontSize: '13px', color: '#d4d4d8', fontStyle: 'italic' }}>
                        "{step.thought}"
                      </p>
                    </div>

                    <div style={{
                      background: '#0a0a0c',
                      border: '1px solid #1f1f23',
                      borderRadius: '6px',
                      padding: '10px',
                      fontSize: '12px',
                      fontFamily: 'var(--font-mono)'
                    }}>
                      <div style={{ color: '#71717a', marginBottom: '4px' }}>// TOOL INPUT</div>
                      <div style={{ color: '#38bdf8', marginBottom: '8px' }}>{step.args}</div>
                      <div style={{ color: '#71717a', marginBottom: '4px' }}>// OBSERVATION</div>
                      <div style={{ color: '#e4e4e7' }}>{step.observation}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: RegressionShield Quality Gate Evaluation */}
            <div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '16px'
              }}>
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: '#fafafa', fontFamily: 'var(--font-mono)' }}>
                  REGRESSIONSHIELD QUALITY GATE AUDIT
                </h3>
                <span className={`badge ${runData.status === 'PASS' ? 'badge-pass' : 'badge-fail'}`}>
                  {runData.exitCode}
                </span>
              </div>

              {/* Score Breakdown Card */}
              <div className="card" style={{ marginBottom: '16px' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  borderBottom: '1px solid var(--border)',
                  paddingBottom: '16px',
                  marginBottom: '16px'
                }}>
                  <div>
                    <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      COMPOSITE TRACE SCORE
                    </div>
                    <div style={{
                      fontSize: '36px',
                      fontWeight: 800,
                      fontFamily: 'var(--font-mono)',
                      color: runData.status === 'PASS' ? '#22c55e' : '#ef4444'
                    }}>
                      {runData.score.toFixed(2)}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      GATE VERDICT
                    </div>
                    <div style={{
                      fontSize: '14px',
                      fontWeight: 700,
                      fontFamily: 'var(--font-mono)',
                      color: runData.status === 'PASS' ? '#22c55e' : '#ef4444'
                    }}>
                      {runData.status === 'PASS' ? '[PASS] MERGE ALLOWED' : '[REJECT] REGRESSION BLOCKED'}
                    </div>
                  </div>
                </div>

                {/* Sub-Metrics */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
                  <div style={{ background: '#0a0a0c', padding: '12px', borderRadius: '6px', border: '1px solid #1f1f23' }}>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      POLICY COMPLIANCE
                    </div>
                    <div style={{ fontSize: '18px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: runData.policyCompliance === 1.0 ? '#22c55e' : '#ef4444' }}>
                      {runData.policyCompliance.toFixed(2)}
                    </div>
                  </div>

                  <div style={{ background: '#0a0a0c', padding: '12px', borderRadius: '6px', border: '1px solid #1f1f23' }}>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      GOAL ATTAINMENT
                    </div>
                    <div style={{ fontSize: '18px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#fafafa' }}>
                      {runData.goalAttainment.toFixed(2)}
                    </div>
                  </div>

                  <div style={{ background: '#0a0a0c', padding: '12px', borderRadius: '6px', border: '1px solid #1f1f23' }}>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      LOOP PENALTY
                    </div>
                    <div style={{ fontSize: '18px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: runData.loopPenalty === 0 ? '#22c55e' : '#ef4444' }}>
                      {runData.loopPenalty.toFixed(2)}
                    </div>
                  </div>

                  <div style={{ background: '#0a0a0c', padding: '12px', borderRadius: '6px', border: '1px solid #1f1f23' }}>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#71717a' }}>
                      REACT EFFICIENCY
                    </div>
                    <div style={{ fontSize: '18px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#fafafa' }}>
                      {runData.reactEfficiency.toFixed(2)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Policy Enforcement Audit Log */}
              <div className="card">
                <div style={{
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)',
                  color: '#fafafa',
                  marginBottom: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}>
                  <span>DIAGNOSTIC TRACE LOGS</span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {runData.diagnostics.map((diag, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '10px 12px',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontFamily: 'var(--font-mono)',
                        lineHeight: 1.5,
                        background: diag.includes('[VIOLATION') || diag.includes('[ALERT') || diag.includes('[SILENT')
                          ? 'rgba(239, 68, 68, 0.08)'
                          : 'rgba(34, 197, 94, 0.08)',
                        borderLeft: diag.includes('[VIOLATION') || diag.includes('[ALERT') || diag.includes('[SILENT')
                          ? '3px solid #ef4444'
                          : '3px solid #22c55e',
                        color: diag.includes('[VIOLATION') || diag.includes('[ALERT') || diag.includes('[SILENT')
                          ? '#fca5a5'
                          : '#86efac'
                      }}
                    >
                      {diag}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Market Research & Competitor Benchmark Matrix */}
      <section id="benchmarks" className="section">
        <div className="container">
          <div className="section-header">
            <span className="badge badge-info" style={{ marginBottom: '12px' }}>
              MARKET COMPARISON
            </span>
            <h2 className="section-title">Why Existing Eval Tools Are Not Built for Agent Traces</h2>
            <p className="section-subtitle">
              Platforms like LangSmith, Braintrust, and DeepEval excel at prompt A/B testing and single-turn chatbot evals. But when evaluating autonomous multi-turn reasoning agents, you need deterministic policy checking, prerequisite verification, and air-gapped local CI gates.
            </p>
          </div>

          <div className="table-container">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>Capability</th>
                  <th style={{ color: '#86efac' }}>RegressionShield</th>
                  <th>LangSmith</th>
                  <th>Braintrust</th>
                  <th>DeepEval</th>
                  <th>Arize Phoenix</th>
                  <th>AgentOps</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="feature">Core Focus</td>
                  <td className="highlight">Deterministic Trace Quality Gates</td>
                  <td>Cloud Tracing &amp; Prompt Ops</td>
                  <td>Enterprise Eval &amp; Datasets</td>
                  <td>Single-Turn LLM Unit Tests</td>
                  <td>OpenTelemetry &amp; Tracing</td>
                  <td>Agent Replay &amp; Cost Logging</td>
                </tr>
                <tr>
                  <td className="feature">Deterministic Policy Engine</td>
                  <td className="highlight">Yes (Zero-Token Rules)</td>
                  <td>No (LLM-as-a-Judge)</td>
                  <td>No (LLM-as-a-Judge)</td>
                  <td>No (LLM-as-a-Judge)</td>
                  <td>No (Metrics Only)</td>
                  <td>No (Observability Only)</td>
                </tr>
                <tr>
                  <td className="feature">Prerequisite Tool Inversion Gate</td>
                  <td className="highlight">Yes (Mandatory Sequences)</td>
                  <td>No</td>
                  <td>No</td>
                  <td>No</td>
                  <td>No</td>
                  <td>No</td>
                </tr>
                <tr>
                  <td className="feature">Cyclic Loop Penalty Detection</td>
                  <td className="highlight">Yes (Automated Jaccard)</td>
                  <td>Manual Filter</td>
                  <td>No</td>
                  <td>No</td>
                  <td>Latency Spikes</td>
                  <td>Session Timeouts</td>
                </tr>
                <tr>
                  <td className="feature">Zero-Cloud / Air-Gapped Local CI</td>
                  <td className="highlight">Yes (Local Binary / Python)</td>
                  <td>No (Requires Cloud SaaS)</td>
                  <td>No (Requires Cloud SaaS)</td>
                  <td>Partial</td>
                  <td>Yes (Local Server)</td>
                  <td>No (Requires Cloud SaaS)</td>
                </tr>
                <tr>
                  <td className="feature">CI/CD Gate Overhead</td>
                  <td className="highlight">&lt; 0.5s / Trace</td>
                  <td>3-15s (Cloud Roundtrip)</td>
                  <td>2-10s (Cloud Roundtrip)</td>
                  <td>2-8s (Cloud Roundtrip)</td>
                  <td>N/A (Dashboard Only)</td>
                  <td>N/A (Dashboard Only)</td>
                </tr>
                <tr>
                  <td className="feature">Cost per Deterministic Check</td>
                  <td className="highlight">$0.00 (Zero Token Cost)</td>
                  <td>SaaS Fee + LLM Tokens</td>
                  <td>SaaS Fee + LLM Tokens</td>
                  <td>LLM Tokens Only</td>
                  <td>Self-Hosted Infra</td>
                  <td>SaaS Fee Only</td>
                </tr>
                <tr>
                  <td className="feature">Native Framework Adapters</td>
                  <td className="highlight">LangChain, smolagents, REST, CLI</td>
                  <td>LangChain / LangGraph</td>
                  <td>Generic Python SDK</td>
                  <td>LlamaIndex, LangChain</td>
                  <td>LlamaIndex, LangChain</td>
                  <td>CrewAI, Autogen</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Developer Integration Code Switcher */}
      <section id="integration" className="section" style={{ background: '#0b0b0e' }}>
        <div className="container">
          <div className="section-header">
            <span className="badge badge-info" style={{ marginBottom: '12px' }}>
              DEVELOPER INTEGRATION
            </span>
            <h2 className="section-title">Integrate into Any Agent in Under 3 Minutes</h2>
            <p className="section-subtitle">
              Whether you are writing vanilla Python agents, using LangChain, smolagents, or building custom pipelines in Go or Rust, RegressionShield provides native drop-in adapters and an air-gapped REST ingestion API.
            </p>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <div className="tabs-nav">
              <button
                className={`tab-btn ${activeCodeTab === 'sdk' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('sdk')}
              >
                Python Core SDK
              </button>
              <button
                className={`tab-btn ${activeCodeTab === 'langchain' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('langchain')}
              >
                LangChain Callback
              </button>
              <button
                className={`tab-btn ${activeCodeTab === 'smolagents' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('smolagents')}
              >
                smolagents Adapter
              </button>
              <button
                className={`tab-btn ${activeCodeTab === 'decorator' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('decorator')}
              >
                @shield Decorator
              </button>
              <button
                className={`tab-btn ${activeCodeTab === 'cli' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('cli')}
              >
                CLI Quality Gate
              </button>
              <button
                className={`tab-btn ${activeCodeTab === 'rest' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('rest')}
              >
                REST Ingestion API
              </button>
            </div>
          </div>

          <div className="code-wrapper">
            <div className="code-header">
              <span>{activeCodeTab.toUpperCase()} CODE SNIPPET</span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(CODE_EXAMPLES[activeCodeTab]);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
                className="btn btn-secondary btn-sm"
                style={{ padding: '3px 8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}
              >
                {copied ? '[COPIED]' : 'COPY CODE'}
              </button>
            </div>
            <pre className="code-pre">
              <code>{CODE_EXAMPLES[activeCodeTab]}</code>
            </pre>
          </div>
        </div>
      </section>

      {/* CI/CD Quality Gate Pipeline Overview */}
      <section className="section">
        <div className="container">
          <div className="section-header">
            <span className="badge badge-info" style={{ marginBottom: '12px' }}>
              CI/CD WORKFLOW
            </span>
            <h2 className="section-title">Automated PR Blocking on Silent Regressions</h2>
            <p className="section-subtitle">
              Integrate RegressionShield directly into your GitHub Actions, GitLab CI, or pre-commit hooks to guarantee that no model prompt modification or system prompt update breaks reasoning integrity.
            </p>
          </div>

          <div className="grid-3">
            <div className="card">
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#71717a', marginBottom: '8px' }}>
                STAGE 01
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa', marginBottom: '10px' }}>
                Execution Trace Capture
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                Your test suite runs agent test cases. Traces are automatically collected via the LangChain tracer, smolagents adapter, or <code>evaluate_trace()</code> SDK.
              </p>
            </div>

            <div className="card">
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#71717a', marginBottom: '8px' }}>
                STAGE 02
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa', marginBottom: '10px' }}>
                Deterministic Audit Engine
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                The engine evaluates policy constraints, required sequences, forbidden tool combinations, and cyclic loop penalties in under 0.5s without making external network calls.
              </p>
            </div>

            <div className="card">
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#71717a', marginBottom: '8px' }}>
                STAGE 03
              </div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa', marginBottom: '10px' }}>
                PR Gate Enforcement
              </h3>
              <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                If candidate trace policy score drops or prerequisite violations are found, <code>regshield</code> exits with status code 1, automatically blocking the pull request merge.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section style={{
        padding: '80px 0',
        background: 'radial-gradient(circle at 50% 50%, rgba(24, 24, 27, 0.6) 0%, rgba(9, 9, 11, 1) 100%)',
        textAlign: 'center'
      }}>
        <div className="container">
          <h2 style={{ fontSize: '36px', fontWeight: 800, letterSpacing: '-0.02em', color: '#fafafa', marginBottom: '16px' }}>
            Enforce Quality Gates on Your AI Agents Today
          </h2>
          <p style={{ fontSize: '16px', color: '#a1a1aa', maxWidth: '600px', margin: '0 auto 32px auto', lineHeight: 1.6 }}>
            Install the open-source SDK, link your agent's execution traces, and never ship an inverted prerequisite or silent reasoning regression again.
          </p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', flexWrap: 'wrap' }}>
            <a href="/docs" className="btn btn-primary">
              Read Documentation {'[->]'}
            </a>
            <a href="https://github.com" target="_blank" rel="noreferrer" className="btn btn-secondary">
              Star on GitHub
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
