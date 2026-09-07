'use client';

import React, { useState } from 'react';

const DOC_SECTIONS = [
  { id: 'quickstart', title: 'Quickstart & Installation' },
  { id: 'policy-schema', title: 'Policy-as-Code Schema' },
  { id: 'core-metrics', title: 'Core Scoring Metrics' },
  { id: 'langchain-adapter', title: 'LangChain Adapter' },
  { id: 'smolagents-adapter', title: 'smolagents Adapter' },
  { id: 'decorator', title: '@shield Decorator' },
  { id: 'llm-judge', title: 'LLM-as-a-Judge Setup' },
  { id: 'cicd-gate', title: 'CI/CD Quality Gate (CLI)' },
  { id: 'rest-api', title: 'REST Ingestion API' },
];

export default function DocsPage() {
  const [activeDoc, setActiveDoc] = useState('quickstart');
  const [copiedSection, setCopiedSection] = useState(null);

  const copyCode = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedSection(id);
    setTimeout(() => setCopiedSection(null), 2000);
  };

  return (
    <div className="container" style={{ padding: '48px 24px 96px 24px' }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '260px 1fr',
        gap: '48px',
        alignItems: 'start'
      }}>
        {/* Sticky Sidebar Navigation */}
        <aside style={{
          position: 'sticky',
          top: '90px',
          background: '#0d0d10',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          padding: '16px',
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            textTransform: 'uppercase',
            color: '#71717a',
            letterSpacing: '0.05em',
            marginBottom: '14px',
            paddingBottom: '8px',
            borderBottom: '1px solid var(--border-subtle)'
          }}>
            DOCUMENTATION
          </div>

          <nav style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {DOC_SECTIONS.map((sec) => (
              <button
                key={sec.id}
                onClick={() => setActiveDoc(sec.id)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontFamily: 'var(--font-mono)',
                  background: activeDoc === sec.id ? 'var(--bg-subtle)' : 'transparent',
                  color: activeDoc === sec.id ? '#fafafa' : '#a1a1aa',
                  border: activeDoc === sec.id ? '1px solid var(--border)' : '1px solid transparent',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
              >
                {activeDoc === sec.id ? '-> ' : ''}{sec.title}
              </button>
            ))}
          </nav>
        </aside>

        {/* Main Content Area */}
        <article style={{ minWidth: 0 }}>
          {/* Quickstart */}
          {activeDoc === 'quickstart' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>GETTING STARTED</span>
              <h1 className="section-title">Quickstart &amp; Installation</h1>
              <p className="section-subtitle">
                RegressionShield is a lightweight, zero-cloud-telemetry Python library and CLI designed to enforce deterministic quality gates on autonomous AI agent execution traces.
              </p>

              <div style={{ marginTop: '32px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  1. Install via pip
                </h3>
                <div className="code-wrapper" style={{ marginBottom: '24px' }}>
                  <div className="code-header">
                    <span>TERMINAL</span>
                    <button
                      onClick={() => copyCode('pip install regression-shield', 'install')}
                      className="btn btn-secondary btn-sm"
                      style={{ padding: '2px 8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}
                    >
                      {copiedSection === 'install' ? '[COPIED]' : 'COPY'}
                    </button>
                  </div>
                  <pre className="code-pre">
                    <code>pip install regression-shield</code>
                  </pre>
                </div>

                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  2. Minimal Python Example
                </h3>
                <div className="code-wrapper" style={{ marginBottom: '24px' }}>
                  <div className="code-header">
                    <span>PYTHON (EVALUATE_TRACE.PY)</span>
                    <button
                      onClick={() => copyCode(`from regression_shield import evaluate_trace

# Your agent's reasoning trace
trace = [
    {
        "thought": "I will run the security audit first.",
        "tool": "security_scan",
        "tool_input": {"target": "repo"},
        "observation": "Vulnerabilities: 0"
    },
    {
        "thought": "Security check clean. Proceeding to push release.",
        "tool": "publish_release",
        "tool_input": {"tag": "v1.0.0"},
        "observation": "Published"
    }
]

# Run deterministic audit
result = evaluate_trace(
    trace,
    policy={
        "required_tools": ["security_scan"],
        "max_tool_calls": 4
    }
)

print(f"Passed: {result.passed}")
print(f"Score: {result.composite_score:.2f}")
if not result.passed:
    print(f"Regressions detected: {result.regressions}")`, 'py-min')}
                      className="btn btn-secondary btn-sm"
                      style={{ padding: '2px 8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}
                    >
                      {copiedSection === 'py-min' ? '[COPIED]' : 'COPY'}
                    </button>
                  </div>
                  <pre className="code-pre">
                    <code>{`from regression_shield import evaluate_trace

# Your agent's reasoning trace
trace = [
    {
        "thought": "I will run the security audit first.",
        "tool": "security_scan",
        "tool_input": {"target": "repo"},
        "observation": "Vulnerabilities: 0"
    },
    {
        "thought": "Security check clean. Proceeding to push release.",
        "tool": "publish_release",
        "tool_input": {"tag": "v1.0.0"},
        "observation": "Published"
    }
]

# Run deterministic audit
result = evaluate_trace(
    trace,
    policy={
        "required_tools": ["security_scan"],
        "max_tool_calls": 4
    }
)

print(f"Passed: {result.passed}")
print(f"Score: {result.composite_score:.2f}")
if not result.passed:
    print(f"Regressions detected: {result.regressions}")`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* Policy Schema */}
          {activeDoc === 'policy-schema' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>SPECIFICATION</span>
              <h1 className="section-title">Policy-as-Code Schema</h1>
              <p className="section-subtitle">
                Policies define the immutable boundaries, required sequences, and forbidden tool combinations that an agent must respect. Policies can be declared in Python dictionaries or YAML files.
              </p>

              <div style={{ marginTop: '32px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  Complete YAML Policy Example (policy.yaml)
                </h3>
                <div className="code-wrapper" style={{ marginBottom: '24px' }}>
                  <div className="code-header">
                    <span>POLICY.YAML</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`# RegressionShield Policy-as-Code Schema
required_tools:
  - run_unit_tests
  - verify_security_credentials

forbidden_tools:
  - force_push_to_main
  - bypass_payment_gateway

forbidden_tool_pairs:
  # Disallows calling tool B after tool A without intermediate validation
  - [read_user_secrets, send_external_webhook]
  - [deploy_production, run_unit_tests] # Inverted prerequisite check

max_tool_calls: 6
min_thought_length: 20
allow_duplicate_tool_calls: false`}</code>
                  </pre>
                </div>

                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  Field Definitions
                </h3>
                <div className="table-container">
                  <table className="comparison-table">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Type</th>
                        <th>Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><code>required_tools</code></td>
                        <td><code>list[str]</code></td>
                        <td>Tools that must be called at least once in the trace. If omitted, policy compliance score drops to 0.0.</td>
                      </tr>
                      <tr>
                        <td><code>forbidden_tools</code></td>
                        <td><code>list[str]</code></td>
                        <td>Tools that are completely blacklisted. If called, immediate gate rejection.</td>
                      </tr>
                      <tr>
                        <td><code>forbidden_tool_pairs</code></td>
                        <td><code>list[list[str]]</code></td>
                        <td>Sequence constraints. Disallows calling the second tool after the first tool without satisfying policy gates.</td>
                      </tr>
                      <tr>
                        <td><code>max_tool_calls</code></td>
                        <td><code>int</code></td>
                        <td>Maximum allowed tool executions. Traces exceeding this budget incur steep efficiency penalties.</td>
                      </tr>
                      <tr>
                        <td><code>min_thought_length</code></td>
                        <td><code>int</code></td>
                        <td>Enforces that the model articulates reasoning steps before invoking tools (prevents blind action thrashing).</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Core Metrics */}
          {activeDoc === 'core-metrics' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>EVALUATION ALGORITHMS</span>
              <h1 className="section-title">Core Scoring Metrics</h1>
              <p className="section-subtitle">
                RegressionShield combines deterministic rule validation with ReAct reasoning density metrics to produce an uncompromised quality score between 0.0 and 1.0.
              </p>

              <div style={{ marginTop: '32px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa' }}>1. Policy Compliance Score (Weight: 40%)</h3>
                    <span className="badge badge-pass">100% DETERMINISTIC</span>
                  </div>
                  <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                    Evaluates strict adherence to <code>required_tools</code>, <code>forbidden_tools</code>, and <code>forbidden_tool_pairs</code>. Any security violation drops this score to 0.0 and immediately flags the pull request for blocking.
                  </p>
                </div>

                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa' }}>2. Loop Thrashing Penalty (Weight: 20%)</h3>
                    <span className="badge badge-pass">AUTOMATED JACCARD</span>
                  </div>
                  <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                    Measures repetition of identical tool calls and arguments across steps. Applies a negative penalty (-0.1 to -1.0) when the agent enters cyclic loops without making state progress.
                  </p>
                </div>

                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa' }}>3. Goal Attainment Score (Weight: 25%)</h3>
                    <span className="badge badge-info">HYBRID EVAL</span>
                  </div>
                  <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                    Verifies that the agent reached a terminal success state, resolved the user query, and provided verified artifact citations without unhandled exceptions.
                  </p>
                </div>

                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fafafa' }}>4. ReAct Reasoning Efficiency (Weight: 15%)</h3>
                    <span className="badge badge-info">RATIO ANALYSIS</span>
                  </div>
                  <p style={{ fontSize: '13px', color: '#a1a1aa', lineHeight: 1.6 }}>
                    Computes the ratio of purposeful tool executions relative to budget. Penalizes erratic step generation where thoughts do not logically justify downstream tool actions.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* LangChain Adapter */}
          {activeDoc === 'langchain-adapter' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>FRAMEWORK INTEGRATION</span>
              <h1 className="section-title">LangChain &amp; LangGraph Adapter</h1>
              <p className="section-subtitle">
                Drop in the <code>RegressionShieldTracer</code> callback to transparently capture execution traces from any LangChain AgentExecutor or LangGraph workflow without altering existing agent code.
              </p>

              <div style={{ marginTop: '32px' }}>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>LANGCHAIN_AGENT.PY</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from regression_shield.adapters.langchain import RegressionShieldTracer

# 1. Initialize tracer with strict policy rules
tracer = RegressionShieldTracer(
    policy={
        "required_tools": ["lookup_customer", "validate_policy"],
        "max_tool_calls": 6
    }
)

# 2. Attach tracer callback
agent_executor = AgentExecutor(agent=agent, tools=tools)
result = agent_executor.invoke(
    {"input": "Cancel renewal for customer 99401"},
    config={"callbacks": [tracer]}
)

# 3. Retrieve audited trace and evaluation result
eval_summary = tracer.get_evaluation()
print(f"Policy Score: {eval_summary.policy_compliance_score}")
print(f"Passed Gate: {eval_summary.passed}")`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* smolagents Adapter */}
          {activeDoc === 'smolagents-adapter' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>FRAMEWORK INTEGRATION</span>
              <h1 className="section-title">Hugging Face smolagents Adapter</h1>
              <p className="section-subtitle">
                Hugging Face's <code>smolagents</code> provides lightweight code and tool agents. RegressionShield normalizes <code>agent.logs</code> and step memories into a standardized execution trace format.
              </p>

              <div style={{ marginTop: '32px' }}>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>SMOLAGENTS_EVAL.PY</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`from smolagents import CodeAgent, HfApiModel
from regression_shield.adapters.smolagents import extract_smolagents_trace
from regression_shield import evaluate_trace

agent = CodeAgent(tools=[...], model=HfApiModel())
output = agent.run("Refactor legacy repository files and run tests")

# Extract normalized trace
trace = extract_smolagents_trace(agent)

# Evaluate against quality gate
result = evaluate_trace(
    trace,
    policy={"required_tools": ["run_tests"]}
)

print(f"Quality Gate Verdict: {result.passed}")
print(f"Composite Score: {result.composite_score}")`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* @shield Decorator */}
          {activeDoc === 'decorator' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>ZERO BOILERPLATE</span>
              <h1 className="section-title">Function Decorator (@shield)</h1>
              <p className="section-subtitle">
                Wrap any agentic pipeline function with <code>@shield</code> to automatically intercept return values, inspect traces, log diagnostics, or raise exceptions on regression.
              </p>

              <div style={{ marginTop: '32px' }}>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>PIPELINE.PY</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`from regression_shield import shield

@shield(
    policy={
        "forbidden_tool_pairs": [["access_credentials", "send_external_webhook"]],
        "max_tool_calls": 5
    },
    on_violation="raise"  # Options: "raise", "warn", "log"
)
def run_autonomous_pipeline(task_prompt: str):
    # Your agent's reasoning loop
    agent_output = run_my_agent(task_prompt)
    return agent_output`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* LLM Judge */}
          {activeDoc === 'llm-judge' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>HYBRID EVALUATION</span>
              <h1 className="section-title">LLM-as-a-Judge Setup</h1>
              <p className="section-subtitle">
                While deterministic rules handle security, sequence order, and loop thrashing, an optional LLM-as-a-Judge layer can score qualitative reasoning clarity and subjective goal attainment.
              </p>

              <div style={{ marginTop: '32px' }}>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>JUDGE_CONFIG.PY</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`from regression_shield import evaluate_trace

# Supports OpenRouter, Gemini, OpenAI, and Anthropic
result = evaluate_trace(
    trace,
    policy={"required_tools": ["fetch_doc"]},
    judge_provider="openrouter",
    judge_model="meta-llama/llama-3.3-70b-instruct",
    api_key="sk-or-v1-..."  # Or set OPENROUTER_API_KEY env var
)

print(f"Qualitative Score: {result.judge_score}")
print(f"Judge Critique: {result.judge_critique}")`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* CI/CD Gate */}
          {activeDoc === 'cicd-gate' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>CI/CD AUTOMATION</span>
              <h1 className="section-title">GitHub Actions &amp; CLI Quality Gate</h1>
              <p className="section-subtitle">
                Block pull requests automatically whenever a prompt tweak causes agent reasoning degradation or violates policy.
              </p>

              <div style={{ marginTop: '32px' }}>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>.GITHUB/WORKFLOWS/AGENT_GATE.YML</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`name: Agent Quality Gate

on: [pull_request]

jobs:
  evaluate-agent-reasoning:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install RegressionShield
        run: pip install regression-shield

      - name: Run Agent Test Suite
        run: python run_agent_evals.py --output candidate_trace.json

      - name: Enforce Policy Quality Gate
        run: |
          regshield check \\
            --trace ./candidate_trace.json \\
            --baseline ./baselines/approved_trace.json \\
            --policy ./policy.yaml \\
            --fail-on-regression`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* REST API */}
          {activeDoc === 'rest-api' && (
            <div>
              <span className="badge badge-info" style={{ marginBottom: '12px' }}>REST INTERFACE</span>
              <h1 className="section-title">REST Ingestion API</h1>
              <p className="section-subtitle">
                Run RegressionShield as an air-gapped local microservice to evaluate traces from non-Python agents written in Go, Rust, TypeScript, or Java.
              </p>

              <div style={{ marginTop: '32px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  Start Local REST Server
                </h3>
                <div className="code-wrapper" style={{ marginBottom: '24px' }}>
                  <div className="code-header">
                    <span>TERMINAL</span>
                  </div>
                  <pre className="code-pre">
                    <code>regshield serve --port 8000</code>
                  </pre>
                </div>

                <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#fafafa', marginBottom: '12px' }}>
                  POST /api/evaluate-trace
                </h3>
                <div className="code-wrapper">
                  <div className="code-header">
                    <span>CURL</span>
                  </div>
                  <pre className="code-pre">
                    <code>{`curl -X POST http://localhost:8000/api/evaluate-trace \\
  -H "Content-Type: application/json" \\
  -d '{
    "trace": [
      {
        "thought": "Checking user authentication state",
        "tool": "verify_auth",
        "tool_input": {"uid": "usr_992"},
        "observation": "AUTHORIZED"
      }
    ],
    "policy": {
      "required_tools": ["verify_auth"],
      "max_tool_calls": 3
    }
  }'`}</code>
                  </pre>
                </div>
              </div>
            </div>
          )}
        </article>
      </div>
    </div>
  );
}
